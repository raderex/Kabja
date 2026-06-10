#!/bin/bash
# ════════════════════════════════════════════════════════════════════════════
#  KTM Bus Tracker — Startup Script with Telegram Webhook Registration
#  
#  This script is called after Docker Compose services are healthy.
#  It automatically registers the Telegram webhook if configured.
#
#  Usage:
#    chmod +x scripts/startup.sh
#    ./scripts/startup.sh
# ════════════════════════════════════════════════════════════════════════════

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  KTM Bus Tracker — Startup Script                         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"

# Wait for backend to be ready
echo -e "${YELLOW}⏳  Waiting for backend to be healthy...${NC}"
sleep 5

# Check if backend is running
HEALTH_CHECK=0
for i in {1..30}; do
    if curl -f http://localhost:8000/health > /dev/null 2>&1; then
        HEALTH_CHECK=1
        break
    fi
    echo -e "${YELLOW}  Attempt $i/30...${NC}"
    sleep 2
done

if [ $HEALTH_CHECK -eq 0 ]; then
    echo -e "${RED}❌ Backend is not responding. Exiting.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Backend is healthy!${NC}"

# Check if Telegram is configured
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo -e "${YELLOW}⚠️  TELEGRAM_BOT_TOKEN not set. Skipping webhook registration.${NC}"
    echo -e "${YELLOW}   To use Telegram OTP, set environment variables and restart.${NC}"
    exit 0
fi

if [ -z "$PUBLIC_URL" ]; then
    echo -e "${RED}❌ PUBLIC_URL is not set. Cannot register Telegram webhook.${NC}"
    exit 1
fi

# Check if using Telegram provider
if [ "$OTP_PROVIDER" != "telegram" ]; then
    echo -e "${YELLOW}⚠️  OTP_PROVIDER is set to '$OTP_PROVIDER', not 'telegram'. Skipping webhook.${NC}"
    exit 0
fi

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Registering Telegram Webhook                             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"

# Register webhook using the telegram_bot.py script
if command -v docker &> /dev/null; then
    echo -e "${YELLOW}📝 Registering Telegram webhook via Docker...${NC}"
    docker-compose exec -T backend python telegram_bot.py register
    WEBHOOK_RESULT=$?
else
    echo -e "${YELLOW}📝 Registering Telegram webhook directly...${NC}"
    cd backend
    python telegram_bot.py register
    WEBHOOK_RESULT=$?
    cd ..
fi

if [ $WEBHOOK_RESULT -eq 0 ]; then
    echo -e "${GREEN}✅ Telegram webhook registration completed!${NC}"
    sleep 2
    
    # Get webhook info
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  Webhook Status                                            ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    
    if command -v docker &> /dev/null; then
        docker-compose exec -T backend python telegram_bot.py info
    else
        cd backend
        python telegram_bot.py info
        cd ..
    fi
    
    echo -e "${GREEN}✅ Startup complete! Your app is ready.${NC}"
else
    echo -e "${YELLOW}⚠️  Webhook registration had issues. Check logs above.${NC}"
    echo -e "${YELLOW}   The app will still work, but Telegram OTP may be unavailable.${NC}"
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Service URLs                                              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo -e "${GREEN}Backend API:${NC}    http://localhost:8000"
echo -e "${GREEN}Docs:${NC}           http://localhost:8000/docs"
echo -e "${GREEN}Redis:${NC}          localhost:6379"
echo -e "${GREEN}PostgreSQL:${NC}     localhost:5432"
echo -e "${GREEN}OSRM:${NC}           http://localhost:5000"

if [ ! -z "$PUBLIC_URL" ]; then
    echo -e "${GREEN}Public URL:${NC}      $PUBLIC_URL"
    echo -e "${GREEN}Telegram Bot:${NC}    https://t.me/$TELEGRAM_BOT_NAME"
fi

echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Test the backend: curl http://localhost:8000/health"
echo "  2. Start the Flutter app with BASE_URL pointing to your backend"
echo "  3. Test the login flow with Telegram OTP"
echo ""
