import requests
import numpy as np
import cv2


def fetch_frame(url: str, timeout: float = 4.0):
    """Fetch a single JPEG frame from the given URL with cache-busting and a quick retry.
    Optimized for responsiveness over exhaustive retries.
    """
    # Ensure cache-busting to avoid intermediaries returning stale/empty content
    sep = '&' if '?' in url else '?'
    full_url = f"{url}{sep}t={int(__import__('time').time()*1000)}"
    for _ in range(3):  # quick retries
        try:
            resp = requests.get(full_url, timeout=timeout)
            resp.raise_for_status()
            arr = np.frombuffer(resp.content, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                return frame
        except Exception:
            pass
    return None
