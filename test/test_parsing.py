"""
Test phần logic thuần (không gọi mạng thật tới Lazada/Telegram):
  - curl_parser: parse 1 mẫu lệnh curl giả lập
  - url_resolver: trích URL từ text, bỏ tracking param, resolve redirect
    (mock requests, không gọi mạng thật)

Chạy: python -m unittest discover -s tests -v
(từ thư mục gốc project, sau khi đã pip install -r requirements.txt)
"""
import unittest
from unittest.mock import MagicMock, patch

import requests

from curl_parser import CurlParseError, parse_curl, parse_session_input
from url_resolver import extract_url, resolve_final_url, strip_tracking_params

SAMPLE_CURL = r"""curl 'https://acs-m.lazada.vn/h5/mtop.lazada.cheetah.aff.shortlink.create/1.0/?appKey=24677475&t=1717000000000&sign=abcdef0123456789abcdef0123456789' \
  -H 'accept: application/json' \
  -H 'accept-language: vi,en-US;q=0.9,en;q=0.8' \
  -H 'cache-control: no-cache' \
  -b 'lzd_cid=xyz; _m_h5_tk=faketoken123456789_1717000000000; _m_h5_tk_enc=deadbeef; other=1' \
  -H 'content-type: application/x-www-form-urlencoded' \
  -H 'origin: https://pages.lazada.vn' \
  -H 'referer: https://pages.lazada.vn/' \
  -H 'user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Test/1.0' \
  -H 'sec-ch-ua: "Not.A/Brand";v="8", "Chromium";v="125"' \
  -H 'x-ua: 216#fake-fingerprint' \
  -H 'x-umidtoken: T2fakeumidtoken' \
  --data-raw 'data=%7B%22payload%22...'"""


class TestCurlParser(unittest.TestCase):
    def test_parse_curl_extracts_cookie_and_headers(self):
        session = parse_curl(SAMPLE_CURL)
        self.assertIn("_m_h5_tk=faketoken123456789_1717000000000", session.cookie)
        self.assertEqual(session.user_agent, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Test/1.0")
        # header nested-quote (sec-ch-ua) phải được tách đúng, không vỡ chuỗi
        self.assertEqual(
            session.extra_headers.get("sec-ch-ua"),
            '"Not.A/Brand";v="8", "Chromium";v="125"',
        )
        self.assertEqual(session.extra_headers.get("x-ua"), "216#fake-fingerprint")
        self.assertEqual(session.extra_headers.get("x-umidtoken"), "T2fakeumidtoken")
        # các header đã được create_shortlink() tự set không nên lặp lại ở extra_headers
        for h in ("accept", "origin", "referer", "user-agent", "cookie", "content-type"):
            self.assertNotIn(h, session.extra_headers)

    def test_token_extraction_from_parsed_session(self):
        session = parse_curl(SAMPLE_CURL)
        self.assertEqual(session.token(), "faketoken123456789")

    def test_missing_cookie_raises(self):
        bad_curl = "curl 'https://example.com' -H 'accept: application/json'"
        with self.assertRaises(CurlParseError):
            parse_curl(bad_curl)

    def test_parse_session_input_accepts_raw_cookie_fallback(self):
        raw_cookie = "_m_h5_tk=rawcookie123_1717000000000; _m_h5_tk_enc=zzz"
        session = parse_session_input(raw_cookie)
        self.assertEqual(session.cookie, raw_cookie)
        self.assertEqual(session.extra_headers, {})

    def test_parse_session_input_rejects_garbage(self):
        with self.assertRaises(CurlParseError):
            parse_session_input("xin chao ban dep trai")

    def test_parse_curl_rejects_cmd_style_with_helpful_message(self):
        cmd_style = (
            'curl "https://acs-m.lazada.vn/h5/x/1.0/?jsv=2.4.11^&appKey=24677475^&t=123" ^\n'
            '  -H "accept: application/json" ^\n'
            '  -H "cookie: _m_h5_tk=abc_123"'
        )
        with self.assertRaises(CurlParseError) as ctx:
            parse_curl(cmd_style)
        self.assertIn("bash", str(ctx.exception))

    def test_parse_session_input_also_rejects_cmd_style(self):
        cmd_style = 'curl "https://x.com?a=1^&b=2" ^\n  -H "cookie: _m_h5_tk=abc_123"'
        with self.assertRaises(CurlParseError):
            parse_session_input(cmd_style)


class TestUrlResolver(unittest.TestCase):
    def test_extract_url_from_plain_link(self):
        self.assertEqual(
            extract_url("https://s.lazada.vn/s.abcdef"), "https://s.lazada.vn/s.abcdef"
        )

    def test_extract_url_from_sentence_with_trailing_punctuation(self):
        text = "xem giúp mình sản phẩm này https://s.lazada.vn/s.abcdef. cảm ơn nha"
        self.assertEqual(extract_url(text), "https://s.lazada.vn/s.abcdef")

    def test_extract_url_returns_none_when_absent(self):
        self.assertIsNone(extract_url("không có link nào ở đây cả"))

    def test_strip_tracking_params_removes_known_keys_keeps_others(self):
        url = "https://www.lazada.vn/products/x-i123-s456.html?utm_source=fb&spm=abc&keepme=1"
        result = strip_tracking_params(url)
        self.assertIn("keepme=1", result)
        self.assertNotIn("utm_source", result)
        self.assertNotIn("spm=", result)

    @patch("url_resolver.requests.head")
    def test_resolve_final_url_uses_head_when_it_succeeds(self, mock_head):
        mock_resp = MagicMock(status_code=200, url="https://www.lazada.vn/final-product.html")
        mock_head.return_value = mock_resp
        result = resolve_final_url("https://s.lazada.vn/s.abcdef")
        self.assertEqual(result, "https://www.lazada.vn/final-product.html")

    @patch("url_resolver.requests.get")
    @patch(
        "url_resolver.requests.head",
        side_effect=requests.exceptions.RequestException("HEAD not supported"),
    )
    def test_resolve_final_url_falls_back_to_get(self, mock_head, mock_get):
        mock_resp = MagicMock(status_code=200, url="https://www.lazada.vn/final-product.html")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_resp
        result = resolve_final_url("https://s.lazada.vn/s.abcdef")
        self.assertEqual(result, "https://www.lazada.vn/final-product.html")


if __name__ == "__main__":
    unittest.main()
