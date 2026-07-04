"""
session_store.py

Lưu LazadaSession bằng 1 file JSON đơn giản, để phiên đăng nhập không mất
khi tiến trình bot restart giữa chừng (crash, deploy lại cùng 1 instance...).

KHÔNG đảm bảo sống sót qua một lần "deploy lại" (redeploy) trên Render nếu
dùng đĩa mặc định - đĩa đó bị xoá/khởi tạo lại giữa các lần deploy. Muốn
bền hơn:
  - gắn thêm Render Persistent Disk và trỏ SESSION_FILE vào đường dẫn
    trong đĩa đó, hoặc
  - đơn giản là /setsession lại sau mỗi lần deploy/redeploy (cookie vốn
    cũng hết hạn định kỳ nên việc này không tránh được hoàn toàn).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from lazada_client import APP_KEY_DEFAULT, DEFAULT_USER_AGENT, LazadaSession

SESSION_FILE = Path(os.environ.get("SESSION_FILE", "data/session.json"))


def save_session(session: LazadaSession) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cookie": session.cookie,
        "app_key": session.app_key,
        "user_agent": session.user_agent,
        "extra_headers": session.extra_headers,
    }
    tmp = SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SESSION_FILE)


def load_session() -> LazadaSession | None:
    if not SESSION_FILE.exists():
        return None
    try:
        payload = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return LazadaSession(
        cookie=payload.get("cookie", ""),
        app_key=payload.get("app_key", APP_KEY_DEFAULT),
        user_agent=payload.get("user_agent", DEFAULT_USER_AGENT),
        extra_headers=payload.get("extra_headers") or {},
    )


def clear_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
