# ═══════════════════════════════════════════════════════════════════
#  KTM Bus Tracker — Backend Dockerfile
#  Uses python:3.11-slim — all wheels pre-built, zero compilation.
#  DO NOT change to 3.12+ until asyncpg ships wheels for that version.
# ═══════════════════════════════════════════════════════════════════
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install all deps — pre-built wheels only, no gcc/rust needed
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
