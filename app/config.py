"""Settings come from environment variables, so the same image runs anywhere."""

import os


class Settings:
    def __init__(self) -> None:
        # When DATABASE_URL is set, data is stored in PostgreSQL.
        # When it is empty, an in-memory store is used (data is lost on restart).
        self.database_url = os.getenv("DATABASE_URL", "")
        self.app_version = os.getenv("APP_VERSION", "dev")
        self.environment = os.getenv("APP_ENV", "local")
        # Secret key that unlocks the admin API. If it is not set, the admin API is switched off.
        # Never put the real value in code or Git: pass it in as an environment variable / Secret.
        self.admin_api_key = os.getenv("ADMIN_API_KEY", "")


settings = Settings()
