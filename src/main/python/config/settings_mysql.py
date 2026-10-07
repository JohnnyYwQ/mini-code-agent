"""Optional local MySQL settings; select with --settings=config.settings_mysql."""

import os

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .settings import *  # noqa: F403
from .settings import BASE_DIR

load_dotenv(BASE_DIR / ".env.mysql", override=False)


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"Set {name} in .env.mysql or the environment")
    return value


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": required_env("MYSQL_DATABASE"),
        "USER": required_env("MYSQL_USER"),
        "PASSWORD": required_env("MYSQL_PASSWORD"),
        "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT", "3307"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "isolation_level": "read committed",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
        },
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_0900_bin"},
    }
}
