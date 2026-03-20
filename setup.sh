#!/bin/bash
#
# Valinor SaaS v2 - Complete Setup Script
# Sets up the entire development environment
#

set -e

echo "================================================"
echo "   Valinor SaaS v2 - Development Setup"
echo "================================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo -e "\n${YELLOW}Checking prerequisites...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Python 3 found: $(python3 --version)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}Node.js is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Node.js found: $(node --version)"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker found: $(docker --version)"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo -e "${YELLOW}Docker Compose not found, checking docker compose command...${NC}"
    if docker compose version &> /dev/null; then
        echo -e "${GREEN}✓${NC} Docker Compose found (docker compose)"
        DOCKER_COMPOSE="docker compose"
    else
        echo -e "${RED}Docker Compose is not installed${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Docker Compose found: $(docker-compose --version)"
    DOCKER_COMPOSE="docker-compose"
fi

# Create directories
echo -e "\n${YELLOW}Creating directory structure...${NC}"
mkdir -p ssh_keys logs temp deploy/sql
echo -e "${GREEN}✓${NC} Directories created"

# Setup Python virtual environment
echo -e "\n${YELLOW}Setting up Python environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi

# Activate venv
source venv/bin/activate

# Install Python dependencies
echo -e "\n${YELLOW}Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt
echo -e "${GREEN}✓${NC} Python dependencies installed"

# Setup Node.js dependencies
echo -e "\n${YELLOW}Installing Node.js dependencies...${NC}"
cd web
npm install
cd ..
echo -e "${GREEN}✓${NC} Node.js dependencies installed"

# Create .env file if not exists
if [ ! -f ".env" ]; then
    echo -e "\n${YELLOW}Creating .env file...${NC}"
    cat > .env << EOL
# Valinor SaaS Environment Configuration
# Generated: $(date)

# LLM Provider Configuration
LLM_PROVIDER=anthropic_api
ANTHROPIC_API_KEY=your-api-key-here

# Alternative: Console Auth (no API costs)
# LLM_PROVIDER=console_auth
# CLAUDE_USERNAME=your-email
# CLAUDE_PASSWORD=your-password

# Database Configuration (will be set by Gloria setup)
DB_TYPE=postgresql
DB_HOST=localhost
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=

# SSH Tunnel (will be set by Gloria setup)
SSH_HOST=
SSH_PORT=22
SSH_USER=
SSH_KEY_PATH=

# Redis
REDIS_URL=redis://localhost:6379

# Security
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

# Development
DEBUG=true
LOG_LEVEL=INFO
EOL
    echo -e "${GREEN}✓${NC} .env file created"
    echo -e "${YELLOW}  ⚠️  Please update your API keys in .env${NC}"
fi

# Create SQL initialization script
echo -e "\n${YELLOW}Creating database initialization script...${NC}"
cat > deploy/sql/init.sql << 'EOL'
-- Valinor SaaS Database Schema
-- Metadata storage only - no client data

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Clients table
CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Analyses table
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES clients(id),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reports table
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id),
    type VARCHAR(50) NOT NULL,
    title VARCHAR(255),
    content TEXT,
    file_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES clients(id),
    action VARCHAR(100) NOT NULL,
    details JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_analyses_client_id ON analyses(client_id);
CREATE INDEX idx_analyses_status ON analyses(status);
CREATE INDEX idx_reports_analysis_id ON reports(analysis_id);
CREATE INDEX idx_audit_log_client_id ON audit_log(client_id);
EOL
echo -e "${GREEN}✓${NC} Database schema created"

# Setup Docker networks
echo -e "\n${YELLOW}Setting up Docker network...${NC}"
docker network create valinor-network 2>/dev/null || true
echo -e "${GREEN}✓${NC} Docker network ready"

# Function to check if services are ready
check_services() {
    echo -e "\n${YELLOW}Checking service health...${NC}"
    
    # Check Redis
    if docker exec valinor-saas-redis-1 redis-cli ping &>/dev/null; then
        echo -e "${GREEN}✓${NC} Redis is healthy"
    else
        echo -e "${RED}✗${NC} Redis is not responding"
    fi
    
    # Check PostgreSQL
    if docker exec valinor-saas-postgres-1 pg_isready &>/dev/null; then
        echo -e "${GREEN}✓${NC} PostgreSQL is healthy"
    else
        echo -e "${RED}✗${NC} PostgreSQL is not responding"
    fi
    
    # Check API
    if curl -s http://localhost:8000/health &>/dev/null; then
        echo -e "${GREEN}✓${NC} API is healthy"
    else
        echo -e "${RED}✗${NC} API is not responding"
    fi
    
    # Check Frontend
    if curl -s http://localhost:3000 &>/dev/null; then
        echo -e "${GREEN}✓${NC} Frontend is healthy"
    else
        echo -e "${RED}✗${NC} Frontend is not responding"
    fi
}

# Main menu
echo -e "\n${YELLOW}Setup Options:${NC}"
echo "1. Start all services (Docker Compose)"
echo "2. Setup Gloria's database connection"
echo "3. Run tests"
echo "4. Stop all services"
echo "5. Clean everything (reset)"
echo "6. Exit"

read -p "Select option [1]: " option
option=${option:-1}

case $option in
    1)
        echo -e "\n${YELLOW}Starting all services...${NC}"
        $DOCKER_COMPOSE up -d
        echo -e "${GREEN}✓${NC} Services started"
        
        echo -e "\n${YELLOW}Waiting for services to be ready...${NC}"
        sleep 10
        
        check_services
        
        echo -e "\n${GREEN}================================================${NC}"
        echo -e "${GREEN}   Valinor SaaS is ready!${NC}"
        echo -e "${GREEN}================================================${NC}"
        echo ""
        echo "🌐 Frontend: http://localhost:3000"
        echo "📡 API Docs: http://localhost:8000/docs"
        echo "🗄️ Adminer: http://localhost:8080"
        echo ""
        echo "Next steps:"
        echo "1. Configure Gloria's database: ./setup.sh (option 2)"
        echo "2. Add your ANTHROPIC_API_KEY to .env"
        echo "3. Visit http://localhost:3000 to start"
        ;;
        
    2)
        echo -e "\n${YELLOW}Setting up Gloria's database connection...${NC}"
        python3 scripts/setup_gloria_connection.py
        ;;
        
    3)
        echo -e "\n${YELLOW}Running tests...${NC}"
        python3 -m pytest tests/ -v
        python3 test_provider_switch.py
        ;;
        
    4)
        echo -e "\n${YELLOW}Stopping all services...${NC}"
        $DOCKER_COMPOSE down
        echo -e "${GREEN}✓${NC} Services stopped"
        ;;
        
    5)
        echo -e "\n${RED}⚠️  This will delete all data and containers${NC}"
        read -p "Are you sure? (y/N): " confirm
        if [ "$confirm" = "y" ]; then
            $DOCKER_COMPOSE down -v
            rm -rf venv node_modules web/node_modules web/.next
            echo -e "${GREEN}✓${NC} Everything cleaned"
        fi
        ;;
        
    6)
        echo "Exiting..."
        exit 0
        ;;
        
    *)
        echo -e "${RED}Invalid option${NC}"
        exit 1
        ;;
esac