"""Test KB-driven lobby entry with same account."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Vision gateway credentials are read from the environment (see .env.example)

from qa_interactive import InteractiveAgent

GAME_URL = os.environ.get("GAME_URL", "")
LOGIN_ID = os.environ.get("LOGIN_ID", "")


async def main():
    agent = InteractiveAgent(
        game_url=GAME_URL,
        game_name="example_game",
        login_id=LOGIN_ID,
        headless=False,
    )
    try:
        await agent.run()
    except Exception as e:
        print(f"[FATAL] {e}", flush=True)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
