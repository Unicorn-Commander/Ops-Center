#!/usr/bin/env python3
"""
Create admin account for aaron@magicunicorn.tech in Keycloak uchub realm
"""

import sys
import asyncio
from keycloak_integration import create_user, set_user_password, get_user_by_email

async def main():
    print("🔐 Creating admin account for aaron@magicunicorn.tech...", flush=True)

    try:
        # Check if user exists
        print("Checking if user exists...", flush=True)
        user = await get_user_by_email("aaron@magicunicorn.tech")

        if user:
            print(f"✅ User exists: {user.get('username')}", flush=True)
            user_id = user['id']
        else:
            print("Creating new user...", flush=True)
            user_id = await create_user(
                email="aaron@magicunicorn.tech",
                username="aaron",
                first_name="Aaron",
                last_name="Admin",
                email_verified=True,
                attributes={
                    "role": ["admin"],
                    "org_role": ["owner"],
                    "subscription_tier": ["enterprise"]
                }
            )
            print(f"✅ User created: {user_id}", flush=True)

        # Set password
        print("Setting password...", flush=True)
        success = await set_user_password(user_id, "REMOVED-KEYCLOAK_ADMIN_PASSWORD", temporary=False)

        if success:
            print("\n" + "="*60, flush=True)
            print("🎉 SUCCESS!", flush=True)
            print("="*60, flush=True)
            print("Email: aaron@magicunicorn.tech", flush=True)
            print("Username: aaron", flush=True)
            print("Password: REMOVED-KEYCLOAK_ADMIN_PASSWORD", flush=True)
            print("Role: admin (full access)", flush=True)
            print("Org Role: owner", flush=True)
            print("\n✨ You can now log in at https://unicorncommander.ai", flush=True)
        else:
            print("⚠️  Password may not have been set", flush=True)

    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
