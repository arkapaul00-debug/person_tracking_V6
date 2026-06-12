from django.db import models
import uuid

class ForensicCase(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('ERROR', 'Error'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    mode = models.CharField(max_length=10, default='hybrid')
    threshold = models.FloatField(default=0.75)
    output_video = models.FileField(upload_to='outputs/', null=True, blank=True)

    def __str__(self):
        return f"Case {self.id} - {self.status}"

class EvidenceVideo(models.Model):
    case = models.OneToOneField(ForensicCase, on_delete=models.CASCADE, related_name='video')
    file = models.FileField(upload_to='evidence/videos/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

class ReferenceImage(models.Model):
    case = models.ForeignKey(ForensicCase, on_delete=models.CASCADE, related_name='references')
    file = models.ImageField(upload_to='evidence/refs/')

class AnalysisLog(models.Model):
    case = models.ForeignKey(ForensicCase, on_delete=models.CASCADE, related_name='logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    message = models.TextField()
    log_type = models.CharField(max_length=10, default='info') # 'info' or 'alert'

    class Meta:
        ordering = ['-timestamp']

class RuntimeConfig(models.Model):
    """
    Centralized configuration management.
    These settings are cached in Redis and read by distributed workers
    to adjust thresholds without restarting the application.
    """
    key = models.CharField(max_length=100, unique=True, primary_key=True)
    value_json = models.TextField(help_text="JSON serialized value")
    description = models.CharField(max_length=255, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.key}: {self.value_json}"

class AuditLog(models.Model):
    """
    Immutable audit trail for all forensic actions and data access.
    Essential for compliance and chain of custody.
    """
    action = models.CharField(max_length=100) # e.g. "VIEW_EVIDENCE", "START_TRACKING"
    user_id = models.CharField(max_length=100, blank=True, help_text="ID of the user who performed the action")
    resource_id = models.CharField(max_length=100, blank=True, help_text="ID of the affected case/camera/evidence")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata_json = models.TextField(blank=True, default="{}")

    class Meta:
        ordering = ['-timestamp']
        
    def __str__(self):
        return f"{self.timestamp} - {self.user_id} - {self.action}"