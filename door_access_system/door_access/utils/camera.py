import requests
import numpy as np
import cv2


def fetch_frame(url: str, timeout: float = 5.0):
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        arr = np.frombuffer(resp.content, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame
    except Exception:
        return None
