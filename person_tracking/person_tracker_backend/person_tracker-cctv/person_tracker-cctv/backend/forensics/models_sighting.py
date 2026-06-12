from django.db import models
from .models import ForensicCase

class SuspectSighting(models.Model):
    case = models.ForeignKey(ForensicCase, on_delete=models.CASCADE, related_name='sightings')
    track_id = models.IntegerField()
    start_time = models.FloatField()  # Seconds
    end_time = models.FloatField()    # Seconds
    clip_file = models.FileField(upload_to='outputs/sightings/')
    max_score = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_time']