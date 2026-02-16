# Stage 1: Export dependencies
FROM python:3.13-slim AS deps

WORKDIR /app

# Install Poetry and export plugin
ENV POETRY_VERSION=2.1.4
RUN pip install --no-cache-dir poetry==${POETRY_VERSION} poetry-plugin-export

# Export dependencies to requirements.txt
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes --only main

# Stage 2: Final runtime image
FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from requirements.txt (cached layer)
COPY --from=deps /app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Yandex Cloud CLI
RUN curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash -s -- -i /usr/local/bin
ENV PATH="/usr/local/bin/bin:${PATH}"

# Application code (changes most frequently, so last)
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
