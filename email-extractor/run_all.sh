#!/bin/bash
set -e

# Build the container
echo "Building Docker container..."
cd "$(dirname "$0")"
docker compose build

# Run the extraction (this will also run evaluation as per docker-compose command)
echo "Running extraction and evaluation..."
docker compose up
