import io
import os
import pickle
import requests
import cv2
import time
import threading
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator

from .forms import EnrollmentForm, RegistrationForm
from .models import AccessLog, Door, DoorAccess, FaceProfile
from .mqtt import send_command
from .utils.face import encode_image_file, compare_encoding_to_image, detect_face_count
from .utils.camera import fetch_frame
import numpy as np
import base64

ESP32_URL = os.environ.get('ESP32_URL', 'http://192.168.0.123/jpg')


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
def user_logs(request):
    logs_qs = AccessLog.objects.filter(user=request.user).order_by('-timestamp')
    paginator = Paginator(logs_qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'user/logs.html', {
        'page_obj': page_obj,
    })


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
    door_id_str = request.POST.get('door_id', '').strip()
    if not door_id_str.isdigit():
        return JsonResponse({'ok': False, 'status': 'ERROR', 'error': 'door_required', 'message': 'Please select a door'}, status=400)
    door_id = int(door_id_str)
    # Prefer provided camera_url; otherwise, use last seen ESP32 IP from cache; fallback to ESP32_URL
    camera_url = request.POST.get('camera_url')
    if not camera_url:
        last_ip = cache.get('esp32_ip')
        if last_ip:
            camera_url = f"http://{last_ip}/jpg"
        else:
            camera_url = ESP32_URL
    door = get_object_or_404(Door, id=door_id)
    profile = FaceProfile.objects.filter(user=request.user).first()
    if not profile or not profile.encoding:
        AccessLog.objects.create(user=request.user, door=door, status='DENIED', note='No profile')
        return JsonResponse({'ok': False, 'status': 'DENIED', 'error': 'not_enrolled', 'message': 'User not enrolled with a face profile'}, status=403)

    # Multi-frame confirmation settings
    frame_count = getattr(settings, 'FACE_MULTI_FRAME_COUNT', 3)
    required_matches = getattr(settings, 'FACE_MULTI_FRAME_REQUIRED', 2)
    delay_ms = getattr(settings, 'FACE_MULTI_FRAME_DELAY_MS', 150)
    # For pull-based verification (dashboard provides camera_url), prefer low-latency single-frame check
    if request.POST.get('camera_url'):
        frame_count = 1
        required_matches = 1
        delay_ms = 0

    allowed = DoorAccess.objects.filter(user=request.user, door=door, allowed=True).exists()

    matches = 0
    saw_face = 0
    multiple_faces_detected = False

    def _urls_to_try(u: str):
        u = (u or '').strip()
        candidates = []
        if not u:
            return candidates
        lower = u.lower()
        # Prefer snapshot endpoint
        if '/stream' in lower:
            candidates.append(u.lower().replace('/stream', '/jpg'))
        if '?action=stream' in lower:
            candidates.append(u.replace('?action=stream', '?action=snapshot'))
        candidates.append(u)
        # Common alternatives
        base = u.rsplit('?', 1)[0]
        if not base.lower().endswith(('/jpg', '/jpeg', '/capture', '/photo', '/snapshot')):
            for alt in ('/jpg', '/capture', '/photo', '/snapshot'):
                if not base.endswith(alt):
                    candidates.append(base.rstrip('/') + alt)
        # Query-style alternatives (e.g., mjpg-streamer)
        if '?action=' in u and 'snapshot' not in lower:
            candidates.append(u.split('?', 1)[0] + '?action=snapshot')
        # De-dup preserving order
        seen = set()
        ordered = []
        for c in candidates:
            if c not in seen:
                seen.add(c); ordered.append(c)
        return ordered

    tried = []
    for i in range(max(1, int(frame_count))):
        frame = None
        for u in _urls_to_try(camera_url):
            # Try each candidate URL with small retries and longer timeout
            for attempt in range(3):
                tried.append(u)
                frame = fetch_frame(u, timeout=4.0)
                if frame is not None:
                    break
                time.sleep(0.2)
            if frame is not None:
                break
        if frame is None:
            return JsonResponse({
                'ok': False,
                'status': 'ERROR',
                'error': 'camera_off',
                'message': 'Camera snapshot unavailable',
                'tried': tried[-8:],
            }, status=503)

        count = detect_face_count(frame)
        if count > 0:
            saw_face += 1
        if count > 1:
            multiple_faces_detected = True
            break

        if count == 1:
            if compare_encoding_to_image(profile.encoding, frame):
                matches += 1

        if i < frame_count - 1 and delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    if multiple_faces_detected:
        AccessLog.objects.create(user=request.user, door=door, status='DENIED', note='Multiple faces detected')
        return JsonResponse({'ok': False, 'status': 'DENIED', 'error': 'multiple_faces_detected', 'message': 'Multiple faces in frame. Please ensure only one person is in view.'}, status=400)

    match_confirmed = matches >= max(1, int(required_matches))

    if match_confirmed and allowed:
        send_command(door.id, 'OPEN')
        AccessLog.objects.create(user=request.user, door=door, status='OPEN')
        # Schedule motor stop in background to avoid blocking the response
        try:
            duration = float(getattr(settings, 'MOTOR_ON_DURATION_SEC', 2))
        except Exception:
            duration = 2

        def _stop_motor_later(door_id: int, delay: float):
            if delay and delay > 0:
                time.sleep(delay)
            try:
                send_command(door_id, 'CLOSE')
            except Exception:
                pass

        threading.Thread(target=_stop_motor_later, args=(door.id, duration), daemon=True).start()

        return JsonResponse({
            'ok': True,
            'status': 'OPEN',
            'recognized_name': request.user.username,
            'message': f"Welcome, {request.user.username}"
        })

    if match_confirmed and not allowed:
        AccessLog.objects.create(user=request.user, door=door, status='DENIED', note='No access')
        return JsonResponse({'ok': False, 'status': 'DENIED', 'error': 'no_access_to_door', 'message': 'No access to this door'}, status=403)

    if saw_face == 0:
        AccessLog.objects.create(user=request.user, door=door, status='DENIED', note='No face detected')
        return JsonResponse({'ok': False, 'status': 'DENIED', 'error': 'no_face_detected', 'message': 'No face detected. Please align face with the camera.'}, status=400)

    AccessLog.objects.create(user=request.user, door=door, status='DENIED', note='Face not recognized')
    return JsonResponse({'ok': False, 'status': 'DENIED', 'error': 'face_not_recognized', 'message': 'Face not recognized'}, status=401)


@csrf_exempt
@require_http_methods(["POST"]) 
def api_verify_open_device(request):
    """
    ESP32-CAM posts a JPEG in request.body.
    Enforced user-binding: require ?username=<account> and only match that user's profile.
    Returns: {"verified": true/false}
    """
    try:
        username = (request.GET.get('username') or '').strip()
        # Record ESP32 IP for later pull-based verification defaults
        src_ip = request.META.get('REMOTE_ADDR')
        if src_ip:
            cache.set('esp32_ip', src_ip, timeout=24*60*60)  # 24h

        data = request.body
        if not data:
            return JsonResponse({'verified': False, 'error': 'empty_body'}, status=400)

        nparr = np.frombuffer(data, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return JsonResponse({'verified': False, 'error': 'invalid_image'}, status=400)

        # Multi-frame confirmation thresholds (device flow)
        mf_count = getattr(settings, 'FACE_MULTI_FRAME_COUNT', 3)
        mf_required = getattr(settings, 'FACE_MULTI_FRAME_REQUIRED', 2)

        matched_user = None

        if username:
            # Enforce user-bound when username is provided
            user = User.objects.filter(username__iexact=username).first()
            if not user:
                return JsonResponse({'verified': False, 'error': 'user_not_found'}, status=404)

            profile = FaceProfile.objects.filter(user=user).first()
            if not profile or not profile.encoding:
                return JsonResponse({'verified': False, 'error': 'not_enrolled'}, status=403)

            try:
                if compare_encoding_to_image(profile.encoding, frame):
                    matched_user = user
            except Exception:
                pass
        else:
            # Backward-compatible: match against any enrolled profile
            profiles = FaceProfile.objects.select_related('user').all()
            for p in profiles:
                if p.encoding:
                    try:
                        if compare_encoding_to_image(p.encoding, frame):
                            matched_user = p.user
                            break
                    except Exception:
                        continue

        # Multi-frame confirmation voting using cache
        key = f"verify_hist:{(username or request.META.get('REMOTE_ADDR') or 'anon').lower()}"
        hist = cache.get(key, [])
        current = bool(matched_user)
        hist.append(1 if current else 0)
        if len(hist) > mf_count:
            hist = hist[-mf_count:]
        cache.set(key, hist, timeout=60)  # keep short history

        votes_true = sum(hist)
        decision = votes_true >= mf_required and current

        if decision and matched_user:
            AccessLog.objects.create(
                user=matched_user,
                door=Door.objects.first() if Door.objects.exists() else None,
                status='OPEN',
                note='ESP32 push verified (multi-frame)'
            )
            return JsonResponse({'verified': True, 'user': matched_user.username, 'votes': {'true': votes_true, 'total': len(hist)}})

        return JsonResponse({'verified': False, 'votes': {'true': votes_true, 'total': len(hist)}})
    except Exception as e:
        return JsonResponse({'verified': False, 'error': str(e)}, status=500)


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
    door_id_str = (request.POST.get('door_id') or '').strip()
    command = (request.POST.get('command') or '').strip().upper()
    if not door_id_str.isdigit():
        return JsonResponse({'error': 'door_id required'}, status=400)
    if command not in ("OPEN", "CLOSE"):
        return JsonResponse({'error': 'invalid command'}, status=400)
    door = get_object_or_404(Door, id=int(door_id_str))
    send_command(door.id, command)
    AccessLog.objects.create(user=request.user, door=door, status=command)
    return JsonResponse({'ok': True, 'status': command})


 


@login_required
@require_http_methods(["GET"])
def api_camera_diag(request):
    """Quick diagnostic: try to fetch a snapshot and report details."""
    provided = (request.GET.get('url') or '').strip()
    source = 'provided' if provided else 'cached_or_default'

    camera_url = provided
    if not camera_url:
        last_ip = cache.get('esp32_ip')
        if last_ip:
            camera_url = f"http://{last_ip}/jpg"
        else:
            camera_url = ESP32_URL

    def _urls_to_try(u: str):
        u = (u or '').strip()
        cands = []
        if not u:
            return cands
        lower = u.lower()
        if '/stream' in lower:
            cands.append(lower.replace('/stream', '/jpg'))
        cands.append(u)
        base = u.rsplit('?', 1)[0]
        if not base.lower().endswith(('/jpg', '/jpeg', '/capture', '/photo', '/snapshot')):
            for alt in ('/jpg', '/capture', '/photo', '/snapshot'):
                cands.append(base.rstrip('/') + alt)
        seen = set(); out = []
        for c in cands:
            if c not in seen:
                seen.add(c); out.append(c)
        return out

    tried = []
    for u in _urls_to_try(camera_url):
        tried.append(u)
        frame = fetch_frame(u, timeout=4.0)
        if frame is not None:
            # Return a base64 data URL so the browser does not contact the device directly
            ok, buf = cv2.imencode('.jpg', frame)
            data_url = None
            if ok:
                b64 = base64.b64encode(buf.tobytes()).decode('ascii')
                data_url = f"data:image/jpeg;base64,{b64}"
            return JsonResponse({'ok': True, 'used': u, 'tried': tried[-5:], 'source': source, 'data_url': data_url})

    return JsonResponse({'ok': False, 'error': 'camera_off', 'tried': tried[-5:], 'source': source}, status=503)
