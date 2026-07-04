"""
curl_parser.py

Cho phép người dùng /setsession bằng cách dán nguyên lệnh curl (Chrome/Edge
DevTools -> Network -> chuột phải request tạo shortlink -> Copy -> Copy as
cURL (bash)) để dựng lại LazadaSession, thay vì phải tự bóc cookie bằng tay.
Nhờ vậy giữ được cả các header chống bot (x-ua, x-umidtoken, sec-ch-ua...)
mà endpoint AntiCreep của Lazada có thể yêu cầu.

Cũng hỗ trợ fallback: nếu nội dung dán vào không phải lệnh curl, coi cả
đoạn text là cookie string thô (kém ổn định hơn vì thiếu các header chống
bot, nhưng vẫn dùng được nếu Lazada không đòi hỏi những header đó).

LƯU Ý: module này được viết lại từ đầu vì phần "curl parser" nhắc tới
trong log làm việc trước đó không có trong file bạn gửi. Đã unit-test với
một mẫu curl giả lập kiểu bash (xem tests/test_parsing.py). Lệnh curl copy
ở dạng cmd/PowerShell của Windows (dùng dấu ^ để escape) được CHỦ ĐỘNG
PHÁT HIỆN và từ chối kèm hướng dẫn đổi sang bash, vì cú pháp cmd quá phức
tạp/không nhất quán để parse đúng một cách tổng quát.
"""
from __future__ import annotations

import re
import shlex

from lazada_client import APP_KEY_DEFAULT, DEFAULT_USER_AGENT, LazadaSession

# Dấu hiệu đặc trưng của "Copy as cURL (cmd)"/PowerShell trên Windows: dùng
# ^ để escape (^&, ^", ^%...) hoặc ^ ở cuối dòng để nối dòng. Định dạng này
# KHÔNG dùng được với parser dưới đây (chỉ hiểu cú pháp kiểu bash/POSIX).
_CMD_STYLE_RE = re.compile(r'\^[&"%^<>|]|\^\s*\r?\n')

# Các header mà lazada_client.create_shortlink() đã tự set cứng, hoặc là
# header giả/không liên quan do curl/trình duyệt sinh ra - không đưa vào
# extra_headers để tránh đè/xung đột hoặc rác vô ích.
_HEADERS_HANDLED_ELSEWHERE = {
    "accept", "accept-language", "cache-control", "content-type",
    "content-length", "origin", "referer", "user-agent", "cookie",
    "x-i18n-language", "x-i18n-regionid", "host", "connection",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user",
    "upgrade-insecure-requests", "pragma", "priority", "te",
}


class CurlParseError(Exception):
    pass


def _normalize(raw: str) -> str:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Bỏ line-continuation kiểu bash: dấu \ ở cuối dòng (Copy as cURL nhiều dòng)
    raw = raw.replace("\\\n", " ")
    return raw.strip()


def _parse_headers_and_cookie(tokens: list[str]) -> tuple[dict[str, str], str | None]:
    headers: dict[str, str] = {}
    cookie_from_flag: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-H", "--header") and i + 1 < len(tokens):
            line = tokens[i + 1]
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
            i += 2
            continue
        if tok in ("-b", "--cookie") and i + 1 < len(tokens):
            cookie_from_flag = tokens[i + 1].strip()
            i += 2
            continue
        i += 1
    return headers, cookie_from_flag


def parse_curl(raw_curl: str, app_key: str = APP_KEY_DEFAULT) -> LazadaSession:
    if _CMD_STYLE_RE.search(raw_curl):
        raise CurlParseError(
            "Lệnh này có vẻ được copy ở dạng 'cURL (cmd)' hoặc PowerShell của Windows "
            "(thấy dấu ^ dùng để escape) - dạng đó không parse được. Quay lại DevTools -> "
            "Network -> chuột phải request -> Copy -> chọn đúng 'Copy as cURL (bash)' "
            "(KHÔNG chọn 'Copy as cURL (cmd)'), rồi dán lại. Chrome/Edge luôn có cả 2 lựa "
            "chọn trong menu Copy dù bạn dùng Windows."
        )
    text = _normalize(raw_curl)
    try:
        tokens = shlex.split(text)
    except ValueError as e:
        raise CurlParseError(f"Không parse được lệnh curl (lỗi quote/cú pháp): {e}") from e

    headers, cookie_from_flag = _parse_headers_and_cookie(tokens)
    cookie = cookie_from_flag or headers.get("cookie")
    if not cookie or "_m_h5_tk=" not in cookie:
        raise CurlParseError(
            "Không tìm thấy cookie hợp lệ (_m_h5_tk=...) trong lệnh curl. "
            "Chắc chắn bạn copy đúng request tới acs-m.lazada.vn/.../shortlink.create/ "
            "lúc đã đăng nhập."
        )

    user_agent = headers.get("user-agent", DEFAULT_USER_AGENT)
    extra_headers = {
        k: v for k, v in headers.items() if k not in _HEADERS_HANDLED_ELSEWHERE
    }

    return LazadaSession(
        cookie=cookie,
        app_key=app_key,
        user_agent=user_agent,
        extra_headers=extra_headers,
    )


def parse_session_input(raw_text: str, app_key: str = APP_KEY_DEFAULT) -> LazadaSession:
    """Điểm vào chính cho /setsession: tự nhận diện là lệnh curl hay cookie thô."""
    text = raw_text.strip()
    if not text:
        raise CurlParseError("Chưa dán nội dung nào.")
    if text.lower().startswith("curl"):
        return parse_curl(text, app_key=app_key)
    if "_m_h5_tk=" not in text:
        raise CurlParseError(
            "Không nhận diện được nội dung. Dán nguyên lệnh curl (khuyên dùng, "
            "giữ được đầy đủ header chống bot) hoặc chuỗi cookie có chứa "
            "_m_h5_tk=..."
        )
    return LazadaSession(cookie=text, app_key=app_key)


SESSION_HELP_TEXT = (
    "*Cách lấy session mới:*\n"
    "1. Đăng nhập tài khoản affiliate Lazada trên Chrome/Edge (máy tính).\n"
    "2. Mở trang tạo affiliate shortlink, bấm F12 để mở DevTools -> tab Network.\n"
    "3. Bấm nút \"Tạo shortlink\" trên trang Lazada như bình thường.\n"
    "4. Trong tab Network, tìm request tới "
    "acs-m.lazada.vn/h5/mtop.lazada.cheetah.aff.shortlink.create/...\n"
    "5. Chuột phải request đó -> Copy -> chọn đúng *Copy as cURL (bash)* "
    "(menu có cả 'bash' và 'cmd/PowerShell' dù bạn dùng Windows - PHẢI chọn 'bash', "
    "chọn nhầm 'cmd' sẽ không dùng được).\n"
    "6. Dán nguyên lệnh curl đó vào đây.\n\n"
    "Nếu vẫn lỗi, cách đơn giản hơn (ít ổn định hơn vì thiếu vài header chống bot): "
    "trong tab Network, click vào request đó -> tab Headers -> phần Request Headers -> "
    "tìm dòng \"cookie:\" -> copy riêng phần giá trị (chuỗi dài chứa _m_h5_tk=...) và "
    "dán vào đây.\n\n"
    "Cookie/token sẽ hết hạn sau một thời gian - lặp lại các bước trên để "
    "lấy phiên mới khi bot báo lỗi phiên đăng nhập."
)
