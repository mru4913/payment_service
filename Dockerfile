FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

# 依赖层（利用缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 应用代码
COPY backend/ backend/
COPY frontend/ frontend/
COPY alembic/ alembic/
COPY alembic.ini .

RUN adduser --disabled-password --no-create-home appuser
USER appuser

EXPOSE 8000

# 启动前自动执行数据库迁移
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
