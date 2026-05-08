import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from playwright.async_api import async_playwright


DEFAULT_URL = "https://f1686s.com/home/embedded"
OUT_DIR = Path("bac_capture")
PROFILE_DIR = Path("bac_profile")
EVENTS_FILE = OUT_DIR / "events.jsonl"
ROAD_FILE = OUT_DIR / "road_store.json"


HOOK_JS = r"""
(() => {
  if (window.__BAC_CAPTURE_INSTALLED__) return;
  window.__BAC_CAPTURE_INSTALLED__ = true;

  const NativeWS = window.__NativeWS || window.WebSocket;
  window.__NativeWS = NativeWS;

  const resultName = w =>
    w === 1 ? "BANKER" :
    w === 2 ? "PLAYER" :
    w === 3 ? "TIE" :
    w === -1 ? "DEALING" :
    `UNKNOWN_${w}`;

  const decode = async data => {
    let text =
      typeof data === "string" ? data :
      data instanceof Blob ? await data.text() :
      data instanceof ArrayBuffer ? new TextDecoder().decode(data) :
      String(data || "");
    const i = text.indexOf("{");
    return i >= 0 ? text.slice(i) : text;
  };

  const emit = payload => {
    payload.href = location.href;
    payload.ts = Date.now();
    if (window.bacEmit) window.bacEmit(payload);
  };

  window.WebSocket = function(...args) {
    const ws = new NativeWS(...args);
    emit({ kind: "ws_open", url: String(args[0] || "") });

    ws.addEventListener("message", async e => {
      try {
        const text = await decode(e.data);
        if (!text || !text.includes("{")) return;

        const data = JSON.parse(text);

        if (data.roadInfo) {
          emit({ kind: "road", roadInfo: data.roadInfo });
        }

        const m = data.message || data;
        if (m && "winner" in m) {
          emit({
            kind: "game",
            tableID: m.tableID,
            gameShoe: m.gameShoe,
            gameRound: m.gameRound,
            eventType: m.eventType,
            winner: m.winner,
            result: resultName(m.winner),
            message: m
          });
        }
      } catch (_) {}
    });

    return ws;
  };

  Object.assign(window.WebSocket, NativeWS);
  window.WebSocket.prototype = NativeWS.prototype;

  emit({ kind: "hook_installed" });
})();
"""


def load_road_store() -> dict:
    if not ROAD_FILE.exists():
        return {}
    try:
        return json.loads(ROAD_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_road_store(store: dict) -> None:
    ROAD_FILE.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def first_visible(locator):
    count = await locator.count()
    for i in range(count):
        item = locator.nth(i)
        try:
            if await item.is_visible(timeout=500):
                return item
        except Exception:
            pass
    return None


async def try_auto_login(page, username: str | None, password: str | None) -> bool:
    if not username or not password:
        return False

    print("Trying auto-login.")
    for frame in [page.main_frame]:
        try:
            login_button = frame.get_by_text("Đăng Nhập", exact=True).first
            if await login_button.count() and await login_button.is_visible():
                await login_button.click(timeout=3000)
                await page.wait_for_timeout(5000)
                break
        except Exception:
            pass
    try:
        if not await page.locator("input[placeholder*='Mật'], input[placeholder*='mật']").count():
            await page.mouse.click(488, 288)
            await page.wait_for_timeout(5000)
    except Exception:
        pass

    for frame in [page.main_frame]:
        try:
            pass_input = await first_visible(
                frame.locator(
                    "input[type='password'], input[placeholder*='Mật'], input[placeholder*='mật'], "
                    "input[placeholder*='pass' i]"
                )
            )

            user_input = await first_visible(
                frame.locator(
                    "input[type='text'], input[type='tel'], input[type='email'], "
                    "input:not([type]), input[placeholder*='tài' i], input[placeholder*='user' i], "
                    "input[placeholder*='phone' i], input[placeholder*='account' i]"
                )
            )
            if not user_input or not pass_input:
                visible_inputs = []
                inputs = frame.locator("input:not([type='checkbox']):not([type='hidden'])")
                for i in range(await inputs.count()):
                    item = inputs.nth(i)
                    try:
                        if await item.is_visible(timeout=500):
                            visible_inputs.append(item)
                    except Exception:
                        pass
                if len(visible_inputs) >= 2:
                    user_input = visible_inputs[0]
                    pass_input = visible_inputs[1]
                else:
                    continue

            await user_input.fill(username)
            await pass_input.fill(password)
            print("Filled login form.")

            await page.mouse.click(683, 455)
            print("Submitted login form.")
            warned_captcha = False
            for _ in range(120):
                await page.wait_for_timeout(1000)
                try:
                    text = await page.locator("body").inner_text(timeout=1000)
                except Exception:
                    text = ""
                if "Trượt để hoàn thành" in text and not warned_captcha:
                    print("Captcha slider is waiting. Please solve it in the browser window.")
                    warned_captcha = True
                if "Đăng Nhập" not in text and "ĐĂNG NHẬP" not in text:
                    print("Login appears complete.")
                    return True
                if "Nạp Tiền" in text or "Rút Tiền" in text or "Số dư" in text:
                    print("Login appears complete.")
                    return True
            return False
        except Exception:
            continue

    return False


async def try_enter_table(page, table_text: str) -> bool:
    table_name = "Baccarat C08" if table_text == "1008" else str(table_text)

    async def save_debug(name: str) -> None:
        try:
            await page.screenshot(path=str(OUT_DIR / name), full_page=False)
        except Exception:
            pass

    # Clear the birthday/promo dialog. Coordinates are more reliable here than
    # text because the page is often rendered with mixed encodings.
    await page.mouse.click(310, 101)
    await page.wait_for_timeout(1200)

    # Home page card position for CASINO SEXY in a 1365x900 viewport.
    await page.mouse.click(613, 430)
    print("Clicked CASINO SEXY/home casino area.")
    await page.wait_for_timeout(6000)
    await save_debug("after_casino_click.png")

    # If we are on the provider game list, search the exact target table.
    try:
        await page.mouse.click(575, 91)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("C08" if table_text == "1008" else table_name)
        await page.wait_for_timeout(2500)
        await save_debug("after_table_search.png")
    except Exception:
        pass

    for frame in page.frames:
        try:
            target = frame.get_by_text(table_name, exact=True).first
            if await target.count() and await target.is_visible(timeout=800):
                await target.click(timeout=3000)
                print(f"Clicked table candidate: {table_name}")
                await page.wait_for_timeout(4000)
                if any("singleBacTable.jsp" in frame.url for frame in page.frames):
                    await save_debug("after_table_click.png")
                    return True
        except Exception:
            pass

    # Fallback for the filtered C08 result card.
    await page.mouse.click(615, 216)
    await page.wait_for_timeout(500)
    await page.mouse.click(615, 216)
    print(f"Clicked table coordinate fallback: {table_name}")
    await page.wait_for_timeout(12000)
    await save_debug("after_table_click.png")

    if any("singleBacTable.jsp" in frame.url for frame in page.frames):
        print(f"Entered table view for {table_name}.")
        return True

    # Clear common post-login promotional dialogs if they appear.
    for label in ["Hủy Bỏ", "Đóng", "Xác Nhận"]:
        try:
            btn = page.get_by_text(label, exact=True).first
            if await btn.count() and await btn.is_visible(timeout=500):
                await btn.click(timeout=1000)
                await page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    # Enter the live casino provider first; table cards are loaded after this.
    for label in ["CASINO SEXY", "SEXY", "Casino Sexy"]:
        try:
            target = page.get_by_text(label, exact=True).first
            if await target.count() and await target.is_visible(timeout=500):
                await target.click(timeout=2000)
                print(f"Clicked game/provider candidate: {label}")
                await page.wait_for_timeout(10000)
                break
        except Exception:
            pass

    candidates = [
        table_text,
        f"C{int(table_text):02d}" if table_text.isdigit() and int(table_text) < 100 else table_text,
    ]
    if table_text == "1008":
        candidates.extend(["C08", "08"])

    for frame in page.frames:
        for text in dict.fromkeys(candidates):
            try:
                target = frame.get_by_text(text, exact=True).first
                if await target.count() and await target.is_visible():
                    await target.click(timeout=2000)
                    print(f"Clicked table candidate: {text}")
                    await page.wait_for_timeout(6000)
                    return True
            except Exception:
                pass
    return False


async def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Baccarat websocket results and roadInfo.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--profile",
        default=str(PROFILE_DIR),
        help="Persistent browser profile directory. Keeps login/session cookies.",
    )
    parser.add_argument("--username", default=os.environ.get("BAC_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("BAC_PASSWORD"))
    parser.add_argument("--table", default=os.environ.get("BAC_TABLE", "1008"))
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    Path(args.profile).mkdir(exist_ok=True)
    road_store = load_road_store()

    async with async_playwright() as p:
        async def bac_emit(source, payload):
            nonlocal road_store

            record = dict(payload)
            record["receivedAt"] = int(time.time() * 1000)

            with EVENTS_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            if record.get("kind") == "road":
                road = record.get("roadInfo") or {}
                table_id = str(road.get("tableID") or "unknown")
                road_store[table_id] = road
                save_road_store(road_store)

                counts = road.get("winCounts") or []
                banker = counts[0] if len(counts) > 0 else None
                player = counts[1] if len(counts) > 1 else None
                tie = counts[2] if len(counts) > 2 else None
                total = counts[17] if len(counts) > 17 else None
                print(
                    f"ROAD table={table_id} shoe={road.get('gameShoe')} round={road.get('gameRound')} "
                    f"B={banker} P={player} T={tie} total={total}"
                )

            elif record.get("kind") == "game" and record.get("winner") != -1:
                print(
                    f"RESULT table={record.get('tableID')} {record.get('result')} "
                    f"winner={record.get('winner')} shoe={record.get('gameShoe')} round={record.get('gameRound')}"
                )

            elif record.get("kind") == "ws_open":
                print(f"WS {record.get('url')}")

        context = await p.chromium.launch_persistent_context(
            user_data_dir=args.profile,
            headless=args.headless,
            viewport={"width": 1365, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        await page.expose_binding("bacEmit", bac_emit)
        await context.add_init_script(HOOK_JS)

        print(f"Opening {args.url}")
        print(f"Events: {EVENTS_FILE.resolve()}")
        print(f"Road store: {ROAD_FILE.resolve()}")
        print("Log in and enter the baccarat table. Press Ctrl+C here to stop.")

        await page.goto(args.url, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        if args.username and args.password:
            await page.goto("https://f1686s.com/home/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            logged = await try_auto_login(page, args.username, args.password)
            if not logged:
                print("Could not find a login form automatically. Browser stays open for manual login.")
            else:
                await page.goto(args.url, wait_until="domcontentloaded")
                await page.wait_for_timeout(6000)

        for _ in range(6):
            entered = await try_enter_table(page, str(args.table))
            if entered:
                break
            await page.wait_for_timeout(5000)

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
