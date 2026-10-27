# Stage 1: Build TypeScript frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY package.json package-lock.json tsconfig.json ./
RUN npm ci
COPY web/static/src ./web/static/src
RUN npm run build

# Stage 2: Runtime environment
FROM python:3.12-slim
WORKDIR /app

# Create a non-root system user and prepare directories
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -d /app -s /bin/bash appuser && \
    mkdir -p /config /app && \
    chown -R appuser:appuser /config /app

# Install runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY core/ ./core/
COPY web/ ./web/
COPY cli/ ./cli/
COPY gui/ ./gui/
COPY main.py .

# Copy compiled frontend assets from builder stage
COPY --from=frontend-builder /build/web/static/dist ./web/static/dist

# Ensure permissions
RUN chown -R appuser:appuser /app

# Set default environment variables
ENV XARRTOOLS_CONFIG_DIR=/config \
    XARRTOOLS_HOST=0.0.0.0 \
    XARRTOOLS_PORT=5000 \
    PYTHONUNBUFFERED=1

EXPOSE 5000
VOLUME ["/config"]

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3).getcode() == 200 else 1)"

CMD ["python", "main.py", "--server", "--no-browser"]
