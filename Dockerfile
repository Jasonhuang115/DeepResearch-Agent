FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-dev
COPY agent/alembic.ini ./alembic.ini
COPY agent/alembic ./alembic
COPY agent/src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src

CMD ["uvicorn", "app.main_api:app", "--host", "0.0.0.0", "--port", "8000"]
