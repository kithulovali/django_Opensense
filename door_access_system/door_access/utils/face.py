import io
import pickle
from typing import Optional

import numpy as np
from PIL import Image
import face_recognition
import cv2
from django.conf import settings


def encode_image_file(file_obj) -> Optional[bytes]:
    try:
        image = face_recognition.load_image_file(file_obj)
        encodings = face_recognition.face_encodings(image)
        if not encodings:
            return None
        encoding = encodings[0]
        return pickle.dumps(encoding)
    except Exception:
        return None


def compare_encoding_to_image(known_encoding_bytes: bytes, image_bgr, tolerance: float = 0.45) -> bool:
    known = pickle.loads(known_encoding_bytes)
    # Resolve configurable parameters with safe defaults
    tol = getattr(settings, 'FACE_MATCH_TOLERANCE', tolerance)
    require_single = getattr(settings, 'FACE_REQUIRE_SINGLE_FACE', True)
    detector_model = getattr(settings, 'FACE_DETECTOR_MODEL', 'hog')  # 'hog' or 'cnn'

    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return False
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)

    # Detect face locations first for more stable encodings and optional single-face enforcement
    try:
        locations = face_recognition.face_locations(rgb, model=detector_model)
    except Exception:
        locations = []

    if not locations:
        return False
    if require_single and len(locations) != 1:
        return False

    try:
        encs = face_recognition.face_encodings(rgb, known_face_locations=locations)
    except Exception:
        return False
    if not encs:
        return False

    for enc in encs:
        d = face_recognition.face_distance([known], enc)
        if len(d) and float(d[0]) <= tol:
            return True
    return False


def detect_face_count(image_bgr) -> int:
    detector_model = getattr(settings, 'FACE_DETECTOR_MODEL', 'hog')
    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return 0
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    try:
        locations = face_recognition.face_locations(rgb, model=detector_model)
    except Exception:
        locations = []
    return len(locations)
