import uuid
from django.conf import settings
from django.db import models

class Workspace(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

class AuditEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

class RateBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.BigIntegerField(db_index=True)
