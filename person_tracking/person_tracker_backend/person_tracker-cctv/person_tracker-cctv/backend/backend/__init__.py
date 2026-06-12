import os

# Only eagerly load Celery if Redis/broker is expected to be available.
# This prevents the app from crashing on startup when running locally
# without Redis (i.e., the default development workflow).
try:
    if os.environ.get('USE_CELERY', '0') == '1':
        from .celery import app as celery_app
        __all__ = ('celery_app',)
    else:
        celery_app = None
        __all__ = ()
except Exception:
    celery_app = None
    __all__ = ()
