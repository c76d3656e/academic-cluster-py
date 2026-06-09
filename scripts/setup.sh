#!/bin/bash
# Setup script for academic-cluster using uv

set -e

echo "=== Academic Cluster Setup ==="

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env
fi

echo "Using uv version: $(uv --version)"

# Create virtual environment
echo "Creating virtual environment..."
uv venv .venv --python 3.10

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate || . .venv/Scripts/activate

# Install dependencies
echo "Installing dependencies..."
uv pip install -e ".[dev]"

# Install pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Please edit .env with your API keys"
fi

# Create necessary directories
echo "Creating directories..."
mkdir -p data/{raw,processed,embeddings}
mkdir -p logs

# Download spaCy model
echo "Downloading spaCy model..."
python -m spacy download en_core_web_sm

# Initialize database (if needed)
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your API keys"
echo "2. Run 'source .venv/bin/activate' to activate the environment"
echo "3. Run 'docker-compose up -d' to start PostgreSQL and Redis"
echo "4. Run 'pytest' to verify the setup"
