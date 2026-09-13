FROM python:3.12-slim

WORKDIR /app

# libpq-dev needed for psycopg2-binary; libsnappy1 required by python-snappy
# libpq-dev needed for psycopg2-binary; python-snappy ships with a bundled
# snappy binary in its manylinux wheel so no system libsnappy is required.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Run Alembic migrations then start the ASGI server.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
