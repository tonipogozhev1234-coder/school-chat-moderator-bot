"""
Точка входа (совместимость с хостингами, запускающими main.py).
"""

import asyncio
from bot import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
