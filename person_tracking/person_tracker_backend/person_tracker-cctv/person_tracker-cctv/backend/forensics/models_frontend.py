from django.db import models
from django.contrib.auth.models import User
import uuid

class UserSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='settings')
    theme = models.CharField(max_length=20, default='dark')
    notifications = models.BooleanField(default=True)
    auto_save_streams = models.BooleanField(default=True)
    default_detection_mode = models.CharField(max_length=20, default='hybrid')
    default_threshold = models.FloatField(default=50)

class SystemActivity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    activity_type = models.CharField(max_length=50)
    message = models.TextField()
    color = models.CharField(max_length=20, default='blue')

    class Meta:
        ordering = ['-timestamp']
