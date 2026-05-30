#!/bin/bash
# setup_orin_local_llm.sh
# This script installs Ollama on the Jetson Orin, pulls the Gemma 2 9B model,
# and installs the python dependencies required for local edge AI inference.

set -e

echo "=========================================================="
echo "Initializing Jetson Orin Local LLM Setup"
echo "=========================================================="

# 1. Install Ollama (official installer supports ARM64/Jetpack out of the box)
if ! command -v ollama &> /dev/null; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama is already installed."
fi

# 2. Ensure Ollama service is running
echo "Checking Ollama service status..."
if systemctl is-active --quiet ollama; then
    echo "Ollama service is active."
else
    echo "Starting Ollama service..."
    sudo systemctl start ollama
fi

# 3. Pull the recommended local models
# We pull both gemma2:2b (for ultra-fast low-memory tests) and gemma2:9b (for production accuracy)
echo "Pulling Google Gemma 2 (2B quantized) model..."
ollama pull gemma2:2b

echo "Pulling Google Gemma 2 (9B quantized) model..."
ollama pull gemma2:9b

# 4. Install Ollama Python library in our virtual environment
echo "Installing Ollama Python libraries..."
if [ -d "./venv" ]; then
    ./venv/bin/pip install ollama
else
    echo "Python virtual environment (venv) not found in current directory."
    echo "To install globally, run: pip install ollama"
fi

echo "=========================================================="
echo "Setup Complete!"
echo "To test local inference run: ollama run gemma2:2b 'Hello, Orin!'"
echo "=========================================================="
