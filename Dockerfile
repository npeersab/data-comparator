# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: install Python dependencies into a temp prefix.
# Binary wheels (psycopg2-binary, pymysql) need no compiler; slim has none.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime stage: minimal image with only what's needed to run the app.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATA_COMPARATOR_DB=/app/data/connections.db
WORKDIR /app
COPY --from=build /install /usr/local
COPY app/ ./app/
COPY static/ ./static/

# Persist saved connections + encryption key under a dir writable by the
# unprivileged user; bind-mount a volume at /app/data to keep it across restarts.
RUN mkdir -p /app/data && chown app:app /app/data
# Create an unprivileged user to run as (recent slim images ship no 'python' user).
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --create-home app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/dialects').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
