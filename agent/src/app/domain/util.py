from __future__ import annotations

from datetime import UTC, datetime

import ulid


def new_id() -> str:
    return str(ulid.new())


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
