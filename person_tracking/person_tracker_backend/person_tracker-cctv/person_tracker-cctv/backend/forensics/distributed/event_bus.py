"""
Event Bus — Async Inter-Service Communication Layer.

Provides a unified messaging interface supporting multiple backends:
  - Redis Pub/Sub (default, low-latency, single-node)
  - Kafka (city-scale, persistent, multi-consumer)
  - In-Memory (development/testing, no external deps)

Message types:
  - ALERT:        Target detection events → frontend WebSocket
  - SIGHTING:     Sighting clip completed → evidence pipeline
  - TRACK_UPDATE: Track state changes → cross-camera ReID
  - HEALTH:       Worker health reports → load balancer
  - COMMAND:      Control plane commands → worker management
  - METRIC:       Performance metrics → observability

Usage:
    bus = EventBus.create('redis', host='localhost', port=6379)

    # Publish
    bus.publish('alerts', {'stream_id': 'cam_001', 'score': 0.92, ...})

    # Subscribe
    bus.subscribe('alerts', callback=handle_alert)

    # Request-reply
    response = bus.request('worker.health', {'worker_id': 'gpu_0'})
"""
import time
import json
import threading
import queue
import logging
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(Enum):
    ALERT = 'alert'
    SIGHTING = 'sighting'
    TRACK_UPDATE = 'track_update'
    HEALTH = 'health'
    COMMAND = 'command'
    METRIC = 'metric'
    STREAM_STATE = 'stream_state'


@dataclass
class Event:
    """A single event on the bus."""
    event_type: str
    channel: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    source: str = ''
    event_id: str = ''

    def to_json(self) -> str:
        return json.dumps({
            'event_type': self.event_type,
            'channel': self.channel,
            'payload': self.payload,
            'timestamp': self.timestamp,
            'source': self.source,
            'event_id': self.event_id,
        })

    @classmethod
    def from_json(cls, data: str) -> 'Event':
        d = json.loads(data)
        return cls(**d)


class EventBusBackend:
    """Abstract backend interface."""

    def publish(self, channel: str, message: str):
        raise NotImplementedError

    def subscribe(self, channel: str, callback: Callable):
        raise NotImplementedError

    def unsubscribe(self, channel: str):
        raise NotImplementedError

    def close(self):
        pass


class InMemoryBackend(EventBusBackend):
    """
    In-memory event bus for development and testing.
    No external dependencies required.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    def publish(self, channel: str, message: str):
        with self._lock:
            callbacks = self._subscribers.get(channel, [])[:]
        for cb in callbacks:
            try:
                cb(channel, message)
            except Exception as e:
                logger.error(f"InMemory subscriber error on '{channel}': {e}")

    def subscribe(self, channel: str, callback: Callable):
        with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
            self._subscribers[channel].append(callback)

    def unsubscribe(self, channel: str):
        with self._lock:
            self._subscribers.pop(channel, None)


class RedisBackend(EventBusBackend):
    """
    Redis Pub/Sub backend for low-latency single-node messaging.
    """

    def __init__(self, host: str = 'localhost', port: int = 6379,
                 db: int = 0, password: Optional[str] = None):
        self._redis = None
        self._pubsub = None
        self._threads: Dict[str, threading.Thread] = {}
        self._running = True

        try:
            import redis
            self._redis = redis.Redis(
                host=host, port=port, db=db, password=password,
                decode_responses=True
            )
            self._pubsub = self._redis.pubsub()
            logger.info(f"Redis EventBus connected: {host}:{port}")
        except ImportError:
            logger.warning("redis-py not installed — falling back to InMemory backend")
            raise
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            raise

    def publish(self, channel: str, message: str):
        if self._redis:
            self._redis.publish(channel, message)

    def subscribe(self, channel: str, callback: Callable):
        if self._pubsub is None:
            return

        def _listener():
            self._pubsub.subscribe(channel)
            for msg in self._pubsub.listen():
                if not self._running:
                    break
                if msg['type'] == 'message':
                    try:
                        callback(msg['channel'], msg['data'])
                    except Exception as e:
                        logger.error(f"Redis subscriber error: {e}")

        t = threading.Thread(target=_listener, daemon=True, name=f"Redis-Sub-{channel}")
        t.start()
        self._threads[channel] = t

    def unsubscribe(self, channel: str):
        if self._pubsub:
            self._pubsub.unsubscribe(channel)

    def close(self):
        self._running = False
        if self._pubsub:
            self._pubsub.close()
        if self._redis:
            self._redis.close()


class KafkaBackend(EventBusBackend):
    """
    Kafka backend for city-scale persistent messaging.
    """

    def __init__(self, bootstrap_servers: str = 'localhost:9092',
                 group_id: str = 'forensic-pipeline'):
        self._producer = None
        self._consumers: Dict[str, Any] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._running = True

        try:
            from kafka import KafkaProducer
            self._producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: v.encode('utf-8'),
            )
            self._bootstrap = bootstrap_servers
            self._group_id = group_id
            logger.info(f"Kafka EventBus connected: {bootstrap_servers}")
        except ImportError:
            logger.warning("kafka-python not installed — falling back")
            raise
        except Exception as e:
            logger.error(f"Kafka connection failed: {e}")
            raise

    def publish(self, channel: str, message: str):
        if self._producer:
            self._producer.send(channel, value=message)

    def subscribe(self, channel: str, callback: Callable):
        try:
            from kafka import KafkaConsumer

            consumer = KafkaConsumer(
                channel,
                bootstrap_servers=self._bootstrap,
                group_id=self._group_id,
                value_deserializer=lambda v: v.decode('utf-8'),
                auto_offset_reset='latest',
            )
            self._consumers[channel] = consumer

            def _listener():
                for msg in consumer:
                    if not self._running:
                        break
                    try:
                        callback(channel, msg.value)
                    except Exception as e:
                        logger.error(f"Kafka subscriber error: {e}")

            t = threading.Thread(target=_listener, daemon=True, name=f"Kafka-Sub-{channel}")
            t.start()
            self._threads[channel] = t

        except Exception as e:
            logger.error(f"Kafka subscribe failed: {e}")

    def close(self):
        self._running = False
        if self._producer:
            self._producer.close()
        for consumer in self._consumers.values():
            consumer.close()


class EventBus:
    """
    Unified event bus with pluggable backends.

    Usage:
        bus = EventBus.create('redis', host='localhost')
        bus.publish('alerts', {'type': 'target_detected', ...})
        bus.subscribe('alerts', callback=handle_alert)
    """

    def __init__(self, backend: EventBusBackend, source: str = ''):
        self._backend = backend
        self._source = source
        self._publish_count = 0
        self._subscribe_count = 0

    @classmethod
    def create(cls, backend_type: str = 'memory',
               source: str = '', **kwargs) -> 'EventBus':
        """
        Factory: create an EventBus with the specified backend.

        Args:
            backend_type: 'memory', 'redis', or 'kafka'.
            source: Source identifier for published events.
            **kwargs: Backend-specific configuration.
        """
        if backend_type == 'redis':
            try:
                backend = RedisBackend(**kwargs)
            except Exception:
                logger.warning("Redis unavailable — falling back to InMemory")
                backend = InMemoryBackend()
        elif backend_type == 'kafka':
            try:
                backend = KafkaBackend(**kwargs)
            except Exception:
                logger.warning("Kafka unavailable — falling back to InMemory")
                backend = InMemoryBackend()
        else:
            backend = InMemoryBackend()

        logger.info(f"EventBus created: backend={backend.__class__.__name__}")
        return cls(backend, source=source)

    def publish(self, channel: str, payload: Dict[str, Any],
                event_type: str = ''):
        """Publish an event to a channel."""
        import uuid
        event = Event(
            event_type=event_type or channel,
            channel=channel,
            payload=payload,
            source=self._source,
            event_id=uuid.uuid4().hex[:12],
        )
        self._backend.publish(channel, event.to_json())
        self._publish_count += 1

    def subscribe(self, channel: str, callback: Callable):
        """
        Subscribe to a channel.

        Callback signature: callback(channel: str, event: Event)
        """
        def _wrapper(ch, raw_msg):
            try:
                event = Event.from_json(raw_msg)
                callback(ch, event)
            except Exception:
                callback(ch, raw_msg)

        self._backend.subscribe(channel, _wrapper)
        self._subscribe_count += 1

    def close(self):
        """Close the event bus and release resources."""
        self._backend.close()

    def get_metrics(self) -> dict:
        return {
            'backend': self._backend.__class__.__name__,
            'source': self._source,
            'published': self._publish_count,
            'subscriptions': self._subscribe_count,
        }
