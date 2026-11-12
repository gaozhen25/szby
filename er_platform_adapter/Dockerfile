
FROM harbor.bytech.tech/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     build-essential \
#     curl \
#     && rm -rf /var/lib/apt/lists/*


# RUN pip install poetry

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main --no-interaction --no-ansi --no-root

COPY . .

CMD ["python", "-m", "adapter_gateway.cli","--host", "0.0.0.0"]