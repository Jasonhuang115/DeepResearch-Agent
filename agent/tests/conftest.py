from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.config import settings


@pytest.fixture(autouse=True)
def _isolate_cloud_durable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oss_access_key_id", "")
    monkeypatch.setattr(settings, "oss_access_key_secret", "")
    monkeypatch.setattr(settings, "oss_bucket", "")
    monkeypatch.setattr(settings, "oss_endpoint", "")
    monkeypatch.setattr(settings, "durable_root", str(tmp_path / "durable"))
