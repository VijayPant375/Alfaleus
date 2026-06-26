#!/usr/bin/env bash
# scripts/deploy-web.sh
set -e

echo "Deploying Web Frontend..."
cd "$(dirname "$0")/../web"

echo "Installing dependencies..."
npm install

echo "Building Next.js app..."
npm run build

echo "Web frontend built successfully! Please restart the web service (e.g., using pm2)."
