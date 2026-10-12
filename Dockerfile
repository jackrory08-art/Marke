FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Non-root user; /data holds the SQLite database (a volume in compose)
RUN useradd --create-home --uid 10001 marke \
    && mkdir -p /data /app/logs \
    && chown -R marke:marke /data /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=marke:marke . .

USER marke
ENV DATABASE_URL=sqlite:////data/marke.db
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=3)"

# Binding 0.0.0.0 is fine in a container. Port: $PORT if the platform sets it, else 8000.
# Compose publishes the port on loopback only.
CMD ["python", "run_with_dashboard.py", "--host", "0.0.0.0"]
