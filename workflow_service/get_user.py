import asyncio
from app.database import AsyncSessionLocal
from sqlalchemy import text

async def get_user():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text('SELECT id, email FROM users LIMIT 1'))
        row = result.fetchone()
        if row:
            print(f'User ID: {row[0]}')
            print(f'Email: {row[1]}')
        else:
            print('No users found')

asyncio.run(get_user())
