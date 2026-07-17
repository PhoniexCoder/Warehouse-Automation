import asyncio
import os
import sys

# Ensure python can find the 'app' module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.session import async_session_factory
from app.auth.user_service import UserService
from app.models.user import UserRole

async def seed():
    print("Seeding database...")
    async with async_session_factory() as session:
        service = UserService(session)
        try:
            user = await service.register(
                username="admin",
                email="admin@warehouse.com",
                password="admin",
                role=UserRole.ADMIN
            )
            await session.commit()
            print(f"Success: Created user '{user.username}' (role={user.role.value}) with password 'admin'")
        except Exception as e:
            await session.rollback()
            if "already exists" in str(e):
                print("Default user 'admin' already exists.")
            else:
                print(f"Error seeding user: {e}")

if __name__ == "__main__":
    asyncio.run(seed())
