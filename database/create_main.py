import asyncio

from database.config.conection import create_tables


if __name__ == '__main__':
    asyncio.run(create_tables())
