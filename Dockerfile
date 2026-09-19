# Single-image build for Azure Web App for Containers (one container, one public port).
#   - Next.js (standalone) listens on $PORT (3000) and proxies /api/* to FastAPI
#   - FastAPI (uvicorn) listens on 127.0.0.1:8000, reachable only from inside the container
# For local development run the two apps directly (see README).

# ---- Stage 1: build the Next.js frontend ----
FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Rewrites are resolved at build time: /api/* -> the FastAPI process in this same container.
ENV BACKEND_URL=http://127.0.0.1:8000 \
    NEXT_PUBLIC_APP_NAME=StockSense
RUN npm run build

# ---- Stage 2: Python runtime + the built frontend ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Node runtime only (the frontend is already built) — copied from the build stage.
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/app backend/app
COPY --from=frontend-build /frontend/public frontend/public
COPY --from=frontend-build /frontend/.next/standalone frontend/
COPY --from=frontend-build /frontend/.next/static frontend/.next/static
COPY start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh \
    && useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 3000
CMD ["/app/start.sh"]
