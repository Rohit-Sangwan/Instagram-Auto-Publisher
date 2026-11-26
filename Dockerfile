FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.13-slim-bookworm AS api
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 publisher && useradd --uid 10001 --gid publisher publisher \
    && install -d -o publisher -g publisher -m 0700 /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY migrations migrations
COPY alembic.ini .
USER publisher
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "60"]

FROM nginx:stable-alpine AS proxy
COPY --from=frontend /build/dist/ /usr/share/nginx/html/
COPY deploy/default.conf.template /etc/nginx/templates/default.conf.template
