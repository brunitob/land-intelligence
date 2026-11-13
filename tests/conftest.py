from __future__ import annotations

import os
from typing import Any

import pytest

# Base de datos de test separada (se crea y migra automáticamente si Postgres está disponible).
_BASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://patagonia:patagonia@localhost:5432/patagonia_land")
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", _BASE_URL.rsplit("/", 1)[0] + "/patagonia_land_test")
os.environ["DATABASE_URL"] = TEST_DB_URL


def _prepare_test_db() -> None:
    try:
        from sqlalchemy import create_engine, text

        admin = create_engine(_BASE_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = 'patagonia_land_test'")).scalar():
                c.execute(text("CREATE DATABASE patagonia_land_test"))
        admin.dispose()
        from alembic import command
        from alembic.config import Config

        from patagonia_land.config import ROOT_DIR

        command.upgrade(Config(str(ROOT_DIR / "alembic.ini")), "head")
    except Exception as exc:  # sin Postgres: los tests de DB se saltean
        print(f"[tests] DB de test no disponible: {exc}")


_prepare_test_db()

from patagonia_land.config import Settings
from patagonia_land.crawling.fetcher import Fetcher
from tests.fixtures.sites import make_transport


def test_settings(**kw: Any) -> Settings:
    return Settings(request_delay_seconds=0, respect_robots=True, llm_enabled=False, **kw)


@pytest.fixture
def site_state() -> dict[str, Any]:
    return {}


@pytest.fixture
def fetcher_factory(site_state):
    def factory() -> Fetcher:
        return Fetcher(settings=test_settings(), allow_private=True, transport=make_transport(site_state))
    return factory


def db_available() -> bool:
    try:
        from sqlalchemy import text

        from patagonia_land.db.session import get_engine

        with get_engine().connect() as c:
            c.execute(text("SELECT 1 FROM sources LIMIT 1"))
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(os.environ.get("SKIP_DB") == "1" or not db_available(),
                                 reason="PostgreSQL/PostGIS no disponible")
