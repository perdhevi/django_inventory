import os
from django.core.exceptions import ImproperlyConfigured

from .settings import *

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
if len(SECRET_KEY) < 50 or SECRET_KEY == "local-learning-only-do-not-deploy":
    raise ImproperlyConfigured("Set a strong production DJANGO_SECRET_KEY.")
DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in os.environ["DJANGO_ALLOWED_HOSTS"].split(",") if host.strip()]
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Explicit production hosts are required.")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"].split(",")]
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# This first release intentionally applies HSTS only to this host, without preload.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
# Only trust this header behind a proxy that overwrites client-supplied forwarding headers.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
STATIC_ROOT = BASE_DIR / "staticfiles"
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                  "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Django 6.1 forbids combining MAILERS with deprecated EMAIL_* settings.
from django import VERSION as django_version

_smtp = {
    "host": os.environ.get("SMTP_HOST", "localhost"),
    "port": int(os.environ.get("SMTP_PORT", "587")),
    "username": os.environ.get("SMTP_USER", ""),
    "password": os.environ.get("SMTP_PASSWORD", ""),
    "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
    "timeout": 10,
}
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "inventory@localhost")
if django_version >= (6, 1):
    for _name in ("EMAIL_BACKEND", "EMAIL_FILE_PATH", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER",
                  "EMAIL_HOST_PASSWORD", "EMAIL_USE_TLS", "EMAIL_USE_SSL", "EMAIL_TIMEOUT",
                  "EMAIL_SSL_CERTFILE", "EMAIL_SSL_KEYFILE"):
        globals().pop(_name, None)
    MAILERS = {
        "default": {"BACKEND": "django.core.mail.backends.smtp.EmailBackend", "OPTIONS": _smtp}
    }
else:
    globals().pop("MAILERS", None)
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST, EMAIL_PORT = _smtp["host"], _smtp["port"]
    EMAIL_HOST_USER, EMAIL_HOST_PASSWORD = _smtp["username"], _smtp["password"]
    EMAIL_USE_TLS, EMAIL_TIMEOUT = _smtp["use_tls"], _smtp["timeout"]
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}