# syntax=docker/dockerfile:1

# --- Builder stage ---
FROM python:3.11-slim AS builder
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --prefix=/install -r requirements.txt

# Copy application code
COPY . .

# --- Final stage ---
FROM python:3.11-slim
WORKDIR /app

# Create non-root user
RUN useradd -m appuser

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy app code
COPY --from=builder /app /app

# Set permissions
RUN chown -R appuser:appuser /app

# Expose Flask port
EXPOSE 5000

# Healthcheck endpoint. The slim image has no curl; urlopen raises (exit 1) unless /healthz answers 2xx
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz', timeout=4)"]

# Runs the app as appuser, after giving it the database's folder (see the script)
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

# Environment variables (can be overridden)
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Entrypoint for prod (can override for dev)
# One worker: running simulations and batches report progress from that process's memory,
# so every status poll has to reach it. Threads serve requests concurrently.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8"] 