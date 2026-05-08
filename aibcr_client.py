import os
from typing import Any

import requests


AIBCR_URL = os.environ.get("AIBCR_URL", "https://aibcr.me/baccarat/getnewresult")


def _headers() -> dict[str, str]:
    if not os.environ.get("AIBCR_CSRF_TOKEN"):
        try:
            import bcr  # type: ignore

            return dict(bcr.HEADERS)
        except Exception:
            pass

    csrf = os.environ.get("AIBCR_CSRF_TOKEN", "")
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://aibcr.me",
        "referer": "https://aibcr.me/ae/lobby",
        "user-agent": os.environ.get(
            "AIBCR_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        ),
        "x-requested-with": "XMLHttpRequest",
    }
    if csrf:
        headers["x-csrf-token"] = csrf
    return headers


def _cookies() -> dict[str, str]:
    if not os.environ.get("AIBCR_XSRF_TOKEN") and not os.environ.get("AIBCR_LARAVEL_SESSION"):
        try:
            import bcr  # type: ignore

            return dict(bcr.COOKIES)
        except Exception:
            pass

    cookies: dict[str, str] = {}
    xsrf = os.environ.get("AIBCR_XSRF_TOKEN", "")
    session = os.environ.get("AIBCR_LARAVEL_SESSION", "")
    if xsrf:
        cookies["XSRF-TOKEN"] = xsrf
    if session:
        cookies["laravel_session"] = session
    return cookies


def result_to_columns(result: str) -> list[list[str]]:
    columns: list[list[str]] = []
    current_col: list[str] = []
    last_bp: str | None = None

    for ch in result:
        if ch == "T":
            continue
        if ch not in ("B", "P"):
            continue

        if last_bp is None:
            current_col.append(ch)
            last_bp = ch
        elif ch == last_bp:
            current_col.append(ch)
        else:
            columns.append(current_col)
            current_col = [ch]
            last_bp = ch

    if current_col:
        columns.append(current_col)

    return columns


def compute_derived_road(columns: list[list[str]], look_back: int) -> list[dict[str, Any]]:
    road: list[dict[str, Any]] = []
    grid_col = 0

    for col_idx, col in enumerate(columns):
        if col_idx < look_back:
            continue

        grid_row = 0
        for row_idx, _ in enumerate(col):
            if row_idx == 0:
                prev_col_len = len(columns[col_idx - 1]) if col_idx - 1 >= 0 else 0
                ref_col_idx = col_idx - 1 - look_back
                ref_col_len = len(columns[ref_col_idx]) if ref_col_idx >= 0 else 0
                color = "red" if prev_col_len == ref_col_len else "blue"
            else:
                ref_col_idx = col_idx - look_back
                ref_row_idx = row_idx - 1
                color = (
                    "red"
                    if ref_col_idx >= 0 and ref_row_idx < len(columns[ref_col_idx])
                    else "blue"
                )

            road.append({"col": grid_col, "row": grid_row, "color": color})
            grid_row += 1

        grid_col += 1

    return road


def compute_all_roads(result: str) -> dict[str, Any]:
    columns = result_to_columns(result)
    return {
        "columns": columns,
        "big_eye_boy": compute_derived_road(columns, look_back=1),
        "small_road": compute_derived_road(columns, look_back=2),
        "cockroach_pig": compute_derived_road(columns, look_back=3),
    }


def fetch_results(table: str = "all") -> dict[str, Any]:
    response = requests.post(
        AIBCR_URL,
        headers=_headers(),
        cookies=_cookies(),
        data={"table": table},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def build_roads(
    game_code: str | None = None,
    table_id: str | None = None,
    table: str = "all",
) -> list[dict[str, Any]]:
    data = fetch_results(table=table)
    tables = data.get("data", [])
    result_list: list[dict[str, Any]] = []

    for item in tables:
        gc = str(item.get("game_code", ""))
        tid = str(item.get("table_id", ""))
        result = str(item.get("result", ""))

        if game_code and gc != game_code:
            continue
        if table_id and tid != table_id:
            continue
        if not result:
            continue

        roads = compute_all_roads(result)
        result_list.append(
            {
                "game_code": gc,
                "table_id": tid,
                "table_name": item.get("table_name", ""),
                "result": result,
                "goodRoad": item.get("goodRoad", ""),
                **roads,
            }
        )

    return result_list
