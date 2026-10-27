# Stage 1: Build TypeScript frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /build/src/xarrtools/web
COPY src/xarrtools/web/package.json src/xarrtools/web/package-lock.json src/xarrtools/web/tsconfig.json ./
RUN npm ci
COPY src/xarrtools/web/static/src ./static/src
RUN npm run build

# Stage 2: Runtime environment
FROM python:3.12-slim
WORKDIR /app

# Create a non-root system user and prepare directories
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -d /app -s /bin/bash appuser && \
    mkdir -p /config /app && \
    chown -R appuser:appuser /config /app

# Install runtime dependencies from pyproject.toml
COPY pyproject.toml README.md MANIFEST.in ./
RUN python3 -c "import tomllib; c = tomllib.load(open('pyproject.toml', 'rb')); open('/tmp/requirements.txt', 'w').write('\n'.join(c['project']['dependencies']))" && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Copy application files and compiled frontend assets
COPY src/ ./src/
COPY --from=frontend-builder /build/src/xarrtools/web/static/dist ./src/xarrtools/web/static/dist

# Install application package
RUN pip install --no-cache-dir --no-deps .

# Ensure permissions
RUN chown -R appuser:appuser /app

ARG VERSION=0.0.0-dev

LABEL org.opencontainers.image.title="xarrtools" \
      org.opencontainers.image.description="Upcoming and new TV show/movie discovery and triage companion for Radarr and Sonarr" \
      org.opencontainers.image.url="https://github.com/devicenul/xarrtools" \
      org.opencontainers.image.source="https://github.com/devicenul/xarrtools" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="GPL-3.0"

# Set default environment variables
ENV XARRTOOLS_CONFIG_DIR=/config \
    XARRTOOLS_HOST=0.0.0.0 \
    XARRTOOLS_PORT=5000 \
    XARRTOOLS_VERSION=${VERSION} \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

EXPOSE 5000
VOLUME ["/config"]

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3).getcode() == 200 else 1)"

CMD ["python", "-m", "xarrtools", "--server", "--no-browser"]
