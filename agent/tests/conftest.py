import pytest

from agent_service.workspace import reset_provider


@pytest.fixture(autouse=True)
def _reset_workspace_provider() -> None:
    reset_provider()
    yield
    reset_provider()
