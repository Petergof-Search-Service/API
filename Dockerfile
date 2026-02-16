FROM python:3.13-slim

WORKDIR /app

# Install system deps for yc cli and build
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry (2.x to match poetry.lock format)
ENV POETRY_VERSION=2.1.4
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VIRTUALENVS_CREATE=false
ENV PATH="${POETRY_HOME}/bin:${PATH}"
RUN curl -sSL https://install.python-poetry.org | python3 -

# Dependencies first (better layer cache)
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-interaction --no-root

# Yandex Cloud CLI
RUN curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash -s -- -i /usr/local/bin
ENV PATH="/usr/local/bin/bin:${PATH}"

# Application
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
