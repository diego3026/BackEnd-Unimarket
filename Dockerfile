# Imagen de producción de la API de UniMarket
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Usuario sin privilegios
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

ENV PORT=8000 \
    RESEARCH_STATE_PATH=/tmp/research_state.sqlite3
EXPOSE 8000

# Railway inyecta $PORT. Las migraciones se aplican antes de arrancar (son idempotentes:
# si ya están al día no hacen nada). railway.json también las corre en preDeployCommand.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-server-header --workers ${WEB_CONCURRENCY:-2}"]
