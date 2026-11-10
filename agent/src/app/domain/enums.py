from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_RUN_STATUSES = (
    RunStatus.QUEUED,
    RunStatus.RUNNING,
    RunStatus.CANCELLING,
)
TERMINAL_RUN_STATUSES = (
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
)


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
