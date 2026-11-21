# Asystent Ocen Okresowych – obraz aplikacji (FastAPI + interfejs webowy + SQLite).
# Kontekst budowania = katalog główny repozytorium (aplikacja czyta dane KPRM z server/data/kprm):
#   docker compose up -d            (z katalogu projekt/, patrz docker-compose.yml)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/projekt
COPY projekt/requirements.txt .
RUN pip install -r requirements.txt

COPY server/data/kprm /app/server/data/kprm
COPY projekt/ .

# Database outside the code, on a volume; runs as a regular user
ENV DB_PATH=/data/app.db \
    AI_MODE=off
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta', timeout=2)"
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
