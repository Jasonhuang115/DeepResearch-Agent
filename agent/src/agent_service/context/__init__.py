"""Context window / memory. Filled in later; v1 is a pass-through."""


def pack_messages(messages: list[dict]) -> list[dict]:
    return list(messages)


def prepare_messages(messages: list[dict]) -> list[dict]:
    """Hook for later compression. Must keep tool-call / tool-result pairs intact."""
    return list(messages)
