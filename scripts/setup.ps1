# Setup script for academic-cluster using uv (Windows PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "=== Academic Cluster Setup ===" -ForegroundColor Cyan

# Check if uv is installed
try {
    $uvVersion = uv --version
    Write-Host "Using uv version: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "uv not found. Installing..." -ForegroundColor Yellow
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# Create virtual environment
Write-Host "Creating virtual environment..." -ForegroundColor Yellow
uv venv .venv --python 3.10

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
. .venv\Scripts\Activate.ps1

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
uv pip install -e ".[dev]"

# Install pre-commit hooks
Write-Host "Installing pre-commit hooks..." -ForegroundColor Yellow
pre-commit install

# Create .env from example if it doesn't exist
if (-not (Test-Path .env)) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "Please edit .env with your API keys" -ForegroundColor Cyan
}

# Create necessary directories
Write-Host "Creating directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path data\raw, data\processed, data\embeddings, logs | Out-Null

# Download spaCy model
Write-Host "Downloading spaCy model..." -ForegroundColor Yellow
python -m spacy download en_core_web_sm

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Edit .env with your API keys"
Write-Host "2. Run '.venv\Scripts\Activate.ps1' to activate the environment"
Write-Host "3. Run 'docker-compose up -d' to start PostgreSQL and Redis"
Write-Host "4. Run 'pytest' to verify the setup"
