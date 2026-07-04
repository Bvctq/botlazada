"""
url_resolver.py

"Giải mã" / chuẩn hoá link trước khi đưa vào Lazada aff API làm masterLink:
  1. Trích URL http(s) đầu tiên từ tin nhắn (phòng khi người dùng gõ kèm
     chữ khác quanh link).
  2. Theo dõi redirect HTTP để lấy link đích thật sự - vì link người dùng
     dán vào thường là link rút gọn (s.lazada.vn/...), link share từ app
     (c.lazada.vn/t/...), hoặc link có wrapper/tracking.
  3. Bỏ bớt các query param tracking không cần thiết (utm_*, fbclid,
     gclid, spm, scm, laz_trackid...) để có masterLink gọn gàng.

LƯU Ý: module này được viết lại từ đầu vì phần "URL normalizer" nhắc tới
trong log làm việc trước đó không có trong file bạn gửi. Môi trường build
này cũng không có quyền truy cập mạng tới lazada.vn nên KHÔNG test được
end-to-end với link Lazada thật - đã unit-test phần logic (regex, bỏ
query param) bằng dữ liệu giả lập. Nếu link Lazada thật cho ra định dạng
khác (vd cần giữ lại vài query param cụ thể), chỉnh STRIP_PARAMS bên dưới.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

URL_RE = re.compile(r"https?://[^\s<>\"']+")

# Các query param tracking phổ biến, an toàn để bỏ khỏi masterLink.
STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "gclsrc", "spm", "scm", "laz_trackid", "mkttid",
    "aff_trace_key", "aff_platform", "aff_fsk", "aff_fcid", "aff_fpsk",
}

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
}


class UrlResolveError(Exception):
    pass


def extract_url(text: str) -> str | None:
    """Lấy URL http(s) đầu tiên xuất hiện trong đoạn text tự do, bỏ dấu
    câu dính vào cuối (dấu chấm, phẩy, ngoặc đóng...)."""
    m = URL_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip(").,;!?\u3002")


def strip_tracking_params(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in STRIP_PARAMS
    ]
    new_query = urlencode(kept)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, ""))


def resolve_final_url(url: str, timeout: float = 15.0) -> str:
    """Theo redirect để lấy URL đích cuối cùng.
    Thử HEAD trước (nhẹ hơn), fallback sang GET (stream, không tải hết
    body) nếu server không hỗ trợ HEAD hoặc trả lỗi."""
    try:
        resp = requests.head(
            url, allow_redirects=True, timeout=timeout, headers=_DEFAULT_HEADERS
        )
        if resp.status_code < 400 and resp.url:
            return resp.url
    except requests.RequestException:
        pass

    try:
        with requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers=_DEFAULT_HEADERS,
            stream=True,
        ) as resp:
            return resp.url
    except requests.RequestException as e:
        raise UrlResolveError(f"Không theo được redirect của link: {e}") from e


def resolve_and_normalize(raw_text: str, timeout: float = 15.0) -> str:
    """Hàm chính bot gọi: từ text thô (chỉ chứa URL, hoặc URL kèm câu
    chữ khác) -> masterLink đã resolve + đã bỏ tracking param."""
    url = extract_url(raw_text)
    if not url:
        raise UrlResolveError("Không tìm thấy link http(s) trong tin nhắn.")
    final_url = resolve_final_url(url, timeout=timeout)
    return strip_tracking_params(final_url)
