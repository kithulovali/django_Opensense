import io
import os
import pickle
import requests
import cv2
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import EnrollmentForm, RegistrationForm
from .models import AccessLog, Door, DoorAccess, FaceProfile
from .mqtt import send_command
from .utils.face import encode_image_file, compare_encoding_to_image
from .utils.camera import fetch_frame
import numpy as np

ESP32_URL = os.environ.get('ESP32_URL', 'http://192.168.137.88/capture')


def is_staff(user):
    return user.is_staff


def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
            )
            login(request, user)
            return redirect('user_dashboard')
    else:
        form = RegistrationForm()
    return render(request, 'registration/register.html', {'form': form})


@login_required
def user_dashboard(request):
    profile = FaceProfile.objects.filter(user=request.user).first()
    logs = AccessLog.objects.filter(user=request.user).order_by('-timestamp')[:20]
    doors = Door.objects.filter(dooraccess__user=request.user, dooraccess__allowed=True).distinct()
    return render(request, 'user/dashboard.html', {'profile': profile, 'logs': logs, 'doors': doors})


@login_required
@require_http_methods(["GET", "POST"])
def enroll(request):
    profile = FaceProfile.objects.filter(user=request.user).first()
    if request.method == 'POST':
        form = EnrollmentForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            encoding = encode_image_file(obj.image)
            if encoding is None:
                messages.error(request, 'No face detected. Try another image.')
            else:
                obj.encoding = encoding
                obj.save()
                messages.success(request, 'Enrollment successful!')
                return redirect('user_dashboard')
    else:
        form = EnrollmentForm(instance=profile)
    return render(request, 'enrollment/upload.html', {'form': form, 'profile': profile})


# APIs
@login_required
@require_http_methods(["POST"])
def api_enroll(request):
    image = request.FILES.get('image')
    if not image:
        return JsonResponse({'error': 'image required'}, status=400)
    encoding = encode_image_file(image)
    if encoding is None:
        return JsonResponse({'error': 'no face detected'}, status=400)
    profile, _ = FaceProfile.objects.get_or_create(user=request.user)
    profile.image = image
    profile.encoding = encoding
    profile.save()
    return JsonResponse({'ok': True})


@login_required
@require_http_methods(["POST"]) 
def api_verify_and_open(request):
    door_id = int(request.POST.get('door_id', '0'))
    door = get_object_or_404(Door, id=door_id)
    profile = FaceProfile.objects.filter(user=request.user).first()
    if not profile or not profile.encoding:
        AccessLog.objects.create(user=request.user, door=door, status='DENIED', note='No profile')
        return JsonResponse({'error': 'not enrolled'}, status=403)

    frame = fetch_frame(ESP32_URL)
    if frame is None:
        return JsonResponse({'error': 'invalid frame'}, status=500)

    allowed = DoorAccess.objects.filter(user=request.user, door=door, allowed=True).exists()
    match = compare_encoding_to_image(profile.encoding, frame)

    if match and allowed:
        send_command(door.id, 'OPEN')
        AccessLog.objects.create(user=request.user, door=door, status='OPEN')
        return JsonResponse({'ok': True, 'status': 'OPEN'})

    AccessLog.objects.create(user=request.user, door=door, status='DENIED', note='Match' if match else 'No match')
    return JsonResponse({'ok': False, 'status': 'DENIED'})


@user_passes_test(is_staff)
@require_http_methods(["GET"])
def admin_dashboard(request):
    recent_logs = AccessLog.objects.select_related('user', 'door').order_by('-timestamp')[:20]
    total_users = User.objects.count()
    total_doors = Door.objects.count()
    total_access = DoorAccess.objects.filter(allowed=True).count()
    return render(request, 'admin/dashboard.html', {
        'recent_logs': recent_logs,
        'total_users': total_users,
        'total_doors': total_doors,
        'total_access': total_access,
    })


@user_passes_test(is_staff)
@require_http_methods(["POST"])
def api_door_command(request):
    door_id = int(request.POST.get('door_id', '0'))
    command = request.POST.get('command', 'OPEN').upper()
    if command not in ("OPEN", "CLOSE"):
        return JsonResponse({'error': 'invalid command'}, status=400)
    door = get_object_or_404(Door, id=door_id)
    send_command(door.id, command)
    AccessLog.objects.create(user=request.user, door=door, status=command)
    return JsonResponse({'ok': True, 'status': command})
