"""Offline tests own their configuration, never the developer's .env/secrets.

Explicit integration opt-ins (e.g. AUTH_POSTGRES_TEST_URL) are not settings
aliases and remain available to the integration fixtures.
"""

import os

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from pydantic_settings import BaseSettings  # noqa: E402
from backend.core import settings as settings_module  # noqa: E402

for settings_type in vars(settings_module).values():
    if isinstance(settings_type, type) and issubclass(settings_type, BaseSettings):
        for field in settings_type.model_fields.values():
            if isinstance(field.validation_alias, str):
                os.environ.pop(field.validation_alias, None)

os.environ.update(
    APP_ENV="test",
    JWT_SECRET_KEY="offline-tests-only-not-a-production-signing-key",
    DATABASE_URL="sqlite+pysqlite:///:memory:",
)
