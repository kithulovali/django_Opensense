from django.contrib import admin
from .models import Door, DoorAccess, FaceProfile, AccessLog


@admin.register(Door)
class DoorAdmin(admin.ModelAdmin):
    list_display = ('name', 'location')
    search_fields = ('name', 'location')


@admin.register(DoorAccess)
class DoorAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'door', 'allowed')
    list_filter = ('allowed', 'door')
    search_fields = ('user__username',)


@admin.register(FaceProfile)
class FaceProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__username',)


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'door', 'status')
    list_filter = ('status', 'door')
    search_fields = ('user__username',)
    ordering = ('-timestamp',)
