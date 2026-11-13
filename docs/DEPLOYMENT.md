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

### 3. Create the App and Its Volume

`fly.toml` in the repository holds the configuration. Change `app` to a name of your own (app
names are unique across Fly.io) and `primary_region` to a region near you (`fly platform regions`).

```bash
fly apps create your-app-name

# The SQLite database lives on this volume, mounted at /data, so it survives deploys and restarts
fly volumes create data --size 1 --region ord
```

### 4. Set the Secret Key

```bash
fly secrets set SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
```

On Fly.io the app refuses to start without it. `fly.toml` sets the rest: `DATABASE_URL`
(`sqlite:////data/app.db`, on the volume), `FLASK_SESSION_COOKIE_SECURE=true` and
`FLASK_ENV=production`.

### 5. Deploy the Application

```bash
fly deploy

# Check deployment status
fly status

# View logs
fly logs
```

### One Machine, Always Running

A running batch's progress lives in the memory of the machine running it, so `fly.toml` keeps
exactly one machine and never stops it (`auto_stop_machines = "off"`, `min_machines_running = 1`).
Don't `fly scale count` above 1: a second machine couldn't report the first one's batches, and
the volume belongs to one machine anyway. A deploy or restart cuts off any batch still running;
its page then says it was interrupted.

### Visitors' Addresses

Every request reaches the app from Fly.io's proxy, which adds the visitor's address to
`X-Forwarded-For`. On Fly.io (where `FLY_APP_NAME` is set) the app trusts that one proxy, so rate
limits apply to each visitor rather than to everyone at once. Behind other proxies, set
`TRUSTED_PROXIES` to how many there are.

### 6. Configure Custom Domain (Optional)

```bash
# Add custom domain
fly certs add your-domain.com

# Check certificate status
fly certs show your-domain.com
```

## Docker Configuration

### Dockerfile

The image is a two-stage build on `python:3.11-slim`, serving the app with gunicorn on port
5000: one worker, since running simulations and batches report progress from that process's
memory, and 8 threads. Its `HEALTHCHECK` fetches `/healthz` with Python, as the slim image has no
curl. `docker-entrypoint.sh` starts the app as the unprivileged `appuser`, first giving it the
database's folder when that's a volume owned by root, as Fly.io mounts them.

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
- **FLASK_SESSION_COOKIE_SECURE**: true
- **PYTHONUNBUFFERED**: 1

### Environment Variable Reference

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| FLASK_ENV | Flask environment | development | No |
| FLASK_DEBUG | Enable debug mode | 0 | No |
| DATABASE_URL | Database connection string | sqlite:///data/app.db | No |
| SECRET_KEY | Flask secret key | dev-secret-key | Yes |
| PYTHONUNBUFFERED | Python output buffering | 1 | No |
| FLASK_SESSION_COOKIE_SECURE | Send the session cookie over HTTPS only | false | Yes, behind HTTPS |
| TRUSTED_PROXIES | Proxies in front of the app that add to X-Forwarded-For | 1 on Fly.io, else 0 | No |

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
[[http_service.checks]]
  interval = "30s"
  timeout = "5s"
  grace_period = "10s"
  method = "GET"
  path = "/healthz"
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

On Fly.io, the volume is snapshotted daily and the snapshots are kept for 5 days:

```bash
fly volumes list                       # the volume's id
fly volumes snapshots list <volume-id>
```

To copy the database down, take a consistent copy with Python's SQLite (the image has no
`sqlite3` command) and fetch it:

```bash
fly ssh console -C "python -c \"import sqlite3; sqlite3.connect('/data/app.db').backup(sqlite3.connect('/data/backup.db'))\""
fly ssh sftp get /data/backup.db
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

Not yet: the app runs on one machine (see "One Machine, Always Running"). Scale it up instead.

### Vertical Scaling

```bash
# Scale to larger VM
fly scale vm shared-cpu-2x
fly scale memory 1024
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