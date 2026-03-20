#!/bin/bash

# Valinor SaaS - Simple MVP Startup Script

set -e

echo "🚀 Starting Valinor SaaS - Simple MVP"
echo "==============================================="

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is required"
    exit 1
fi

# Check if pip requirements are installed
echo "📦 Checking dependencies..."
if ! python3 -c "import fastapi, paramiko, anthropic" 2>/dev/null; then
    echo "⚠️  Installing requirements..."
    pip install -r requirements_simple.txt
fi

# Check for Anthropic API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  Warning: ANTHROPIC_API_KEY not set"
    echo "   Set it with: export ANTHROPIC_API_KEY=your_key_here"
fi

# Create necessary directories
mkdir -p /tmp/valinor_jobs
mkdir -p /tmp/valinor_output

echo "✅ Setup complete"
echo ""
echo "🌐 Starting server on http://localhost:8000"
echo "📖 API docs available at http://localhost:8000/docs"
echo ""
echo "🔄 To test the API:"
echo "   curl http://localhost:8000/health"
echo ""

# Start the simple API
python3 simple_api.py