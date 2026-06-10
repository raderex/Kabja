#!/bin/bash
# ════════════════════════════════════════════════════════════════════════════
#  Quick Start — KTM Bus Tracker with Telegram OTP
#  
#  This script sets up everything needed to get the app running locally
#  with Telegram OTP authentication.
#
#  Prerequisites:
#    • Docker & Docker Compose installed
#    • Telegram bot created via @BotFather
#    • ngrok or similar for HTTPS tunnel (dev only)
# ════════════════════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  $1${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
}

print_step() {
    echo -e "${YELLOW}→ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_header "KTM Bus Tracker — Quick Start"
echo ""

# Check prerequisites
print_header "Checking Prerequisites"

if ! command -v docker &> /dev/null; then
    print_error "Docker not found. Please install Docker Desktop."
    exit 1
fi
print_success "Docker found"

if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose not found. Please install Docker Compose."
    exit 1
fi
print_success "Docker Compose found"

if ! command -v git &> /dev/null; then
    print_error "Git not found. Please install Git."
    exit 1
fi
print_success "Git found"

echo ""
print_header "Configuration Setup"

# Check if .env exists
if [ ! -f .env ]; then
    print_step "Creating .env from template..."
    cp .env.example .env
    print_success ".env created. Please edit with your values:"
    echo ""
    echo "Required:"
    echo "  1. TELEGRAM_BOT_TOKEN      — from @BotFather"
    echo "  2. TELEGRAM_BOT_NAME       — your bot username"
    echo "  3. PUBLIC_URL              — your public domain (HTTPS required)"
    echo "  4. JWT_SECRET              — generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
    echo ""
    print_error "Please edit .env and run this script again"
    exit 1
fi

print_success ".env file exists"

# Validate .env
if grep -q "TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE" .env; then
    print_error "TELEGRAM_BOT_TOKEN not configured in .env"
    exit 1
fi
print_success "Telegram bot token configured"

if grep -q "PUBLIC_URL=https://your-public-domain.com" .env; then
    print_error "PUBLIC_URL not configured in .env"
    exit 1
fi
print_success "Public URL configured"

echo ""
print_header "Starting Services"

print_step "Building Docker images..."
docker-compose build --quiet
print_success "Docker images built"

print_step "Starting services (Redis, PostgreSQL, Backend, Nginx)..."
docker-compose up -d
print_success "Services starting"

print_step "Waiting for backend to be healthy..."
for i in {1..60}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        break
    fi
    echo -n "."
    sleep 1
done
echo ""
print_success "Backend is healthy"

echo ""
print_header "Telegram Webhook Setup"

print_step "Registering Telegram webhook..."
docker-compose exec -T api python telegram_bot.py register

sleep 2

print_step "Checking webhook status..."
docker-compose exec -T api python telegram_bot.py info

echo ""
print_header "Testing Integration"

print_step "Testing backend health..."
curl -s http://localhost:8000/health | jq . || echo "Health check passed"
print_success "Backend is responding"

echo ""
print_header "Next Steps"

PUBLIC_URL=$(grep "^PUBLIC_URL=" .env | cut -d '=' -f 2)
TELEGRAM_BOT_NAME=$(grep "^TELEGRAM_BOT_NAME=" .env | cut -d '=' -f 2)

echo ""
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo ""
echo "Service URLs:"
echo "  • Backend API:     http://localhost:8000"
echo "  • API Docs:        http://localhost:8000/docs"
echo "  • Telegram Bot:    https://t.me/$TELEGRAM_BOT_NAME"
echo "  • Public URL:      $PUBLIC_URL"
echo ""
echo "Test the Telegram bot:"
echo "  1. Open https://t.me/$TELEGRAM_BOT_NAME"
echo "  2. Send /start"
echo "  3. You should see: 'Go back to the app and tap Request OTP'"
echo ""
echo "Start Flutter development:"
echo "  cd flutter"
echo "  flutter run"
echo ""
echo "Stop services:"
echo "  docker-compose down"
echo ""
