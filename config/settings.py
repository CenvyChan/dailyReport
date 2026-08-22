import os
import sys
from pathlib import Path

from config.env import load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent

for _key, _value in load_env_file(BASE_DIR / ".env").items():
    os.environ.setdefault(_key, _value)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "replace-this-development-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]
# 通过 Docker 端口映射或反向代理访问时，POST 会被 CSRF 拦下来，除非把来源写进这里。
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "sales.apps.SalesConfig",
    "purchase.apps.PurchaseConfig",
    "reports.apps.ReportsConfig",
    "notifications.apps.NotificationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.PasswordChangeRequiredMiddleware",
    "core.middleware.ActiveCompanyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation_permissions",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "daily_report.sqlite3",
        "OPTIONS": {"timeout": 10},
    },
}

AUTH_PASSWORD_VALIDATORS = [
    # 内网系统，不做复杂度要求，但至少挡住 1 位或纯数字的密码。
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 会话安全。SECURE_SSL_REDIRECT / *_COOKIE_SECURE / HSTS 都要求 HTTPS，
# 而这套系统跑在内网 HTTP 上，开了会直接登不进去，所以留给日后上 HTTPS 时再开。
# 下面这几项与协议无关，现在就能生效。
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # 前端 fetch 要读 csrftoken
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", 60 * 60 * 12))
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}}

LOGIN_URL = "/accounts/login/"
# 直接落到业务页面，省掉根路径的一次重定向。
LOGIN_REDIRECT_URL = "/sales/shipments/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
BACKUP_DIRECTORY = Path(os.getenv("BACKUP_DIRECTORY", BASE_DIR / "backups"))

# 阿里云企业邮箱 SMTP：465 用 SSL，25/80 用明文，587 用 STARTTLS。
# 阿里云要求 EMAIL_HOST_USER 与 DEFAULT_FROM_EMAIL 是同一个已验证的发信地址。
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.qiye.aliyun.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "True").lower() == "true"
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "False").lower() == "true"
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "30"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "report@example.com")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 应用日志。此前没有任何 LOGGING 配置，异常栈不落盘，出问题只能看 stdout，
# 容器一重建就没了。按天轮转，保留 30 天。
# 跑测试时不写文件：否则会污染生产日志，异常栈还会刷屏盖掉测试结果。
RUNNING_TESTS = "test" in sys.argv
LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO").upper()

if RUNNING_TESTS:
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": True,
        "handlers": {"null": {"class": "logging.NullHandler"}},
        "root": {"handlers": ["null"], "level": "CRITICAL"},
    }
else:
    LOG_DIRECTORY = Path(os.getenv("LOG_DIRECTORY", BASE_DIR / "logs"))
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "{asctime} {levelname} {name} {message}",
                "style": "{",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": LOG_DIRECTORY / "app.log",
                "when": "midnight",
                "backupCount": 30,
                "encoding": "utf-8",
                "formatter": "standard",
            },
            # 定时邮件由计划任务触发，没人盯着终端，单独留一份便于排查昨晚发信。
            "mail_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": LOG_DIRECTORY / "mail.log",
                "when": "midnight",
                "backupCount": 30,
                "encoding": "utf-8",
                "formatter": "standard",
            },
        },
        "root": {"handlers": ["console", "file"], "level": LOG_LEVEL},
        "loggers": {
            # 500 的堆栈默认只发邮件，这里让它落盘。
            "django.request": {
                "handlers": ["console", "file"],
                "level": "ERROR",
                "propagate": False,
            },
            "notifications": {
                "handlers": ["console", "mail_file", "file"],
                "level": LOG_LEVEL,
                "propagate": False,
            },
        },
    }

# 上传的 Excel 超过 2MB 就落临时文件，不再整份堆在内存里。
# 请求体总量上限 12MB，比 core.uploads.MAX_UPLOAD_BYTES（10MB）略高：
# 超限的文件由应用层给出中文提示，而不是被 Django 直接 400 掉。
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
