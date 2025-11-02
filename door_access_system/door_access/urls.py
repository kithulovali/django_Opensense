from django.urls import path
from . import views

urlpatterns = [
    path('', views.user_dashboard, name='user_dashboard'),
    path('register/', views.register, name='register'),
    path('enroll/', views.enroll, name='enroll'),
    path('api/enroll/', views.api_enroll, name='api_enroll'),
    # ESP32 uploads JPEG here
    path('api/verify_open/', views.api_verify_open_device, name='api_verify_open_device'),
    # Existing web button flow (pull from ESP32) preserved under a different path if used
    path('api/verify_open_pull/', views.api_verify_and_open, name='api_verify_and_open'),
    path('api/camera_diag/', views.api_camera_diag, name='api_camera_diag'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('api/admin/door_command/', views.api_door_command, name='api_door_command'),
]
