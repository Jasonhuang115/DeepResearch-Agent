from __future__ import annotations

import pytest

from agent_service.config import settings


@pytest.fixture(autouse=True)
def _isolate_cloud_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oss_access_key_id", "")
    monkeypatch.setattr(settings, "oss_access_key_secret", "")
    monkeypatch.setattr(settings, "oss_bucket", "")
    monkeypatch.setattr(settings, "oss_endpoint", "")
