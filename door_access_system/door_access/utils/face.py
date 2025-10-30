import io
import pickle
from typing import Optional

import numpy as np
from PIL import Image
import face_recognition
import cv2


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


def compare_encoding_to_image(known_encoding_bytes: bytes, image_bgr) -> bool:
    known = pickle.loads(known_encoding_bytes)
    # Convert BGR (OpenCV) to RGB and ensure C-contiguous uint8 array for dlib
    try:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return False
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    try:
        encs = face_recognition.face_encodings(rgb)
    except Exception:
        return False
    if not encs:
        return False
    matches = face_recognition.compare_faces([known], encs[0])
    return bool(matches[0])
