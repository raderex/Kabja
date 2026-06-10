#!/bin/bash
# ════════════════════════════════════════════════════════════════════════════
#  KTM Bus Tracker — Free Hosting Setup (Cloudflare Tunnel)
#  
#  This script automates the setup of Cloudflare Tunnel for free public hosting.
#  No credit card, no servers, completely free!
#
#  Usage:
#    chmod +x scripts/setup_cloudflare_tunnel.sh
#    ./scripts/setup_cloudflare_tunnel.sh
# ════════════════════════════════════════════════════════════════════════════

set -e

# Colors
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

print_header "KTM Bus Tracker — Free Hosting Setup"

# Check if cloudflared is installed
echo ""
echo "Checking for cloudflared..."

if ! command -v cloudflared &> /dev/null; then
    print_error "cloudflared is not installed"
    echo ""
    echo "Install cloudflared:"
    echo ""
    echo "  macOS:"
    echo "    brew install cloudflare/cloudflare/cloudflared"
    echo ""
    echo "  Linux:"
    echo "    curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
    echo "    sudo dpkg -i cloudflared.deb"
    echo ""
    echo "  Windows:"
    echo "    Download from: https://github.com/cloudflare/cloudflared/releases"
    echo ""
    exit 1
fi

print_success "cloudflared found"

# Check Cloudflare account
echo ""
print_step "Checking Cloudflare authentication..."

if ! cloudflared tunnel info > /dev/null 2>&1; then
    print_error "Not authenticated with Cloudflare"
    echo ""
    echo "1. Go to: https://dash.cloudflare.com/sign-up"
    echo "2. Create FREE account"
    echo "3. Then run:"
    echo "   cloudflared tunnel login"
    echo ""
    exit 1
fi

print_success "Authenticated with Cloudflare"

# Check if tunnel exists
echo ""
print_step "Checking for existing tunnel..."

TUNNEL_NAME="bustrack"
TUNNEL_EXISTS=$(cloudflared tunnel list 2>/dev/null | grep -c "$TUNNEL_NAME" || echo "0")

if [ "$TUNNEL_EXISTS" -eq 0 ]; then
    print_step "Creating new tunnel: $TUNNEL_NAME"
    cloudflared tunnel create "$TUNNEL_NAME"
    print_success "Tunnel created!"
else
    print_success "Tunnel already exists"
fi

# Get tunnel info
echo ""
print_step "Getting tunnel URL..."

TUNNEL_ID=$(cloudflared tunnel info --output json | jq -r '.id // empty' 2>/dev/null || cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
TUNNEL_URL=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $(NF-1)}')

if [ -z "$TUNNEL_URL" ]; then
    # Fallback: construct URL
    TUNNEL_URL="bustrack-${TUNNEL_ID:0:7}.trycloudflare.com"
fi

print_success "Tunnel URL: $TUNNEL_URL"

# Create config file
echo ""
print_step "Creating cloudflared config..."

CONFIG_DIR="$HOME/.cloudflared"
CONFIG_FILE="$CONFIG_DIR/config.yml"

if [ ! -d "$CONFIG_DIR" ]; then
    mkdir -p "$CONFIG_DIR"
fi

# Find credentials file
CREDS_FILE="$CONFIG_DIR/${TUNNEL_NAME}.json"

cat > "$CONFIG_FILE" << EOF
tunnel: $TUNNEL_NAME
credentials-file: $CREDS_FILE

ingress:
  - service: http://localhost:8000
    
http2Origin: true
loglevel: info
EOF

print_success "Config created at $CONFIG_FILE"

# Update .env with tunnel URL
echo ""
print_step "Updating .env with tunnel URL..."

if [ -f ".env" ]; then
    # Check if PUBLIC_URL exists
    if grep -q "^PUBLIC_URL=" .env; then
        # Update existing
        sed -i.bak "s|^PUBLIC_URL=.*|PUBLIC_URL=https://$TUNNEL_URL|" .env
        rm -f .env.bak
    else
        # Add new
        echo "PUBLIC_URL=https://$TUNNEL_URL" >> .env
    fi
    print_success ".env updated"
else
    print_error ".env not found. Creating from template..."
    cp .env.example .env
    echo "PUBLIC_URL=https://$TUNNEL_URL" >> .env
    print_success ".env created"
fi

# Summary
echo ""
print_header "Setup Complete!"

echo ""
echo -e "${GREEN}Your public URL:${NC}"
echo "  https://$TUNNEL_URL"
echo ""

echo -e "${GREEN}Next steps:${NC}"
echo ""
echo "1. Update Flutter config:"
echo "   flutter/lib/core/config/app_config.dart"
echo "   static const String baseUrl = 'https://$TUNNEL_URL';"
echo ""

echo "2. Start backend (Terminal 1):"
echo "   docker-compose up -d"
echo ""

echo "3. Start tunnel (Terminal 2):"
echo "   cloudflared tunnel run bustrack"
echo ""

echo "4. Register Telegram webhook:"
echo "   python backend/telegram_bot.py register"
echo ""

echo "5. Start Flutter app (Terminal 3):"
echo "   cd flutter && flutter run"
echo ""

echo -e "${GREEN}On your phone:${NC}"
echo "  • Install Flutter app"
echo "  • Test login with Chat ID"
echo "  • Test GPS tracking on the move!"
echo ""

echo "Keep terminal 2 (tunnel) running while testing!"
echo ""
