# D&D 5e Combat Simulator Deployment Guide

## Overview

This guide covers deploying the D&D 5e Combat Simulator using Docker, Docker Compose, and Fly.io. The application is designed to be containerized and can run in various environments.

## Prerequisites

- Docker and Docker Compose installed
- Fly.io CLI (for production deployment)
- Git (for version control)

## Local Development with Docker

### 1. Build and Run with Docker Compose

```bash
# Clone the repository
git clone <repository-url>
cd dnd5e_combat_sim

# Build and start the application
docker-compose up --build

# The application will be available at http://localhost:5000
```

### 2. Environment Variables

Create a `.env` file for local development:

```env
FLASK_ENV=development
FLASK_DEBUG=1
PYTHONUNBUFFERED=1
DATABASE_URL=sqlite:///data/app.db
SECRET_KEY=your-dev-secret-key
```

### 3. Database Initialization

The database will be automatically initialized on first run. To manually initialize:

```bash
# Run database initialization script
docker-compose exec web python scripts/init_db.py
```

### 4. Development Workflow

```bash
# Start development environment
docker-compose up

# View logs
docker-compose logs -f web

# Stop the application
docker-compose down

# Rebuild after code changes
docker-compose up --build
```

## Production Deployment with Fly.io

### 1. Install Fly.io CLI

```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows
# Download from https://fly.io/docs/hands-on/install-flyctl/
```

### 2. Authenticate with Fly.io

```bash
fly auth login
```

### 3. Create a New App

```bash
# Create a new app (replace 'your-app-name' with desired name)
fly apps create your-app-name

# Or use the existing fly.toml configuration
fly launch
```

### 4. Set Environment Variables

```bash
# Set production environment variables
fly secrets set FLASK_ENV=production
fly secrets set SECRET_KEY=your-production-secret-key
fly secrets set DATABASE_URL=sqlite:////data/app.db
```

### 5. Deploy the Application

```bash
# Deploy to Fly.io
fly deploy

# Check deployment status
fly status

# View logs
fly logs
```

### 6. Configure Custom Domain (Optional)

```bash
# Add custom domain
fly certs add your-domain.com

# Check certificate status
fly certs show your-domain.com
```

## Docker Configuration

### Dockerfile

The application uses a multi-stage Docker build for optimization:

```dockerfile
# Builder stage
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential gcc
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt
COPY . .

# Final stage
FROM python:3.11-slim
WORKDIR /app
RUN useradd -m appuser
COPY --from=builder /install /usr/local
COPY --from=builder /app /app
RUN chown -R appuser:appuser /app
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:5000/healthz || exit 1
USER appuser
ENV FLASK_ENV=production
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "3"]
```

### Docker Compose

```yaml
version: '3.8'
services:
  web:
    build: .
    container_name: dnd5e-combat-sim-dev
    command: flask run --host=0.0.0.0 --port=5000 --reload
    environment:
      - FLASK_ENV=development
      - FLASK_DEBUG=1
      - PYTHONUNBUFFERED=1
      - DATABASE_URL=sqlite:////app/data/app.db
      - SECRET_KEY=dev-secret-key
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - .:/app
    restart: unless-stopped
```

## Environment Configuration

### Development Environment

- **FLASK_ENV**: development
- **FLASK_DEBUG**: 1
- **DATABASE_URL**: sqlite:///data/app.db
- **SECRET_KEY**: dev-secret-key

### Production Environment

- **FLASK_ENV**: production
- **DATABASE_URL**: sqlite:////data/app.db
- **SECRET_KEY**: [generate secure random key]
- **PYTHONUNBUFFERED**: 1

### Environment Variable Reference

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| FLASK_ENV | Flask environment | development | No |
| FLASK_DEBUG | Enable debug mode | 0 | No |
| DATABASE_URL | Database connection string | sqlite:///data/app.db | No |
| SECRET_KEY | Flask secret key | dev-secret-key | Yes |
| PYTHONUNBUFFERED | Python output buffering | 1 | No |

## Monitoring and Health Checks

### Health Check Endpoint

The application provides a health check endpoint at `/healthz`:

```bash
# Test health check
curl http://localhost:5000/healthz
# Returns: ok
```

### Fly.io Health Checks

Configured in `fly.toml`:

```toml
[checks]
  [checks.http]
    interval = "30s"
    timeout = "5s"
    grace_period = "10s"
    method = "get"
    path = "/healthz"
    protocol = "http"
```

### Monitoring Endpoints

- `/healthz`: Basic health check
- `/api/monsters`: API availability test
- Application logs: Available via `fly logs`

## Database Management

### SQLite Database

The application uses SQLite for simplicity. The database file is stored in the `data/` directory.

### Backup and Restore

```bash
# Backup database
docker-compose exec web sqlite3 /app/data/app.db ".backup /app/data/backup.db"

# Restore database
docker-compose exec web sqlite3 /app/data/app.db ".restore /app/data/backup.db"
```

### Database Initialization

```bash
# Initialize database schema
python scripts/init_db.py

# Or via Docker
docker-compose exec web python scripts/init_db.py
```

## Security Considerations

### Production Security

1. **Secret Key**: Generate a secure random secret key
2. **HTTPS**: Always use HTTPS in production
3. **Rate Limiting**: Configured to prevent abuse
4. **Input Validation**: All inputs are validated and sanitized
5. **Security Headers**: Automatically added to all responses

### Security Headers

The application includes the following security headers:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy`: Configured for security

## Troubleshooting

### Common Issues

#### 1. Port Already in Use

```bash
# Check what's using port 5000
lsof -i :5000

# Kill the process or use a different port
docker-compose up -p 5001
```

#### 2. Database Permission Issues

```bash
# Fix database permissions
sudo chown -R $USER:$USER data/
chmod 755 data/
```

#### 3. Docker Build Failures

```bash
# Clean Docker cache
docker system prune -a

# Rebuild without cache
docker-compose build --no-cache
```

#### 4. Fly.io Deployment Issues

```bash
# Check deployment status
fly status

# View deployment logs
fly logs

# Restart the application
fly apps restart your-app-name
```

### Logs and Debugging

#### Local Development

```bash
# View application logs
docker-compose logs -f web

# Access container shell
docker-compose exec web bash
```

#### Production (Fly.io)

```bash
# View application logs
fly logs

# View specific log stream
fly logs --app your-app-name

# SSH into the application
fly ssh console
```

### Performance Issues

1. **High Memory Usage**: Monitor with `fly status`
2. **Slow Response Times**: Check database queries and caching
3. **Rate Limiting**: Adjust limits in `app.py` if needed

## Scaling

### Horizontal Scaling (Fly.io)

```bash
# Scale to multiple instances
fly scale count 3

# Scale with specific resources
fly scale vm shared-cpu-1x --memory 512
```

### Vertical Scaling

```bash
# Scale to larger VM
fly scale vm shared-cpu-2x --memory 1024
```

## Maintenance

### Regular Maintenance Tasks

1. **Database Cleanup**: Remove old sessions and simulations
2. **Log Rotation**: Monitor log file sizes
3. **Security Updates**: Keep dependencies updated
4. **Backup**: Regular database backups

### Update Procedures

```bash
# Update application
git pull origin main
docker-compose up --build

# Update on Fly.io
fly deploy
```

### Rollback Procedures

```bash
# Rollback to previous deployment
fly deploy --image-label v1.0.0

# Or rollback to specific release
fly releases
fly rollback v1
```

## Support and Resources

- **Documentation**: Check the `docs/` directory
- **Issues**: Report bugs via GitHub issues
- **Monitoring**: Use Fly.io dashboard for monitoring
- **Logs**: Access logs via `fly logs` or Fly.io dashboard

## Best Practices

1. **Environment Separation**: Use different environments for dev/staging/prod
2. **Secret Management**: Use Fly.io secrets for sensitive data
3. **Monitoring**: Set up alerts for critical issues
4. **Backup**: Regular database backups
5. **Testing**: Run tests before deployment
6. **Documentation**: Keep deployment procedures updated 