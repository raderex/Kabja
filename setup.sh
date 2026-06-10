#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  KTM School Bus Tracker — Setup & Dependency Check
#  Arch Linux · Uses Python 3.11 explicitly (3.12+ has no asyncpg wheels)
#  Usage: bash setup.sh
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()     { echo -e "${GREEN}  ✓${NC} $*"; }
warn()   { echo -e "${YELLOW}  ⚠${NC}  $*"; }
err()    { echo -e "${RED}  ✗${NC} $*"; }
info()   { echo -e "${CYAN}  →${NC} $*"; }
header() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}"; }

ERRORS=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ═══════════════════════════════════════════════════════════════════════════
header "Finding Python 3.11"
# ═══════════════════════════════════════════════════════════════════════════

# Search for python3.11 in all common locations
PYTHON311=""
for candidate in \
    python3.11 \
    /usr/bin/python3.11 \
    /usr/local/bin/python3.11 \
    /opt/python3.11/bin/python3.11 \
    "$HOME/.pyenv/versions/3.11"*/bin/python3.11 \
    /usr/lib/python3.11/bin/python3.11; do
  if command -v "$candidate" &>/dev/null 2>&1; then
    VER=$("$candidate" --version 2>&1)
    if echo "$VER" | grep -q "3\.11\."; then
      PYTHON311="$candidate"
      ok "Found Python 3.11: $PYTHON311 ($VER)"
      break
    fi
  fi
done

if [[ -z "$PYTHON311" ]]; then
  err "Python 3.11 not found in PATH or common locations"
  echo ""
  echo -e "${YELLOW}  Install Python 3.11 on Arch Linux:${NC}"
  echo "    sudo pacman -S python311"
  echo "    # or via AUR:"
  echo "    yay -S python311"
  echo ""
  echo "  If already installed, find it with:  find / -name 'python3.11' 2>/dev/null"
  echo "  Then re-run: bash setup.sh"
  exit 1
fi

# Confirm version is exactly 3.11.x (not 3.1 or 3.110)
FULL_VER=$("$PYTHON311" --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$FULL_VER" | cut -d. -f1)
MINOR=$(echo "$FULL_VER" | cut -d. -f2)

if [[ "$MAJOR" != "3" || "$MINOR" != "11" ]]; then
  err "$PYTHON311 is version $FULL_VER — need exactly 3.11.x"
  ((ERRORS++))
fi

# ═══════════════════════════════════════════════════════════════════════════
header "Python Virtual Environment (3.11)"
# ═══════════════════════════════════════════════════════════════════════════

VENV_DIR="$SCRIPT_DIR/backend/.venv"

if [[ -d "$VENV_DIR" ]]; then
  VENV_PYTHON_VER=$("$VENV_DIR/bin/python" --version 2>&1 | awk '{print $2}')
  VENV_MINOR=$(echo "$VENV_PYTHON_VER" | cut -d. -f2)
  if [[ "$VENV_MINOR" == "11" ]]; then
    ok "Existing venv is Python 3.11 ($VENV_PYTHON_VER) — keeping it"
  else
    warn "Existing venv is Python $VENV_PYTHON_VER (not 3.11) — recreating..."
    rm -rf "$VENV_DIR"
    "$PYTHON311" -m venv "$VENV_DIR"
    ok "Venv recreated with Python 3.11"
  fi
else
  info "Creating venv with Python 3.11 at $VENV_DIR"
  "$PYTHON311" -m venv "$VENV_DIR"
  ok "Venv created"
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Confirm the venv python is actually 3.11
CONFIRM_VER=$("$VENV_PY" --version 2>&1)
ok "Venv python: $CONFIRM_VER"

# ═══════════════════════════════════════════════════════════════════════════
header "Installing Python Dependencies"
# ═══════════════════════════════════════════════════════════════════════════

info "Upgrading pip..."
"$VENV_PIP" install --quiet --upgrade pip
ok "pip upgraded: $("$VENV_PIP" --version)"

info "Installing from requirements.txt (all pre-built wheels — no compilation)..."
"$VENV_PIP" install \
    --no-cache-dir \
    --only-binary=:all: \
    -r "$SCRIPT_DIR/backend/requirements.txt" \
  && ok "All packages installed via pre-built wheels" \
  || {
    warn "Pre-built wheels failed for some packages — trying with compilation allowed..."
    "$VENV_PIP" install \
        --no-cache-dir \
        -r "$SCRIPT_DIR/backend/requirements.txt" \
      && ok "Packages installed (with compilation)" \
      || { err "pip install failed — see output above"; ((ERRORS++)); }
  }

# ── Validate imports ───────────────────────────────────────────────────────
info "Validating Python imports..."
FAILED_IMPORTS=()
for mod in fastapi uvicorn redis httpx jose pydantic asyncpg; do
  if "$VENV_PY" -c "import $mod" 2>/dev/null; then
    VER=$("$VENV_PIP" show "$mod" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    ok "  import $mod  ($VER)"
  else
    err "  import $mod FAILED"
    FAILED_IMPORTS+=("$mod")
    ((ERRORS++))
  fi
done

if [[ ${#FAILED_IMPORTS[@]} -gt 0 ]]; then
  echo ""
  warn "Failed imports: ${FAILED_IMPORTS[*]}"
  warn "Try installing manually:"
  echo "    $VENV_PIP install ${FAILED_IMPORTS[*]}"
fi

# ── services/__init__.py ───────────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/backend/services/__init__.py" ]]; then
  err "backend/services/__init__.py missing — creating now"
  echo "# makes services a Python package" > "$SCRIPT_DIR/backend/services/__init__.py"
fi
ok "services/__init__.py exists"

# ── Syntax check all .py files ─────────────────────────────────────────────
info "Syntax checking Python files..."
SYNTAX_ERRORS=0
for pyfile in \
    "$SCRIPT_DIR/backend/main.py" \
    "$SCRIPT_DIR/backend/services/otp_gateway.py" \
    "$SCRIPT_DIR/backend/services/geofence.py" \
    "$SCRIPT_DIR/backend/services/trip_logger.py"; do
  if [[ ! -f "$pyfile" ]]; then
    err "  $(basename "$pyfile") — FILE MISSING"
    ((SYNTAX_ERRORS++)); ((ERRORS++))
    continue
  fi
  if "$VENV_PY" -m py_compile "$pyfile" 2>/dev/null; then
    ok "  $(basename "$pyfile")"
  else
    err "  $(basename "$pyfile") — SYNTAX ERROR:"
    "$VENV_PY" -m py_compile "$pyfile" 2>&1 | sed 's/^/    /'
    ((SYNTAX_ERRORS++)); ((ERRORS++))
  fi
done

# ═══════════════════════════════════════════════════════════════════════════
header "Docker"
# ═══════════════════════════════════════════════════════════════════════════

if command -v docker &>/dev/null; then
  DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
  ok "Docker $DOCKER_VER"
else
  err "Docker not found"
  info "Install: sudo pacman -S docker && sudo systemctl enable --now docker"
  ((ERRORS++))
fi

if systemctl is-active --quiet docker 2>/dev/null; then
  ok "Docker daemon running"
else
  warn "Docker daemon not running — starting..."
  sudo systemctl start docker \
    && ok "Docker started" \
    || { err "Could not start Docker"; ((ERRORS++)); }
fi

if docker compose version &>/dev/null 2>&1; then
  ok "docker compose plugin: $(docker compose version --short 2>/dev/null)"
else
  err "docker compose plugin not found"
  info "Install: sudo pacman -S docker-compose"
  ((ERRORS++))
fi

if groups "$USER" | grep -q docker 2>/dev/null; then
  ok "User '$USER' is in docker group"
else
  warn "User '$USER' not in docker group — adding (need re-login)..."
  sudo usermod -aG docker "$USER"
  warn "Run 'newgrp docker' or log out/in before using docker without sudo"
fi

# ═══════════════════════════════════════════════════════════════════════════
header "Environment File (.env)"
# ═══════════════════════════════════════════════════════════════════════════

ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  err ".env missing — creating from .env.example"
  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
  warn "Edit .env before running docker compose up:"
  warn "  JWT_SECRET     → python3.11 -c \"import secrets; print(secrets.token_hex(32))\""
  warn "  REDIS_PASSWORD → any strong password"
  warn "  POSTGRES_PASSWORD → any strong password"
  warn "  TELEGRAM_BOT_TOKEN → from @BotFather on Telegram"
  ((ERRORS++))
else
  ok ".env exists"
  check_var() {
    local val
    val=$(grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"')
    if [[ -z "$val" ]] || echo "$val" | grep -qi "CHANGE_ME"; then
      warn "  $1 not set — edit .env"
    else
      ok "  $1 is set"
    fi
  }
  check_var JWT_SECRET
  check_var REDIS_PASSWORD
  check_var POSTGRES_PASSWORD
  check_var PUBLIC_URL
  check_var TELEGRAM_BOT_TOKEN
fi

# ═══════════════════════════════════════════════════════════════════════════
header "OSRM Data"
# ═══════════════════════════════════════════════════════════════════════════

OSRM_DIR="$SCRIPT_DIR/osrm_data"
mkdir -p "$OSRM_DIR"

if compgen -G "$OSRM_DIR/*.osrm" > /dev/null 2>&1; then
  ok "OSRM processed data found — routing ready"
elif compgen -G "$OSRM_DIR/*.osm.pbf" > /dev/null 2>&1; then
  warn "PBF file found but not processed yet. Run:"
  echo ""
  echo "    docker run --rm -t -v \$(pwd)/osrm_data:/data \\"
  echo "      ghcr.io/project-osrm/osrm-backend:v5.27.1 \\"
  echo "      osrm-extract -p /opt/car.lua /data/nepal-latest.osm.pbf"
  echo ""
  echo "    docker run --rm -t -v \$(pwd)/osrm_data:/data \\"
  echo "      ghcr.io/project-osrm/osrm-backend:v5.27.1 \\"
  echo "      osrm-partition /data/nepal-latest.osrm"
  echo ""
  echo "    docker run --rm -t -v \$(pwd)/osrm_data:/data \\"
  echo "      ghcr.io/project-osrm/osrm-backend:v5.27.1 \\"
  echo "      osrm-customize /data/nepal-latest.osrm"
else
  warn "No OSM data yet"
  read -rp "  Download nepal-latest.osm.pbf now? (~110MB) [y/N]: " DL
  if [[ "$DL" =~ ^[Yy]$ ]]; then
    wget -q --show-progress \
      "https://download.geofabrik.de/asia/nepal-latest.osm.pbf" \
      -O "$OSRM_DIR/nepal-latest.osm.pbf" \
      && ok "Downloaded — run the 3 osrm-extract commands above" \
      || { err "Download failed"; ((ERRORS++)); }
  else
    warn "ETA routing won't work without OSRM data (rest of the app still runs)"
  fi
fi

# ═══════════════════════════════════════════════════════════════════════════
header "Project File Check"
# ═══════════════════════════════════════════════════════════════════════════

REQUIRED=(
  "docker-compose.yml"
  ".env"
  "backend/main.py"
  "backend/Dockerfile"
  "backend/requirements.txt"
  "backend/services/__init__.py"
  "backend/services/otp_gateway.py"
  "backend/services/geofence.py"
  "backend/services/trip_logger.py"
  "nginx/nginx.conf"
  "nginx/static/privacy.html"
  "nginx/static/support.html"
  "flutter/pubspec.yaml"
  "flutter/lib/main.dart"
  "flutter/lib/core/auth/auth_provider.dart"
  "flutter/lib/core/config/app_config.dart"
  "flutter/lib/core/network/dio_client.dart"
  "flutter/lib/core/network/ws_resilience_manager.dart"
  "flutter/lib/features/auth/login_screen.dart"
  "flutter/lib/features/auth/telegram_auth_screen.dart"
  "flutter/lib/features/home/home_screen.dart"
  "flutter/lib/features/driver/driver_screen.dart"
  "flutter/lib/features/tracking/tracking_screen.dart"
  "flutter/lib/features/tracking/bus_marker_animator.dart"
  "flutter/ios/Runner/Info.plist"
  "flutter/android/app/build.gradle"
  "flutter/android/app/src/main/AndroidManifest.xml"
)

for f in "${REQUIRED[@]}"; do
  if [[ -f "$SCRIPT_DIR/$f" ]]; then
    ok "  $f"
  else
    err "  $f — MISSING"
    ((ERRORS++))
  fi
done

# ═══════════════════════════════════════════════════════════════════════════
header "Summary"
# ═══════════════════════════════════════════════════════════════════════════

echo ""
if [[ "$ERRORS" -eq 0 ]]; then
  echo -e "${GREEN}${BOLD}  ✓ All checks passed — ready to launch!${NC}"
  echo ""
  echo -e "${BOLD}  Quick start:${NC}"
  echo ""
  echo "  # 1. Launch the stack"
  echo "  docker compose up -d"
  echo ""
  echo "  # 2. Seed demo data (replace TOKEN with an admin JWT)"
  echo "  curl -X POST https://localhost:8000/api/admin/seed \\"
  echo "    -H 'Authorization: Bearer \$ADMIN_TOKEN'"
  echo ""
  echo "  # 3. Check health"
  echo "  curl http://localhost:8000/health"
  echo ""
  echo "  # 4. Build Flutter"
  echo "  cd flutter && flutter pub get"
  echo "  flutter build apk --debug   # quick test build"
else
  echo -e "${RED}${BOLD}  ✗ $ERRORS issue(s) to fix before starting${NC}"
  echo ""
  echo "  Fix the errors above then re-run: bash setup.sh"
fi
echo ""
