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

# Healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD curl -f http://localhost:5000/healthz || exit 1

# Switch to non-root user
USER appuser

# Environment variables (can be overridden)
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Entrypoint for prod (can override for dev)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "3"] 