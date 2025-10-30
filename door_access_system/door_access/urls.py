from django.urls import path
from . import views

urlpatterns = [
    path('', views.user_dashboard, name='user_dashboard'),
    path('register/', views.register, name='register'),
    path('enroll/', views.enroll, name='enroll'),
    path('api/enroll/', views.api_enroll, name='api_enroll'),
    path('api/verify_open/', views.api_verify_and_open, name='api_verify_and_open'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('api/admin/door_command/', views.api_door_command, name='api_door_command'),
]
