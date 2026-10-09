"""Django settings for the Weather-Aware Truck Routing backend.

All deploy-specific values come from environment variables so the same image
runs locally, in CI and on the hosting provider.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key")
DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Hosting providers terminate TLS (and redirect http→https) at their proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))
SILENCED_SYSTEM_CHECKS = [
    # Stateless JSON API: no cookies or sessions, so there is nothing for CSRF to protect.
    "security.W003",
    # HTTPS redirect is done by the hosting proxy; redirecting here would break its HTTP health checks.
    "security.W008",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The app is stateless: no models, no database.
DATABASES: dict = {}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "truck-routing",
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# --- Static files / built React app -------------------------------------------
STATIC_URL = "/static/"
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))
if FRONTEND_DIST.is_dir():
    # WhiteNoise serves the Vite build (index.html + /assets/*) from the site root.
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = True

# --- API ----------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "geocode": "120/min",
        "plan": "20/min",
        "heatmap": "20/min",
    },
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

# --- Third-party providers ------------------------------------------------------
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io").rstrip("/")
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")
# Free tier allows 600 locations/minute; stay below it. Raise this with a paid key.
OPEN_METEO_LOCATIONS_PER_MINUTE = int(os.environ.get("OPEN_METEO_LOCATIONS_PER_MINUTE", "500"))
HTTP_USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT", "weather-aware-truck-routing/1.0 (assessment project)"
)
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "25"))

# Car-profile routing engines assume car speeds; trucks are capped at this speed
# when computing ETAs (see planner/services/planner.py).
TRUCK_MAX_SPEED_MPH = float(os.environ.get("TRUCK_MAX_SPEED_MPH", "65"))
WEATHER_CACHE_SECONDS = int(os.environ.get("WEATHER_CACHE_SECONDS", "900"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
