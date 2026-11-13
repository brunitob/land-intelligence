FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[dashboard,dev]"

# Playwright es opcional (ENABLE_PLAYWRIGHT=true). Se instala con: docker compose build --build-arg WITH_PLAYWRIGHT=1
ARG WITH_PLAYWRIGHT=0
RUN if [ "$WITH_PLAYWRIGHT" = "1" ]; then pip install ".[browser]" && playwright install --with-deps chromium; fi

COPY . .

# Proceso sin privilegios
RUN useradd -m app && chown -R app /app
USER app

CMD ["uvicorn", "patagonia_land.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
