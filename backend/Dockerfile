# Back end image for Hugging Face Spaces (Docker SDK).
# Spaces routes traffic to port 7860 and runs the container as uid 1000.
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

USER app
EXPOSE 7860
# Secrets (ODOO_*, DATABASE_URL, ANTHROPIC_API_KEY) come from Space secrets as env vars.
# The disk is ephemeral, so nothing is written locally.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips=*"]
