#!/usr/bin/env python3
"""
Test Telegram OTP Integration
═════════════════════════════════

Test script to verify the Telegram OTP authentication flow.

Usage:
    python test_otp.py <base_url> <chat_id>
    
Example:
    python test_otp.py http://localhost:8000 123456789
"""

import asyncio
import json
import sys
from typing import Any

import httpx


class OTPTester:
    def __init__(self, base_url: str, chat_id: str):
        self.base_url = base_url.rstrip("/")
        self.chat_id = chat_id
        self.otp_code: str | None = None

    async def test_health(self) -> bool:
        """Check if backend is running"""
        print("🔍 Testing backend health...")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/health", timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  ✅ Backend: {data.get('status')}")
                    print(f"     Version: {data.get('version')}")
                    print(f"     Redis: {data.get('redis')}")
                    return True
                else:
                    print(f"  ❌ Backend returned {resp.status_code}")
                    return False
        except Exception as e:
            print(f"  ❌ Connection error: {e}")
            return False

    async def test_telegram_deeplink(self) -> str | None:
        """Get Telegram bot deep link"""
        print("\n📱 Getting Telegram bot deep link...")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/api/auth/telegram/deeplink",
                    timeout=5.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    url = data.get("url")
                    bot = data.get("bot")
                    print(f"  ✅ Bot: @{bot}")
                    print(f"     Link: {url}")
                    return url
                else:
                    print(f"  ❌ Failed: {resp.status_code}")
                    print(f"     {resp.text}")
                    return None
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return None

    async def test_otp_request(self) -> bool:
        """Request OTP for the given chat_id"""
        print(f"\n📧 Requesting OTP for chat_id={self.chat_id}...")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/api/auth/otp/request",
                    json={
                        "username": "testuser",
                        "identifier": self.chat_id,
                        "role": "parent"
                    },
                    timeout=5.0
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  ✅ OTP sent successfully")
                    print(f"     Status: {data.get('status')}")
                    print(f"     Hint: {data.get('hint')}")
                    return True
                elif resp.status_code == 429:
                    print(f"  ⚠️  Rate limited")
                    print(f"     Try again in 60 seconds")
                    return False
                else:
                    print(f"  ❌ Failed: {resp.status_code}")
                    print(f"     {resp.text}")
                    return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False

    async def test_otp_verify(self, code: str) -> bool:
        """Verify the OTP code"""
        print(f"\n✔️  Verifying OTP code: {code}...")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/api/auth/otp/verify",
                    json={
                        "username": "testuser",
                        "identifier": self.chat_id,
                        "code": code,
                        "role": "parent"
                    },
                    timeout=5.0
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    token = data.get("access_token")
                    print(f"  ✅ OTP verified successfully!")
                    print(f"     Token type: {data.get('token_type')}")
                    print(f"     Token: {token[:50]}..." if token else "None")
                    self._print_token_info(token)
                    return True
                elif resp.status_code == 401:
                    print(f"  ❌ Invalid OTP code")
                    return False
                else:
                    print(f"  ❌ Failed: {resp.status_code}")
                    print(f"     {resp.text}")
                    return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False

    def _print_token_info(self, token: str) -> None:
        """Decode and display JWT token info"""
        try:
            import base64
            
            parts = token.split(".")
            if len(parts) != 3:
                return
            
            # Add padding if needed
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            
            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)
            
            print(f"\n     Token claims:")
            print(f"       • sub: {claims.get('sub')}")
            print(f"       • role: {claims.get('role')}")
            print(f"       • exp: {claims.get('exp')}")
            if 'allowed_routes' in claims:
                print(f"       • allowed_routes: {claims.get('allowed_routes')}")
            if 'assigned_bus' in claims:
                print(f"       • assigned_bus: {claims.get('assigned_bus')}")
                print(f"       • assigned_route: {claims.get('assigned_route')}")
        except Exception:
            pass

    async def run_interactive(self) -> None:
        """Run interactive test flow"""
        print("\n" + "="*60)
        print("KTM Bus Tracker — Telegram OTP Integration Tester")
        print("="*60)

        # Step 1: Health check
        if not await self.test_health():
            print("\n❌ Backend is not accessible. Aborting.")
            return

        # Step 2: Get deep link
        await self.test_telegram_deeplink()

        # Step 3: Request OTP
        if not await self.test_otp_request():
            print("\n⚠️  Could not request OTP. Check error above.")
            return

        print("\n" + "-"*60)
        print("📝 OTP has been sent to your Telegram chat!")
        print("    Go to Telegram and open the bot to see the code.")
        print("-"*60)

        # Step 4: Get code from user
        code = input("\n🔐 Enter the 6-digit OTP code: ").strip()

        if len(code) != 6 or not code.isdigit():
            print("❌ Invalid code format. Must be 6 digits.")
            return

        # Step 5: Verify OTP
        success = await self.test_otp_verify(code)

        if success:
            print("\n" + "="*60)
            print("✅ All tests passed! Telegram OTP is working!")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("❌ OTP verification failed. Check your code and try again.")
            print("="*60)


async def main() -> None:
    """Main entry point"""
    if len(sys.argv) < 3:
        print("Usage: python test_otp.py <base_url> <chat_id>")
        print("\nExample:")
        print("  python test_otp.py http://localhost:8000 123456789")
        print("\nWhere:")
        print("  base_url: Your backend URL (e.g., http://localhost:8000)")
        print("  chat_id:  Your Telegram chat ID (get from @userinfobot)")
        sys.exit(1)

    base_url = sys.argv[1]
    chat_id = sys.argv[2]

    tester = OTPTester(base_url, chat_id)
    await tester.run_interactive()


if __name__ == "__main__":
    asyncio.run(main())
