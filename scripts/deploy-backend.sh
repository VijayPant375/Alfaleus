#!/usr/bin/env bash
# scripts/deploy-backend.sh
set -e

echo "Deploying Backend..."
cd "$(dirname "$0")/../backend"

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python -m venv venv
fi

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
  source venv/Scripts/activate
fi

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running migrations..."
alembic upgrade head

echo "Backend deployed successfully! Please restart the backend service (e.g., using systemd, pm2, or docker)."
