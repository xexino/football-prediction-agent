# Football Intelligence Lab — single container (API + dashboard + scheduler)
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /app/backend/fil/static backend/fil/static
ENV FIL_DB_PATH=/data/fil.db FIL_BACKUP_DIR=/data/backups FIL_CACHE_DIR=/data/cache PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
WORKDIR /app/backend
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["python", "-m", "fil", "serve"]
