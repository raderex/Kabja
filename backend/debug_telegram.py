#!/usr/bin/env python3
"""Quick Telegram OTP debug script — run this on your machine."""
import urllib.request
import json
import sys

BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"  # <-- REPLACE WITH YOUR BOT TOKEN
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def call(method, data=None):
    url = f"{API}/{method}"
    if data:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(url)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

print("=" * 60)
print("  TELEGRAM BOT DEBUGGER")
print("=" * 60)

# 1. Check bot identity
print("\n[1] Checking bot identity (getMe)...")
me = call("getMe")
if me.get("ok"):
    bot = me["result"]
    print(f"    ✅ Bot: @{bot['username']} (ID: {bot['id']})")
else:
    print(f"    ❌ FAILED: {me}")
    print("    → Bot token is INVALID. Get a new one from @BotFather")
    sys.exit(1)

# 2. Check webhook
print("\n[2] Checking webhook (getWebhookInfo)...")
wh = call("getWebhookInfo")
if wh.get("ok"):
    info = wh["result"]
    url = info.get("url", "")
    print(f"    URL:              {url or '(none — no webhook set!)'}")
    print(f"    Pending updates:  {info.get('pending_update_count', 0)}")
    print(f"    Last error:       {info.get('last_error_message', 'none')}")
    print(f"    Last error date:  {info.get('last_error_date', 'none')}")
    if not url:
        print("    ⚠️  No webhook registered! The backend needs to call setWebhook.")
    elif "trycloudflare" in url:
        print(f"    ⚠️  Webhook points to a cloudflare tunnel URL.")
        print(f"       Make sure this URL is still active!")
else:
    print(f"    ❌ FAILED: {wh}")

# 3. Try sending a test message
if len(sys.argv) > 1:
    chat_id = sys.argv[1]
    print(f"\n[3] Sending test message to chat_id={chat_id}...")
    result = call("sendMessage", {
        "chat_id": chat_id,
        "text": "🧪 Test from BusTrack debugger — if you see this, OTP delivery will work!",
    })
    if result.get("ok"):
        print(f"    ✅ Message sent successfully!")
    else:
        err = result.get("description", result.get("error", "unknown"))
        print(f"    ❌ FAILED: {err}")
        if "chat not found" in str(err).lower():
            print("    → You need to /start the bot first! Open t.me/sajabusbot and send /start")
        elif "bot was blocked" in str(err).lower():
            print("    → You blocked the bot. Unblock it in Telegram.")
else:
    print("\n[3] Skipped test message (run with chat_id: python3 debug_telegram.py YOUR_CHAT_ID)")

print("\n" + "=" * 60)
