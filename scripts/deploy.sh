#!/bin/bash

# D&D 5e Combat Simulator Production Deployment Script

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="dnd5e-combat-sim"
DEPLOYMENT_TYPE="${1:-fly}"  # fly, docker, or local
ENVIRONMENT="${2:-production}"

echo -e "${GREEN}🚀 Starting deployment of D&D 5e Combat Simulator${NC}"
echo -e "${YELLOW}Deployment type: ${DEPLOYMENT_TYPE}${NC}"
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    case $DEPLOYMENT_TYPE in
        "fly")
            if ! command -v flyctl &> /dev/null; then
                print_error "Fly.io CLI not found. Please install it first."
                exit 1
            fi
            ;;
        "docker")
            if ! command -v docker &> /dev/null; then
                print_error "Docker not found. Please install it first."
                exit 1
            fi
            if ! command -v docker-compose &> /dev/null; then
                print_error "Docker Compose not found. Please install it first."
                exit 1
            fi
            ;;
    esac
    
    print_status "Prerequisites check passed"
}

# Function to validate environment
validate_environment() {
    print_status "Validating environment configuration..."
    
    # Check required environment variables
    required_vars=("SECRET_KEY" "DATABASE_URL")
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            print_warning "Environment variable $var not set"
        fi
    done
    
    print_status "Environment validation completed"
}

# Function to run tests
run_tests() {
    print_status "Running tests..."
    
    # Run unit tests
    if python -m pytest tests/ -v --tb=short; then
        print_status "Unit tests passed"
    else
        print_error "Unit tests failed"
        exit 1
    fi
    
    # Run deployment tests
    if python -m pytest tests/test_deployment.py -v; then
        print_status "Deployment tests passed"
    else
        print_warning "Some deployment tests failed (this may be expected in CI)"
    fi
}

# Function to build application
build_application() {
    print_status "Building application..."
    
    case $DEPLOYMENT_TYPE in
        "fly")
            # Fly.io will build during deployment
            print_status "Build will be handled by Fly.io"
            ;;
        "docker")
            docker-compose build --no-cache
            print_status "Docker build completed"
            ;;
        "local")
            # Install dependencies
            pip install -r requirements.txt
            print_status "Local build completed"
            ;;
    esac
}

# Function to initialize database
initialize_database() {
    print_status "Initializing database..."
    
    case $DEPLOYMENT_TYPE in
        "fly")
            # Database will be initialized on first run
            print_status "Database will be initialized on first run"
            ;;
        "docker")
            docker-compose exec web python scripts/init_db.py
            print_status "Database initialized"
            ;;
        "local")
            python scripts/init_db.py
            print_status "Database initialized"
            ;;
    esac
}

# Function to deploy to Fly.io
deploy_fly() {
    print_status "Deploying to Fly.io..."
    
    # Check if app exists
    if ! fly apps list | grep -q "$APP_NAME"; then
        print_status "Creating new Fly.io app..."
        fly apps create "$APP_NAME"
    fi
    
    # Set secrets if not already set
    if [ -n "$SECRET_KEY" ]; then
        fly secrets set SECRET_KEY="$SECRET_KEY" --app "$APP_NAME"
    fi
    
    if [ -n "$DATABASE_URL" ]; then
        fly secrets set DATABASE_URL="$DATABASE_URL" --app "$APP_NAME"
    fi
    
    # Deploy
    fly deploy --app "$APP_NAME"
    
    print_status "Fly.io deployment completed"
}

# Function to deploy with Docker
deploy_docker() {
    print_status "Deploying with Docker..."
    
    # Stop existing containers
    docker-compose down
    
    # Start new containers
    docker-compose up -d
    
    # Wait for application to start
    print_status "Waiting for application to start..."
    sleep 10
    
    # Check health
    if curl -f http://localhost:5000/healthz > /dev/null 2>&1; then
        print_status "Application is healthy"
    else
        print_error "Application health check failed"
        exit 1
    fi
    
    print_status "Docker deployment completed"
}

# Function to deploy locally
deploy_local() {
    print_status "Deploying locally..."
    
    # Start the application
    python app.py &
    APP_PID=$!
    
    # Wait for application to start
    sleep 5
    
    # Check health
    if curl -f http://localhost:5000/healthz > /dev/null 2>&1; then
        print_status "Application is healthy"
        print_status "Application running on http://localhost:5000"
        print_status "Press Ctrl+C to stop"
        
        # Wait for interrupt
        trap "kill $APP_PID; exit" INT
        wait $APP_PID
    else
        print_error "Application health check failed"
        kill $APP_PID 2>/dev/null || true
        exit 1
    fi
}

# Function to run health checks
run_health_checks() {
    print_status "Running health checks..."
    
    local base_url=""
    case $DEPLOYMENT_TYPE in
        "fly")
            base_url="https://$APP_NAME.fly.dev"
            ;;
        "docker"|"local")
            base_url="http://localhost:5000"
            ;;
    esac
    
    # Basic health check
    if curl -f "$base_url/healthz" > /dev/null 2>&1; then
        print_status "Health check passed"
    else
        print_error "Health check failed"
        return 1
    fi
    
    # API health check
    if curl -f "$base_url/api/monsters" > /dev/null 2>&1; then
        print_status "API health check passed"
    else
        print_error "API health check failed"
        return 1
    fi
    
    print_status "All health checks passed"
}

# Function to run load tests (optional)
run_load_tests() {
    if [ "$ENVIRONMENT" = "production" ] && [ "$DEPLOYMENT_TYPE" = "fly" ]; then
        print_status "Running load tests..."
        
        # Install locust if not available
        if ! command -v locust &> /dev/null; then
            pip install locust
        fi
        
        # Run load test for 1 minute
        timeout 60s locust -f tests/test_load.py --host="https://$APP_NAME.fly.dev" --users 5 --spawn-rate 1 --run-time 1m --headless || true
        
        print_status "Load tests completed"
    fi
}

# Function to cleanup
cleanup() {
    print_status "Cleaning up..."
    
    case $DEPLOYMENT_TYPE in
        "docker")
            # Keep containers running for local deployment
            ;;
        "local")
            # Kill background processes
            pkill -f "python app.py" 2>/dev/null || true
            ;;
    esac
    
    print_status "Cleanup completed"
}

# Main deployment flow
main() {
    echo -e "${GREEN}🎯 Starting deployment process...${NC}"
    
    check_prerequisites
    validate_environment
    run_tests
    build_application
    initialize_database
    
    case $DEPLOYMENT_TYPE in
        "fly")
            deploy_fly
            ;;
        "docker")
            deploy_docker
            ;;
        "local")
            deploy_local
            ;;
        *)
            print_error "Unknown deployment type: $DEPLOYMENT_TYPE"
            exit 1
            ;;
    esac
    
    if [ "$DEPLOYMENT_TYPE" != "local" ]; then
        run_health_checks
        run_load_tests
    fi
    
    print_status "Deployment completed successfully! 🎉"
}

# Handle script interruption
trap cleanup EXIT

# Run main function
main "$@" 