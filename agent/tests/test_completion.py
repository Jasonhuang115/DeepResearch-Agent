from research_engine.completion import FinishKind, normalize_finish


def test_normalize_finish_maps_reasons() -> None:
    assert normalize_finish("stop", has_tool_calls=False, cancelled=False).kind == FinishKind.COMPLETED
    assert normalize_finish("stop", has_tool_calls=True, cancelled=False).kind == FinishKind.TOOL_CALLS
    assert normalize_finish("tool_calls", has_tool_calls=True, cancelled=False).kind == FinishKind.TOOL_CALLS
    assert normalize_finish("length", has_tool_calls=False, cancelled=False).kind == FinishKind.OUTPUT_LIMIT
    assert normalize_finish("content_filter", has_tool_calls=False, cancelled=False).kind == FinishKind.FILTERED
    assert normalize_finish("stop", has_tool_calls=False, cancelled=True).kind == FinishKind.CANCELLED
    assert normalize_finish("weird", has_tool_calls=False, cancelled=False).kind == FinishKind.UNKNOWN
