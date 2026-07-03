"""
Client gọi API nội bộ (mtop) mà trang "Tạo affiliate shortlink" của Lazada
dùng khi bấm nút "Tạo shortlink". Đây là API không public/không tài liệu
hoá chính thức - được suy ra từ request thật (network tab) của chính tài
khoản affiliate của bạn, nên chỉ hoạt động khi:
  1. cookie/token còn hạn (đăng nhập bằng chính tài khoản của bạn), và
  2. Lazada không thay đổi cấu trúc API này.

Không hardcode cookie/token thật vào code - luôn truyền qua biến môi
trường hoặc lệnh /setsession của bot.
"""
import hashlib
import json
import re
import time
from dataclasses import dataclass, field

import requests

APP_KEY_DEFAULT = "24677475"
API_PATH = "mtop.lazada.cheetah.aff.shortlink.create"
API_URL = f"https://acs-m.lazada.vn/h5/{API_PATH}/1.0/"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

SHORTLINK_IN_RESPONSE_RE = re.compile(r"https://s\.lazada\.vn/[A-Za-z0-9._\-/]+")


class LazadaApiError(Exception):
    """Lazada trả về lỗi (vd token hết hạn) hoặc response không đọc được."""

    def __init__(self, message: str, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class LazadaSession:
    """Toàn bộ thông tin phiên đăng nhập cần để gọi API - refresh định kỳ."""

    cookie: str
    app_key: str = APP_KEY_DEFAULT
    user_agent: str = DEFAULT_USER_AGENT
    extra_headers: dict = field(default_factory=dict)  # x-ua, x-umidtoken, sec-ch-ua...

    def token(self) -> str:
        """Lấy phần token (trước dấu "_") từ cookie _m_h5_tk."""
        m = re.search(r"_m_h5_tk=([^;_]+)", self.cookie)
        if not m:
            raise LazadaApiError(
                "Không tìm thấy cookie _m_h5_tk - cookie có thể bị thiếu hoặc sai định dạng."
            )
        return m.group(1)

    def is_configured(self) -> bool:
        return bool(self.cookie and "_m_h5_tk=" in self.cookie)


def _build_data_string(master_link: str, source_url: str, sub_id1: str, sub_id2: str, sub_id3: str) -> str:
    inner = {
        "masterLink": master_link,
        "sourceUrl": source_url,
        "sub_id1": sub_id1 or "",
        "sub_id2": sub_id2 or "",
        "sub_id3": sub_id3 or "",
    }
    inner_json = json.dumps(inner, separators=(",", ":"), ensure_ascii=False)
    outer = {"payload": inner_json}
    return json.dumps(outer, separators=(",", ":"), ensure_ascii=False)


def _sign(token: str, t: str, app_key: str, data: str) -> str:
    raw = f"{token}&{t}&{app_key}&{data}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _extract_shortlink(response_json) -> str | None:
    """Không rõ tên field chính xác trong response nên tìm theo pattern URL
    (đáng tin cậy hơn vì domain s.lazada.vn/... là cố định), có fallback
    theo vài tên field hay gặp."""
    text = json.dumps(response_json, ensure_ascii=False)
    m = SHORTLINK_IN_RESPONSE_RE.search(text)
    if m:
        return m.group(0)

    data = response_json.get("data") if isinstance(response_json, dict) else None
    if isinstance(data, dict):
        for key in ("shortUrl", "shortLink", "shortenUrl", "url", "link", "affLink"):
            if data.get(key):
                return data[key]
    return None


def create_shortlink(
    session: LazadaSession,
    master_link: str,
    source_url: str,
    sub_id1: str = "",
    sub_id2: str = "",
    sub_id3: str = "",
    timeout: int = 20,
) -> str:
    """Gọi API tạo affiliate shortlink, trả về link rút gọn (s.lazada.vn/...).
    Raise LazadaApiError nếu thất bại."""
    if not session.is_configured():
        raise LazadaApiError("Chưa cấu hình cookie Lazada. Dùng /setsession để thiết lập.")

    data_str = _build_data_string(master_link, source_url, sub_id1, sub_id2, sub_id3)
    t = str(int(time.time() * 1000))
    token = session.token()
    sign = _sign(token, t, session.app_key, data_str)

    params = {
        "jsv": "2.4.11",
        "appKey": session.app_key,
        "t": t,
        "sign": sign,
        "api": API_PATH,
        "v": "1.0",
        "type": "originaljson",
        "isSec": "1",
        "AntiCreep": "true",
        "timeout": str(timeout * 1000),
        "dataType": "json",
        "sessionOption": "AutoLoginOnly",
        "x-i18n-language": "vi",
        "x-i18n-regionID": "VN",
    }

    headers = {
        "accept": "application/json",
        "accept-language": "vi,en-US;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://pages.lazada.vn",
        "referer": "https://pages.lazada.vn/",
        "user-agent": session.user_agent,
        "x-i18n-language": "vi",
        "x-i18n-regionid": "VN",
        "cookie": session.cookie,
    }
    headers.update(session.extra_headers)  # x-ua, x-umidtoken, sec-ch-ua... nếu có

    try:
        resp = requests.post(
            API_URL,
            params=params,
            headers=headers,
            data={"data": data_str},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise LazadaApiError(f"Lỗi kết nối tới Lazada: {e}") from e

    try:
        payload = resp.json()
    except ValueError as e:
        raise LazadaApiError(
            f"Lazada trả về dữ liệu không phải JSON (HTTP {resp.status_code}).",
            raw_response=resp.text[:500],
        ) from e

    ret = payload.get("ret") or []
    ret_str = ret[0] if ret else ""
    if not ret_str.upper().startswith("SUCCESS"):
        hint = ""
        if "TOKEN" in ret_str.upper() or "SESSION" in ret_str.upper():
            hint = " (có thể cookie/token đã hết hạn - dùng /setsession để cập nhật lại.)"
        raise LazadaApiError(f"Lazada từ chối request: {ret_str}{hint}", raw_response=json.dumps(payload, ensure_ascii=False))

    shortlink = _extract_shortlink(payload)
    if not shortlink:
        raise LazadaApiError(
            "Tạo thành công nhưng không tìm thấy link rút gọn trong response.",
            raw_response=json.dumps(payload, ensure_ascii=False)[:800],
        )
    return shortlink
