import asyncio
import base64
import json
from pathlib import Path

from playwright.async_api import async_playwright


PROFILE_DIR = Path("bac_profile")
OUT_FILE = Path("bac_capture") / "storage_state.json"


async def main() -> None:
    OUT_FILE.parent.mkdir(exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1365, "height": 900},
        )
        await context.storage_state(path=str(OUT_FILE))
        await context.close()

    raw = OUT_FILE.read_text(encoding="utf-8")
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")

    print(f"Saved: {OUT_FILE.resolve()}")
    print()
    print("Set this Railway variable:")
    print()
    print("BAC_STORAGE_STATE_B64=" + encoded)


if __name__ == "__main__":
    asyncio.run(main())
