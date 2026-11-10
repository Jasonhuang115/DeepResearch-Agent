from research_engine.trace import NullTracer


def build_tracer() -> NullTracer:
    return NullTracer()


def make_tracer(api_key: str = "") -> NullTracer:
    _ = api_key
    return NullTracer()
