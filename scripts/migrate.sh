#!/usr/bin/env bash
# scripts/migrate.sh
set -e

echo "Running Database Migrations..."
cd "$(dirname "$0")/../backend"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
  source venv/Scripts/activate
fi

alembic upgrade head
echo "Migrations completed successfully."
