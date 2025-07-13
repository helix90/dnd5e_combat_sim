#!/bin/bash
# Usage: source scripts/env_setup.sh

export FLASK_ENV=development
export FLASK_DEBUG=1
export PYTHONUNBUFFERED=1
export DATABASE_URL=sqlite:///$(pwd)/data/app.db
export SECRET_KEY=dev-secret-key
# Add any other required env vars here

echo "Environment variables set for D&D 5e Combat Simulator." 