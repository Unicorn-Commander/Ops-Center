#!/usr/bin/env python3
"""
Reset password for aaron@magicunicorn.tech in Keycloak uchub realm
"""

import asyncio
import httpx
import os

KEYCLOAK_URL = "http://uchub-keycloak:8080"
KEYCLOAK_REALM = "uchub"
KEYCLOAK_ADMIN_USER = "admin"
KEYCLOAK_ADMIN_PASSWORD = "REMOVED-KEYCLOAK_ADMIN_PASSWORD"
AARON_USER_ID = "00a665e2-8703-4c06-a6b1-ec25cfcb98ef"
NEW_PASSWORD = "REMOVED-KEYCLOAK_ADMIN_PASSWORD"

async def get_admin_token():
    """Get admin token from Keycloak"""
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.post(
            f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
            data={
                "username": KEYCLOAK_ADMIN_USER,
                "password": KEYCLOAK_ADMIN_PASSWORD,
                "grant_type": "password",
                "client_id": "admin-cli"
            },
            timeout=10.0
        )

        if response.status_code == 200:
            return response.json()["access_token"]
        else:
            print(f"Failed to get token: {response.status_code}")
            print(f"Response: {response.text}")
            return None

async def reset_password(user_id, password, token):
    """Reset user password"""
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.put(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/reset-password",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "type": "password",
                "value": password,
                "temporary": False
            },
            timeout=10.0
        )

        return response.status_code == 204

async def main():
    print("🔐 Resetting password for aaron@magicunicorn.tech...", flush=True)

    # Get admin token
    print("Getting admin token...", flush=True)
    token = await get_admin_token()

    if not token:
        print("❌ Failed to authenticate as admin", flush=True)
        return

    print("✅ Admin token obtained", flush=True)

    # Reset password
    print(f"Resetting password to: {NEW_PASSWORD}", flush=True)
    success = await reset_password(AARON_USER_ID, NEW_PASSWORD, token)

    if success:
        print("\n" + "="*60, flush=True)
        print("🎉 PASSWORD RESET SUCCESSFUL!", flush=True)
        print("="*60, flush=True)
        print("Email/Username: aaron@magicunicorn.tech / aaron", flush=True)
        print(f"Password: {NEW_PASSWORD}", flush=True)
        print("Role: Platform Admin (full access)", flush=True)
        print("\n✨ You can now log in at https://unicorncommander.ai", flush=True)
    else:
        print("❌ Failed to reset password", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
