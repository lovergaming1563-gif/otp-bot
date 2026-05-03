"""
Run this ONCE to generate a Pyrogram session string.
Then add the output as SESSION_STRING environment variable.

Usage:  python generate_session.py
"""
import asyncio


async def main():
    try:
        from pyrogram import Client
    except ImportError:
        print("Install pyrogram first: pip install pyrogram tgcrypto")
        return

    api_id = int(input("API ID: ").strip())
    api_hash = input("API Hash: ").strip()

    async with Client(
        "gen_session",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    ) as app:
        session_string = await app.export_session_string()

    print("\n" + "=" * 60)
    print("SESSION_STRING (copy this entire value):")
    print(session_string)
    print("=" * 60)
    print("\nAdd this as SESSION_STRING in your environment variables.")


if __name__ == "__main__":
    asyncio.run(main())
