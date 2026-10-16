"""Demo: run two mock consoles locally so the GUI has something to mirror.

mock-A on 127.0.0.1:10023, mock-B on 127.0.0.1:10024.
Both auto-move a random fader every ~2s (simulates a user at the desk).
"""
import asyncio

from x32mirror.simulator import MockX32


async def main():
    a = MockX32("mock-A", "127.0.0.1", 10023)
    b = MockX32("mock-B", "127.0.0.1", 10024)
    await asyncio.gather(
        a.start(), b.start(),
        a.auto_move(2.0), b.auto_move(2.5),
    )


if __name__ == "__main__":
    asyncio.run(main())
