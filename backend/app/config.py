import os
from dataclasses import dataclass

from sqlalchemy.engine import URL


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    owner_user: str
    owner_password: str
    app_user: str
    app_password: str
    recruiters_csv: str

    def _url(self, user: str, password: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def owner_url(self) -> URL:
        """Schema owner: runs migrations and seeding. Never used to serve requests."""
        return self._url(self.owner_user, self.owner_password)

    @property
    def app_url(self) -> URL:
        """Non-superuser role the API serves requests as; RLS applies to it."""
        return self._url(self.app_user, self.app_password)


def get_settings() -> Settings:
    env = os.environ
    return Settings(
        db_host=env.get("DB_HOST", "localhost"),
        db_port=int(env.get("DB_PORT", "5432")),
        db_name=env.get("TECHFORCE_DB", "techforce"),
        owner_user=env.get("DB_OWNER_USER", "techforce_owner"),
        owner_password=env.get("DB_OWNER_PASSWORD", "owner_pw"),
        app_user=env.get("DB_APP_USER", "techforce_app"),
        app_password=env.get("DB_APP_PASSWORD", "app_pw"),
        recruiters_csv=env.get("RECRUITERS_CSV", "/data/recruiters.csv"),
    )
