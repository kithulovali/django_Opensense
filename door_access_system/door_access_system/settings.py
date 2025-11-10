import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-secret-key-change-me')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
# Comma-separated list in env var ALLOWED_HOSTS, or sensible defaults for local/LAN
ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS',
    '127.0.0.1,localhost,192.168.0.121'
).split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'door_access',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'door_access_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'door_access_system.wsgi.application'
ASGI_APPLICATION = 'door_access_system.asgi.application'

# Channels
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}

# Database (SQLite for now)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'user_dashboard'
LOGOUT_REDIRECT_URL = 'login'

# Face recognition settings
# Smaller tolerance is stricter. Typical good values: 0.35 - 0.45
FACE_MATCH_TOLERANCE = float(os.environ.get('FACE_MATCH_TOLERANCE', '0.9'))
# Enforce exactly one face in frame during verification
FACE_REQUIRE_SINGLE_FACE = os.environ.get('FACE_REQUIRE_SINGLE_FACE', '1') == '1'
# 'hog' works on CPU; 'cnn' requires dlib CNN model and more compute
FACE_DETECTOR_MODEL = os.environ.get('FACE_DETECTOR_MODEL', 'hog')
# Multi-frame confirmation: capture N frames and require K matches
FACE_MULTI_FRAME_COUNT = int(os.environ.get('FACE_MULTI_FRAME_COUNT', '3'))
FACE_MULTI_FRAME_REQUIRED = int(os.environ.get('FACE_MULTI_FRAME_REQUIRED', '1'))
# Delay between frames in milliseconds
FACE_MULTI_FRAME_DELAY_MS = int(os.environ.get('FACE_MULTI_FRAME_DELAY_MS', '150'))

MOTOR_ON_DURATION_SEC = float(os.environ.get('MOTOR_ON_DURATION_SEC', '2'))
