# door_access_system

Face-recognition door opener using Django 4, PostgreSQL, Channels (WebSocket), MQTT, and ESP32-CAM.

## Setup

1. Create and activate a virtualenv, then install deps:

```
pip install -r requirements.txt
```

2. Configure environment variables (example):

- `DJANGO_SECRET_KEY=change-me`
- `DJANGO_DEBUG=1`
- `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1`
- `POSTGRES_DB=door_access_db`
- `POSTGRES_USER=door_user`
- `POSTGRES_PASSWORD=door_password`
- `POSTGRES_HOST=localhost`
- `POSTGRES_PORT=5432`
- `MQTT_HOST=localhost`
- `MQTT_PORT=1883`
- `MQTT_TOPIC=door/control`
- `ESP32_URL=http://192.168.110.59/capture`

3. Initialize DB:

```
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

4. Run dev server (ASGI):

```
daphne -b 0.0.0.0 -p 8000 door_access_system.asgi:application
```
Or standard runserver (Channels supports it too):
```
python manage.py runserver
```

## Notes
- MEDIA files are stored under `media/`. Upload face images via the Enroll page.
- Admin dashboard at `/admin/dashboard/`.
- API:
  - POST `/api/enroll/` with `image` file
  - POST `/api/verify_open/` with `door_id`
- MQTT payload: `{ "door": <id>, "command": "OPEN" | "CLOSE" }`
- ESP32-CAM endpoint should return a single JPEG frame.
