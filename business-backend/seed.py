import asyncio
import os
import sys

# Ensure python can find the 'app' module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.session import async_session_factory
from app.auth.user_service import UserService
from app.models.user import UserRole

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@warehouse.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

async def seed():
    if not ADMIN_PASSWORD:
        print("ADMIN_PASSWORD not set, skipping seed.")
        return
    print("Seeding database...")
    async with async_session_factory() as session:
        service = UserService(session)
        try:
            user = await service.register(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                password=ADMIN_PASSWORD,
                role=UserRole.ADMIN
            )
            await session.commit()
            print(f"Success: Created user '{user.username}' (role={user.role.value})")
        except Exception as e:
            await session.rollback()
            if "already exists" in str(e):
                print(f"Default user '{ADMIN_USERNAME}' already exists.")
            else:
                print(f"Error seeding user: {e}")

if __name__ == "__main__":
    asyncio.run(seed())
