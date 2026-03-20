#!/bin/bash

# Start Valinor SaaS MVP

set -e

echo "🚀 Starting Valinor SaaS MVP..."

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is required but not installed"
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found, copying from .env.example"
    cp .env.example .env
    echo "✏️  Please edit .env file with your API keys"
fi

# Check for required API keys
if ! grep -q "ANTHROPIC_API_KEY=.*[a-zA-Z0-9]" .env; then
    echo "⚠️  Warning: ANTHROPIC_API_KEY not set in .env file"
    echo "   Set this to run actual analysis"
fi

# Stop any existing containers
echo "🛑 Stopping any existing containers..."
docker-compose -f docker-compose.dev.yml down

# Build and start core services
echo "🔨 Building and starting services..."
docker-compose -f docker-compose.dev.yml up -d postgres redis

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check PostgreSQL
echo "🐘 Checking PostgreSQL..."
until docker-compose -f docker-compose.dev.yml exec postgres pg_isready -U valinor; do
    echo "Waiting for PostgreSQL..."
    sleep 2
done

# Check Redis
echo "📱 Checking Redis..."
until docker-compose -f docker-compose.dev.yml exec redis redis-cli ping; do
    echo "Waiting for Redis..."
    sleep 2
done

# Start API and Worker
echo "🔧 Starting API and Worker..."
docker-compose -f docker-compose.dev.yml up -d api worker

# Start web interface (MVP profile)
echo "🌐 Starting web interface..."
docker-compose -f docker-compose.dev.yml --profile mvp up -d web

echo ""
echo "✅ Valinor SaaS MVP is now running!"
echo ""
echo "🔗 Services:"
echo "   API:     http://localhost:8000"
echo "   Docs:    http://localhost:8000/docs"
echo "   Health:  http://localhost:8000/health"
echo "   Web UI:  http://localhost:3000"
echo "   Flower:  http://localhost:5555 (Celery monitoring)"
echo ""
echo "📊 To view logs:"
echo "   docker-compose -f docker-compose.dev.yml logs -f api"
echo "   docker-compose -f docker-compose.dev.yml logs -f worker"
echo ""
echo "🛑 To stop all services:"
echo "   docker-compose -f docker-compose.dev.yml down"
echo ""

# Optional: Start Flower for monitoring
read -p "Start Celery monitoring (Flower)? [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker-compose -f docker-compose.dev.yml up -d flower
    echo "🌸 Flower started at http://localhost:5555"
fi

echo "🎉 MVP setup complete! Happy analyzing!"