"""
Django models for CCTV stream management and live tracking.
"""
from django.db import models
import uuid
from .models import ForensicCase


class CCTVStream(models.Model):
    """Represents a registered CCTV camera/RTSP source."""
    STATUS_CHOICES = [
        ('IDLE', 'Idle'),
        ('CONNECTED', 'Connected'),
        ('DISCONNECTED', 'Disconnected'),
        ('ERROR', 'Error'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    rtsp_url = models.CharField(max_length=500)
    location = models.CharField(max_length=200, blank=True, default='')
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IDLE')
    last_frame_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.status})"

    class Meta:
        ordering = ['created_at']


class LiveTrackingSession(models.Model):
    """A live tracking session across one or more CCTV streams."""
    STATUS_CHOICES = [
        ('STARTING', 'Starting'),
        ('RUNNING', 'Running'),
        ('STOPPING', 'Stopping'),
        ('STOPPED', 'Stopped'),
        ('ERROR', 'Error'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(ForensicCase, on_delete=models.CASCADE, related_name='live_sessions')
    streams = models.ManyToManyField(CCTVStream, related_name='sessions', blank=True)
    mode = models.CharField(max_length=10, default='hybrid')
    threshold = models.FloatField(default=0.55)
    started_at = models.DateTimeField(auto_now_add=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='STARTING')

    def __str__(self):
        return f"Session {self.id} ({self.status})"

    class Meta:
        ordering = ['-started_at']


class LiveAlert(models.Model):
    """A real-time detection alert from a live tracking session."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(LiveTrackingSession, on_delete=models.CASCADE, related_name='alerts')
    stream = models.ForeignKey(CCTVStream, on_delete=models.CASCADE, related_name='alerts')
    timestamp = models.DateTimeField(auto_now_add=True)
    frame_number = models.IntegerField(default=0)
    confidence = models.FloatField()
    track_id = models.IntegerField(default=-1)
    thumbnail = models.ImageField(upload_to='outputs/live_alerts/thumbs/', null=True, blank=True)
    clip_file = models.FileField(upload_to='outputs/live_alerts/clips/', null=True, blank=True)

    def __str__(self):
        return f"Alert {self.id} ({self.confidence:.2f}) on {self.stream.name}"

    class Meta:
        ordering = ['-timestamp']
