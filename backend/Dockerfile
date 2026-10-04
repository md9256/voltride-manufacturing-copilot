# Back end image. Runs on Render (sets $PORT) or Hugging Face Spaces (port 7860),
# as an unprivileged user (uid 1000, which Spaces requires).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 app
WORKDIR /home/app/backend

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app app ./app
COPY --chown=app:app scripts ./scripts
# Migrations run at startup (app.main lifespan).
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations

USER app
EXPOSE 7860
ENV PORT=7860
# Secrets (ODOO_*, DATABASE_URL, GEMINI_API_KEY, ...) come from the platform as env vars.
# The disk is ephemeral, so nothing is written locally.
# Shell form so $PORT expands; exec makes uvicorn PID 1 so it receives SIGTERM. --proxy-headers: the client IP (used for rate
# limits) comes from the platform proxy's X-Forwarded-For header.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'

