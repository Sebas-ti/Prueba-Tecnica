from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # las rutas por defecto (data/...) son relativas a la raíz del repo

from app.config import Settings  # noqa: E402
from app.container import Container  # noqa: E402
from app.main import create_app  # noqa: E402


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="test",
        llm_provider="local",
        vector_store_provider="local",
        history_provider="sqlite",
        index_dir=str(tmp_path / "index"),
        sqlite_path=str(tmp_path / "history.db"),
        data_dir=str(ROOT / "data"),
        requests_db_path=str(ROOT / "data" / "solicitudes.json"),
        cloud_catalog_path=str(ROOT / "data" / "cloud_services.json"),
        log_level="WARNING",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(scope="session")
def indexed_container(tmp_path_factory) -> Container:
    tmp = tmp_path_factory.mktemp("kb")
    container = Container.build(make_settings(tmp))
    container.kb.ingest_directory(str(ROOT / "data" / "docs"))
    return container


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture()
def client(tmp_path) -> TestClient:
    s = make_settings(tmp_path)
    container = Container.build(s)
    container.kb.ingest_directory(str(ROOT / "data" / "docs"))
    with TestClient(create_app(s, container)) as c:
        yield c
