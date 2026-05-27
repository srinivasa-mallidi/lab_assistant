"""
Lab Assistant - Django Settings
Production-ready configuration for Laboratory AI Chatbot
"""

import os
from pathlib import Path
from datetime import timedelta

# ─── Load .env file automatically ─────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()  # Loads .env from current working directory or project root

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── ChromaDB / SQLite3 compatibility fix for Windows ─────────────────────────
# ChromaDB requires SQLite >= 3.35. On older Windows Python builds the bundled
# SQLite may be too old. This swap uses pysqlite3-binary if available.
try:
    __import__('pysqlite3')
    import sys
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass  # pysqlite3 not installed - use system sqlite3 (fine on Python 3.11+)

# ─── Security ────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-in-production-abc123xyz")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ─── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "channels",
    # Internal apps
    "apps.chat",
    "apps.documents",
    "apps.agents",
    "apps.database",
    "apps.security",
    "apps.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.security.middleware.AuditLogMiddleware",
    "apps.security.middleware.PromptInjectionMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ─── Templates ────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "lab_assistant.sqlite3",   # sits directly in project root — no subdirectory needed
    }
}

# SampleManager LIMS Database (read-only)
LIMS_DATABASE = {
    "ENGINE": os.environ.get("LIMS_DB_ENGINE", "mssql"),   # mssql | oracle | postgresql
    "HOST": os.environ.get("LIMS_DB_HOST", "localhost"),
    "PORT": os.environ.get("LIMS_DB_PORT", "1433"),
    "NAME": os.environ.get("LIMS_DB_NAME", "SAMPLEMANAGER"),
    "USER": os.environ.get("LIMS_DB_USER", "lims_readonly"),
    "PASSWORD": os.environ.get("LIMS_DB_PASSWORD", ""),
    "OPTIONS": {"readonly": True},
}

# ─── Authentication ───────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "100/hour",
        "chat": "30/minute",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
}

# ─── AI / LLM Configuration ──────────────────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))

SUPPORTED_MODELS = {
    "llama3":      {"name": "llama3:latest",     "context_window": 8192},
    "mistral":     {"name": "mistral:latest",    "context_window": 8192},
    "qwen":        {"name": "qwen2:latest",      "context_window": 32768},
    "deepseek":    {"name": "deepseek-r1:latest","context_window": 65536},
    # ── Small models for low-RAM machines (< 4GB free) ──
    "qwen2:0.5b":  {"name": "qwen2:0.5b",        "context_window": 32768},
    "tinyllama":   {"name": "tinyllama:latest",   "context_window": 2048},
    "phi3:mini":   {"name": "phi3:mini",          "context_window": 4096},
}

# ─── Vector Store / RAG ───────────────────────────────────────────────────────
VECTOR_STORE_TYPE = os.environ.get("VECTOR_STORE_TYPE", "chroma")   # chroma | faiss
CHROMA_PERSIST_DIR = BASE_DIR / "data" / "chroma_db"
FAISS_INDEX_DIR = BASE_DIR / "data" / "faiss_index"

EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2"
)

RAG_CONFIG = {
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "top_k_results": 5,
    "similarity_threshold": 0.3,
    "max_context_tokens": 3000,
}

# ─── Document Ingestion ───────────────────────────────────────────────────────
MEDIA_ROOT = BASE_DIR / "data" / "uploads"
MEDIA_URL = "/media/"
ALLOWED_DOCUMENT_TYPES = [".pdf", ".docx", ".pptx", ".txt", ".md"]
MAX_DOCUMENT_SIZE_MB = 50

# ─── Static Files ─────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "static"]

# ─── Cache (Redis for prod, LocMemCache for dev) ──────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "lab-assistant-cache",
    }
}

# ─── Channels (WebSocket for streaming) ──────────────────────────────────────
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# ─── Logging ──────────────────────────────────────────────────────────────────
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "audit": {
            "format": "{asctime} AUDIT {levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "app.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "audit_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "audit.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "audit",
        },
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "security.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["console", "app_file"], "level": "INFO"},
        "lab_assistant": {"handlers": ["console", "app_file"], "level": "DEBUG", "propagate": False},
        "audit": {"handlers": ["audit_file"], "level": "INFO", "propagate": False},
        "security": {"handlers": ["security_file", "console"], "level": "WARNING", "propagate": False},
    },
}

# ─── Security Headers ─────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
).split(",")

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# ─── Session ──────────────────────────────────────────────────────────────────
SESSION_COOKIE_AGE = 28800         # 8 hours
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ─── Role-Based Access ────────────────────────────────────────────────────────
USER_ROLES = {
    "LAB_ANALYST":    {"can_query_db": True,  "can_upload_docs": False, "can_admin": False},
    "LAB_SUPERVISOR": {"can_query_db": True,  "can_upload_docs": True,  "can_admin": False},
    "LIMS_ADMIN":     {"can_query_db": True,  "can_upload_docs": True,  "can_admin": True},
    "READ_ONLY":      {"can_query_db": False, "can_upload_docs": False, "can_admin": False},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True