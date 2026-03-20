#!/bin/bash

# Valinor SaaS Development Environment Setup Script
# Usage: ./scripts/dev.sh [command]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

# Functions
print_header() {
    echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║       VALINOR SAAS DEVELOPMENT SETUP       ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
    echo
}

print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
    exit 1
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

check_requirements() {
    echo -e "${BLUE}Checking requirements...${NC}"
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
    fi
    print_status "Docker installed"
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        print_error "Docker Compose is not installed."
    fi
    print_status "Docker Compose installed"
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        print_warning "Python 3 not found. Some scripts may not work."
    else
        print_status "Python $(python3 --version | cut -d' ' -f2) installed"
    fi
    
    # Check Node.js (for frontend)
    if ! command -v node &> /dev/null; then
        print_warning "Node.js not found. Frontend development will not work."
    else
        print_status "Node.js $(node --version) installed"
    fi
}

setup_environment() {
    echo -e "\n${BLUE}Setting up environment...${NC}"
    
    # Create .env if it doesn't exist
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f "$ENV_EXAMPLE" ]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            print_status "Created .env from .env.example"
        else
            # Create basic .env
            cat > "$ENV_FILE" <<EOF
# Valinor SaaS Environment Variables
ENVIRONMENT=development

# API Keys (REQUIRED - get from Anthropic)
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Supabase (optional for development)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key

# Security
ENCRYPTION_KEY=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)

# Database (Docker Compose defaults)
DATABASE_URL=postgresql://valinor:dev_password_change_in_prod@localhost:5432/valinor_metadata
REDIS_URL=redis://localhost:6379

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
EOF
            print_status "Created .env with defaults"
            print_warning "Please update ANTHROPIC_API_KEY in .env file"
        fi
    else
        print_status ".env file already exists"
    fi
    
    # Check for ANTHROPIC_API_KEY
    if grep -q "sk-ant-your-key-here" "$ENV_FILE"; then
        print_warning "ANTHROPIC_API_KEY not configured in .env"
        echo "Please update it with your actual key from https://console.anthropic.com"
    fi
    
    # Create necessary directories
    mkdir -p "$PROJECT_ROOT/demo/ssh_keys"
    mkdir -p "$PROJECT_ROOT/logs"
    mkdir -p "$PROJECT_ROOT/tmp"
    print_status "Created necessary directories"
}

generate_ssh_keys() {
    echo -e "\n${BLUE}Generating demo SSH keys...${NC}"
    
    DEMO_KEY="$PROJECT_ROOT/demo/ssh_keys/demo_rsa"
    
    if [ ! -f "$DEMO_KEY" ]; then
        ssh-keygen -t rsa -b 4096 -f "$DEMO_KEY" -N "" -C "demo@valinor.local"
        chmod 600 "$DEMO_KEY"
        chmod 644 "$DEMO_KEY.pub"
        print_status "Generated demo SSH keys"
    else
        print_status "Demo SSH keys already exist"
    fi
}

copy_valinor_core() {
    echo -e "\n${BLUE}Copying Valinor v0 core...${NC}"
    
    SOURCE_DIR="/home/nicolas/Documents/delta4/Valinor/valinor"
    DEST_DIR="$PROJECT_ROOT/core/valinor"
    
    if [ -d "$SOURCE_DIR" ]; then
        mkdir -p "$DEST_DIR"
        cp -r "$SOURCE_DIR"/* "$DEST_DIR/" 2>/dev/null || true
        print_status "Copied Valinor core from $SOURCE_DIR"
    else
        print_warning "Valinor v0 source not found at $SOURCE_DIR"
        echo "Please manually copy the core Valinor code to $DEST_DIR"
    fi
    
    # Copy .claude skills if they exist
    SKILLS_SOURCE="/home/nicolas/Documents/delta4/Valinor/.claude"
    SKILLS_DEST="$PROJECT_ROOT/core/.claude"
    
    if [ -d "$SKILLS_SOURCE" ]; then
        mkdir -p "$SKILLS_DEST"
        cp -r "$SKILLS_SOURCE"/* "$SKILLS_DEST/" 2>/dev/null || true
        print_status "Copied Claude skills"
    fi
}

start_services() {
    echo -e "\n${BLUE}Starting services...${NC}"
    
    # Pull latest images
    docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" pull
    
    # Start core services
    docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" up -d postgres redis
    
    # Wait for services to be ready
    echo -n "Waiting for PostgreSQL..."
    for i in {1..30}; do
        if docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" exec -T postgres pg_isready -U valinor &>/dev/null; then
            echo -e " ${GREEN}ready${NC}"
            break
        fi
        echo -n "."
        sleep 1
    done
    
    echo -n "Waiting for Redis..."
    for i in {1..10}; do
        if docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" exec -T redis redis-cli ping &>/dev/null; then
            echo -e " ${GREEN}ready${NC}"
            break
        fi
        echo -n "."
        sleep 1
    done
    
    # Start API and Worker
    docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" up -d api worker flower
    
    print_status "All services started"
    
    # Show service URLs
    echo -e "\n${BLUE}Service URLs:${NC}"
    echo "  API:        http://localhost:8000"
    echo "  API Docs:   http://localhost:8000/docs"
    echo "  Flower:     http://localhost:5555"
    echo "  PostgreSQL: localhost:5432"
    echo "  Redis:      localhost:6379"
    
    # Start frontend if requested
    if [ "$1" == "--with-frontend" ] || [ "$1" == "-f" ]; then
        echo -e "\n${BLUE}Starting frontend...${NC}"
        docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" --profile full up -d frontend
        echo "  Frontend:   http://localhost:3000"
    fi
    
    # Start demo services if requested
    if [ "$1" == "--with-demo" ] || [ "$1" == "-d" ]; then
        echo -e "\n${BLUE}Starting demo services...${NC}"
        docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" --profile demo up -d
        echo "  Demo SSH:   localhost:2222"
        echo "  Demo DB:    localhost:5433"
    fi
}

stop_services() {
    echo -e "\n${BLUE}Stopping services...${NC}"
    docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" --profile full --profile demo down
    print_status "All services stopped"
}

reset_environment() {
    echo -e "\n${YELLOW}This will delete all data and reset the environment!${NC}"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        stop_services
        docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" down -v
        rm -rf "$PROJECT_ROOT/tmp/*"
        rm -rf "$PROJECT_ROOT/logs/*"
        print_status "Environment reset complete"
    else
        echo "Reset cancelled"
    fi
}

run_tests() {
    echo -e "\n${BLUE}Running tests...${NC}"
    
    # Run Python tests
    docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" exec api pytest tests/ -v
    
    print_status "Tests completed"
}

show_logs() {
    SERVICE=${1:-api}
    docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" logs -f "$SERVICE"
}

# Main script
print_header

case "${1:-setup}" in
    setup)
        check_requirements
        setup_environment
        generate_ssh_keys
        copy_valinor_core
        start_services "${@:2}"
        echo -e "\n${GREEN}Setup complete! 🚀${NC}"
        echo "Run './scripts/dev.sh logs' to view API logs"
        ;;
    start)
        start_services "${@:2}"
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        start_services "${@:2}"
        ;;
    reset)
        reset_environment
        ;;
    test)
        run_tests
        ;;
    logs)
        show_logs "${2:-api}"
        ;;
    shell)
        SERVICE=${2:-api}
        docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" exec "$SERVICE" /bin/bash
        ;;
    psql)
        docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" exec postgres psql -U valinor valinor_metadata
        ;;
    redis-cli)
        docker-compose -f "$PROJECT_ROOT/docker-compose.dev.yml" exec redis redis-cli
        ;;
    help)
        echo "Usage: ./scripts/dev.sh [command]"
        echo ""
        echo "Commands:"
        echo "  setup              Initial setup (default)"
        echo "  start [--with-frontend] [--with-demo]  Start services"
        echo "  stop               Stop all services"
        echo "  restart            Restart services"
        echo "  reset              Reset environment (deletes data)"
        echo "  test               Run tests"
        echo "  logs [service]     Show logs (default: api)"
        echo "  shell [service]    Open shell in service container"
        echo "  psql               Open PostgreSQL console"
        echo "  redis-cli          Open Redis CLI"
        echo "  help               Show this help"
        ;;
    *)
        print_error "Unknown command: $1"
        ;;
esac