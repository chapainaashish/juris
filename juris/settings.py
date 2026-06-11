import os
from datetime import timedelta
from pathlib import Path

from decouple import config

# BASE CONFIGURATION
BASE_DIR = Path(__file__).resolve().parent.parent
SITE_NAME = config("SITE_NAME")

# SECURITY SETTINGS
SECRET_KEY = config("DJANGO_SECRET_KEY")
JWT_SIGNING_KEY = config("JWT_SIGNING_KEY", default=None)
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS", default="*", cast=lambda v: [s.strip() for s in v.split(",")]
)

# APPLICATION DEFINITION
INSTALLED_APPS = [
    # Django apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "channels",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "social_django",
    "corsheaders",
    "drf_yasg",
    "cloudinary",
    "cloudinary_storage",
    # Local apps
    "users",
    "profiles",
    "subscriptions",
    "lawyer",
    "lawyer_availability",
    "kyc",
    "lawyer_appointment",
    "lawyer_wallet",
]

# MIDDLEWARE CONFIGURATION
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# URL CONFIGURATION
ROOT_URLCONF = "juris.urls"

# TEMPLATES CONFIGURATION
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
            ],
        },
    },
]

# ASGI/WSGI CONFIGURATION
ASGI_APPLICATION = "juris.asgi.application"
WSGI_APPLICATION = "juris.wsgi.application"

# DATABASE CONFIGURATION
if DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("POSTGRES_DB"),
            "USER": config("POSTGRES_USER"),
            "PASSWORD": config("POSTGRES_PASSWORD"),
            "HOST": config("POSTGRES_HOST"),
            "PORT": config("POSTGRES_PORT"),
            "CONN_MAX_AGE": 600,
        }
    }

# AUTHENTICATION CONFIGURATION
AUTH_USER_MODEL = "users.User"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {
            "user_attributes": ["username", "email", "first_name", "last_name"],
            "max_similarity": 0.7,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": config("MIN_PASSWORD_LENGTH", default=10, cast=int),
        },
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = (
    "social_core.backends.google.GoogleOAuth2",
    "django.contrib.auth.backends.ModelBackend",
)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# SECURITY ENHANCEMENTS
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# SESSION CONFIGURATION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = config("SESSION_COOKIE_AGE", default=43200, cast=int)
AUTH_COOKIE = "refresh_token"
AUTH_COOKIE_SECURE = not DEBUG
AUTH_COOKIE_HTTP_ONLY = True
AUTH_COOKIE_SAMESITE = "Lax"
AUTH_COOKIE_PATH = "/"
AUTH_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days

# REST FRAMEWORK CONFIGURATION
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("ANON_THROTTLE_RATE", default="20/minute", cast=str),
        "user": config("USER_THROTTLE_RATE", default="60/minute", cast=str),
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": config("DRF_PAGE_SIZE", default=20, cast=int),
}

# JWT CONFIGURATION
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("ACCESS_TOKEN_LIFETIME_MINUTES", default=600, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("REFRESH_TOKEN_LIFETIME_DAYS", default=1, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
}
SIMPLE_JWT_BLACKLIST_APP = "rest_framework_simplejwt.token_blacklist"


# LOGIN SECURITY SETTINGS
MAX_LOGIN_ATTEMPTS = config("MAX_LOGIN_ATTEMPTS", default=5, cast=int)
LOGIN_LOCKOUT_TIME_MINUTES = config("LOGIN_LOCKOUT_TIME_MINUTES", default=30, cast=int)
FRONTEND_URL = config("FRONTEND_URL")

# OTP CONFIGURATION
MAX_OTP_ATTEMPTS = config("MAX_OTP_ATTEMPTS", default=5, cast=int)
OTP_LOCKOUT_TIME_MINUTES = config("OTP_LOCKOUT_TIME_MINUTES", default=30, cast=int)
RESEND_COOLDOWN_SECONDS = config("RESEND_COOLDOWN_SECONDS", default=60, cast=int)
OTP_VALIDITY_MINUTES = config("OTP_VALIDITY_MINUTES", default=5, cast=int)
OTP_CODE_LENGTH = config("OTP_CODE_LENGTH", default=6, cast=int)

# Appointment Configuration
APPOINTMENT_EXPIRATION_MINUTES = config(
    "APPOINTMENT_EXPIRATION_MINUTES", default=10, cast=int
)

# REDIS CONFIGURATION
REDIS_HOST = config("REDIS_HOST", default="redis")
REDIS_PORT = config("REDIS_PORT", default=6379, cast=int)
REDIS_DB = config("REDIS_DB", default=0, cast=int)
REDIS_PASSWORD = config("REDIS_PASSWORD", default=None)


# Channel Configuration
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.pubsub.RedisPubSubChannelLayer",
        "CONFIG": {
            "hosts": [
                (
                    f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
                    if not REDIS_PASSWORD
                    else f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0"
                )
            ],
            "capacity": 1000,
            "expiry": 10,
            "group_expiry": 86400,
            "prefix": "juris_ws",
        },
    },
}

# CACHE CONFIGURATION
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": REDIS_PASSWORD,
            "PARSER_CLASS": "redis.connection._HiredisParser",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
        },
        "KEY_PREFIX": "juris",
    }
}

# Use Redis for session storage
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"


# EMAIL CONFIGURATION
if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = config("EMAIL_HOST")
EMAIL_PORT = config("EMAIL_PORT", cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD")
EMAIL_VERIFICATION_VALID_UNTIL_HOURS = config(
    "EMAIL_VERIFICATION_VALID_UNTIL_HOURS", cast=int
)
EMAIL_VERIFICATION_SUCCESS_URL = config("EMAIL_VERIFICATION_SUCCESS_URL")
EMAIL_VERIFICATION_FAILURE_URL = config("EMAIL_VERIFICATION_FAILURE_URL")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL")
PASSWORD_RESET_TIMEOUT = config("PASSWORD_RESET_TIMEOUT", default=86400, cast=int)

# SOCIAL AUTH CONFIGURATION
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = config("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = config("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET")
SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE = ["email", "profile"]
SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",
    "social_core.pipeline.social_auth.associate_by_email",
    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
)

# TWILIO CONFIGURATION
TWILIO_ACCOUNT_SID = config("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = config("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = config("TWILIO_PHONE_NUMBER")

# Stripe
STRIPE_PUBLISHABLE_KEY = config("STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = config("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = config("STRIPE_WEBHOOK_SECRET")
STRIPE_CURRENCY = config("STRIPE_CURRENCY", cast=str)
TRIAL_PERIOD_DAYS = config("TRIAL_PERIOD_DAYS", cast=int)
NOTIFY_BEFORE_DAYS = config("NOTIFY_BEFORE_DAYS", cast=int)
REFUND_COMMISSION_PERCENTAGE = config("REFUND_COMMISSION_PERCENTAGE", cast=int)


# Agora
AGORA_APP_ID = config("AGORA_APP_ID")
AGORA_APP_CERTIFICATE = config("AGORA_APP_CERTIFICATE")


# INTERNATIONALIZATION
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# STATIC FILES CONFIGURATION
STATIC_URL = "static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]

# MEDIA FILES CONFIGURATION
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
FILE_UPLOAD_PERMISSIONS = 0o644
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880

# CELERY CONFIGURATION
CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_RESULT_BACKEND = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE


# Configure Cloudinary to serve media files
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": config("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": config("CLOUDINARY_API_KEY"),
    "API_SECRET": config("CLOUDINARY_API_SECRET"),
    "MEDIA_TAG": "media",
    "STATIC_TAG": "static",
    "STATIC_IMAGES_EXTENSIONS": [
        "jpg",
        "jpe",
        "jpeg",
        "jpc",
        "jp2",
        "j2k",
        "wdp",
        "jxr",
        "hdp",
        "png",
        "gif",
        "webp",
        "bmp",
        "tif",
        "tiff",
        "ico",
    ],
    "SECURE": True,  # Use HTTPS URLs
    "INVALID_VIDEO_ERROR_MESSAGE": "Please upload a valid video file.",
    "EXCLUDE_DELETE_ORPHANED_MEDIA_PATHS": [],
}


# Use Cloudinary for media files (user uploads)
DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

# Optional: Configure upload presets for different types of content
CLOUDINARY_UPLOAD_PRESET = (
    "vendor_avatars"  # Create this preset in Cloudinary dashboard
)

# Cloudinary Media URL (this will override the default MEDIA_URL when using Cloudinary)
CLOUDINARY_URL = f"cloudinary://{CLOUDINARY_STORAGE['API_KEY']}:{CLOUDINARY_STORAGE['API_SECRET']}@{CLOUDINARY_STORAGE['CLOUD_NAME']}"


# CORS CONFIGURATION
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOW_CREDENTIALS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    CORS_ALLOW_CREDENTIALS = True
