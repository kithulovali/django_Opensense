from django.conf import settings
from django.db import models
from django.utils import timezone


class Door(models.Model):
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class FaceProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='faces/')
    encoding = models.BinaryField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"FaceProfile({self.user.username})"


class DoorAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    door = models.ForeignKey(Door, on_delete=models.CASCADE)
    allowed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'door')

    def __str__(self):
        return f"{self.user} -> {self.door} ({'ALLOWED' if self.allowed else 'DENIED'})"


class AccessLog(models.Model):
    STATUS_CHOICES = (
        ('OPEN', 'OPEN'),
        ('CLOSE', 'CLOSE'),
        ('DENIED', 'DENIED'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    door = models.ForeignKey(Door, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.timestamp} {self.user} {self.door} {self.status}"
