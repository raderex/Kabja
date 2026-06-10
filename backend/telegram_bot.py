#!/usr/bin/env python3
"""
Telegram Bot Registration & Management Utility
═════════════════════════════════════════════════════════════

Standalone script to register/manage Telegram bot webhook for KTM Bus Tracker.

Features:
  • Register webhook on Telegram servers
  • Delete webhook
  • Get bot info
  • Verify webhook configuration

Usage:
  python telegram_bot.py register    # Set up webhook
  python telegram_bot.py delete      # Remove webhook
  python telegram_bot.py info        # Get bot details
  python telegram_bot.py verify      # Check webhook status

Required env vars:
  TELEGRAM_BOT_TOKEN       — from @BotFather on Telegram
  TELEGRAM_BOT_NAME        — bot username (without @)
  TELEGRAM_WEBHOOK_SECRET  — secret token for security
  PUBLIC_URL               — your public domain (https://example.com)
"""

import asyncio
import os
import sys
from typing import Any

import httpx


class TelegramBotManager:
    """Manage Telegram bot webhook registration."""

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.bot_name = os.getenv("TELEGRAM_BOT_NAME", "KTMBusTrackerBot").strip()
        self.webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        self.public_url = os.getenv("PUBLIC_URL", "https://bustrack.yourdomain.com").strip()
        
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set in environment")
        
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.webhook_url = f"{self.public_url}/api/telegram/webhook"

    async def register_webhook(self) -> dict[str, Any]:
        """Register webhook with Telegram servers."""
        print(f"📝 Registering webhook...")
        print(f"   Bot: @{self.bot_name}")
        print(f"   Webhook URL: {self.webhook_url}")
        
        payload = {
            "url": self.webhook_url,
            "allowed_updates": ["message"],
            "drop_pending_updates": False,
        }
        
        if self.webhook_secret:
            payload["secret_token"] = self.webhook_secret
            print(f"   Secret token: {self.webhook_secret[:8]}***")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.api_url}/setWebhook", json=payload)
            data = resp.json()
            
            if data.get("ok"):
                print("✅ Webhook registered successfully!")
                print(f"   Response: {data}")
                return data
            else:
                print(f"❌ Failed to register webhook!")
                print(f"   Error: {data.get('description', 'Unknown error')}")
                return data

    async def delete_webhook(self) -> dict[str, Any]:
        """Remove webhook from Telegram."""
        print(f"🗑️  Deleting webhook...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.api_url}/deleteWebhook",
                json={"drop_pending_updates": False}
            )
            data = resp.json()
            
            if data.get("ok"):
                print("✅ Webhook deleted!")
                return data
            else:
                print(f"❌ Failed to delete webhook!")
                print(f"   Error: {data.get('description', 'Unknown error')}")
                return data

    async def get_webhook_info(self) -> dict[str, Any]:
        """Get current webhook status."""
        print(f"ℹ️  Fetching webhook info...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.api_url}/getWebhookInfo")
            data = resp.json()
            
            if data.get("ok"):
                result = data.get("result", {})
                print("✅ Webhook info retrieved:")
                print(f"   URL: {result.get('url', 'None')}")
                print(f"   IP: {result.get('ip_address', 'Unknown')}")
                print(f"   Pending updates: {result.get('pending_update_count', 0)}")
                print(f"   Last error: {result.get('last_error_message', 'None')}")
                print(f"   Last error date: {result.get('last_error_date', 'N/A')}")
                return data
            else:
                print(f"❌ Failed to fetch webhook info!")
                print(f"   Error: {data.get('description', 'Unknown error')}")
                return data

    async def get_me(self) -> dict[str, Any]:
        """Get bot info."""
        print(f"🤖 Fetching bot info...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.api_url}/getMe")
            data = resp.json()
            
            if data.get("ok"):
                result = data.get("result", {})
                print("✅ Bot info:")
                print(f"   ID: {result.get('id')}")
                print(f"   Username: @{result.get('username')}")
                print(f"   First name: {result.get('first_name')}")
                print(f"   Can join groups: {result.get('can_join_groups')}")
                print(f"   Can read group messages: {result.get('can_read_group_messages')}")
                print(f"   Supports inline queries: {result.get('supports_inline_queries')}")
                return data
            else:
                print(f"❌ Failed to fetch bot info!")
                print(f"   Error: {data.get('description', 'Unknown error')}")
                return data

    async def test_send_message(self, chat_id: str) -> dict[str, Any]:
        """Send a test message to verify bot is working."""
        print(f"📨 Sending test message to chat {chat_id}...")
        
        test_message = (
            "🚌 *KTM School Bus Tracker Test*\n\n"
            "This is a test message to verify the bot is working correctly.\n"
            "If you see this, the Telegram integration is set up properly!"
        )
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": test_message,
                    "parse_mode": "Markdown",
                }
            )
            data = resp.json()
            
            if data.get("ok"):
                print("✅ Test message sent successfully!")
                return data
            else:
                print(f"❌ Failed to send test message!")
                print(f"   Error: {data.get('description', 'Unknown error')}")
                return data


async def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("❌ Usage: python telegram_bot.py [register|delete|info|me|test]")
        print("\nCommands:")
        print("  register <chat_id>  — Register webhook with Telegram")
        print("  delete              — Remove webhook")
        print("  info                — Show webhook status")
        print("  me                  — Get bot information")
        print("  test <chat_id>      — Send test message to chat_id")
        sys.exit(1)
    
    try:
        manager = TelegramBotManager()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "register":
        await manager.register_webhook()
    elif command == "delete":
        await manager.delete_webhook()
    elif command == "info":
        await manager.get_webhook_info()
    elif command == "me":
        await manager.get_me()
    elif command == "test":
        if len(sys.argv) < 3:
            print("❌ Usage: python telegram_bot.py test <chat_id>")
            sys.exit(1)
        await manager.test_send_message(sys.argv[2])
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
