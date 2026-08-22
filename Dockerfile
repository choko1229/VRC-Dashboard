FROM python:3.13-slim

WORKDIR /app

# cryptography等、プラットフォームによってはソースビルドが必要な依存関係のためのビルドツール
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/data

# Pterodactyl等では起動時にPORTが動的に割り当てられることが多いため、環境変数から読む。
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
