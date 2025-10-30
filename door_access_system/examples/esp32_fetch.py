import os
import requests

ESP32_URL = os.environ.get('ESP32_URL', 'http://192.168.110.59/capture')

if __name__ == "__main__":
    r = requests.get(ESP32_URL, timeout=5)
    r.raise_for_status()
    with open('frame.jpg', 'wb') as f:
        f.write(r.content)
    print('Saved frame.jpg from', ESP32_URL)
