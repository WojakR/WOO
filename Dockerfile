# Asystent Ocen Okresowych – obraz aplikacji (interfejs Streamlit z API FastAPI w tym samym procesie + SQLite).
# Kontekst budowania = katalog główny repozytorium (aplikacja czyta dane KPRM z data/kprm):
#   docker compose up -d            (patrz docker-compose.yml)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Database outside the code, on a volume; runs as a regular user
ENV DB_PATH=/data/app.db \
    AI_MODE=off
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
VOLUME ["/data"]

EXPOSE 8000
# The UI is the app (as on a laptop with Uruchom.bat): Streamlit runs the /api routes in-process (frontend/api_client.py)
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/_stcore/health', timeout=2)"
CMD ["python", "-m", "streamlit", "run", "frontend/app.py", "--server.address", "0.0.0.0", "--server.port", "8000", \
     "--server.headless", "true", "--browser.gatherUsageStats", "false"]
