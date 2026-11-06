"""
Django settings for the QazaqRead project.

Secrets and deployment options come from environment variables:
    DJANGO_SECRET_KEY, DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS
    DATABASE_URL  PostgreSQL, e.g. postgresql://user:password@host:5432/qazaqread
                  (required; locally it is read from the .env file)

On Render (the RENDER variable is set there) DEBUG is off by default;
on your own computer it is on, so runserver serves static files and
login cookies work over plain http://127.0.0.1.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Local secrets (DATABASE_URL, DJANGO_SECRET_KEY) from .env; real environment variables win.
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _key, _sep, _value = _line.partition("=")
        if _sep and not _key.strip().startswith("#"):
            os.environ.setdefault(_key.strip(), _value.strip())

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me-in-production",
)

ON_RENDER = bool(os.environ.get("RENDER"))

DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_RENDER else "1") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", ".onrender.com,localhost,127.0.0.1").split(",")
    if h.strip()
]

# Render puts HTTPS in front of the app; forms posted from https://<name>.onrender.com must pass CSRF.
CSRF_TRUSTED_ORIGINS = ["https://*.onrender.com"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves static files when DEBUG is off
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured(
        "DATABASE_URL is not set. Put it in the .env file next to manage.py, e.g.\n"
        "DATABASE_URL=postgresql://user:password@host:5432/dbname"
    )

DATABASES = {"default": dj_database_url.config(conn_max_age=600, conn_health_checks=True)}

# `manage.py test` builds a throwaway database; Render's PostgreSQL user may not create
# databases, so tests run on in-memory SQLite. Real data lives only in PostgreSQL.
if "test" in sys.argv[1:2]:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}


# Authentication

AUTH_USER_MODEL = "core.User"

AUTHENTICATION_BACKENDS = [
    "core.backends.EmailOrUsernameBackend",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization

LANGUAGE_CODE = "kk"

# The site exists only in Kazakh, whatever language the browser asks for.
LANGUAGES = [("kk", "Қазақша")]

# Kazakh for Django's own messages that its bundled translation leaves in English.
LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = "Asia/Almaty"

USE_I18N = True

USE_TZ = True


# Static and uploaded files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed, cache-busted files on Render (needs `collectstatic`, run by build.sh).
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if ON_RENDER
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Audio uploads from the reading page (bytes)
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024


# Email

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# Production hardening (active when DEBUG is off)

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
