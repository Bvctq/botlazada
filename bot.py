"""
bot.py

Bot Telegram tạo affiliate shortlink Lazada.

Luồng xử lý khi nhận 1 tin nhắn:
  1. Kiểm tra người gửi có nằm trong ALLOWED_USER_IDS không (mặc định
     KHOÁ hết nếu chưa cấu hình - tránh lộ session Lazada của bạn cho
     người lạ).
  2. "Giải mã" link người dùng gửi: theo redirect + bỏ tracking param
     (url_resolver.resolve_and_normalize) -> masterLink sạch.
  3. Gọi API nội bộ Lazada bằng session đã lưu (lazada_client.create_shortlink)
     để tạo link rút gọn.
  4. Trả kết quả (hoặc lỗi kèm gợi ý xử lý) cho người dùng.

Lệnh hỗ trợ:
  /start, /help   - hướng dẫn dùng bot
  /setsession     - dán curl (khuyên dùng) hoặc cookie để (re)auth với Lazada
  /status         - xem trạng thái session hiện tại
  /cancel         - huỷ thao tác /setsession đang chờ dán nội dung

Cú pháp tạo link:
  Gửi thẳng 1 link Lazada bất kỳ  -> bot tự tìm link trong tin nhắn, không sub_id.
  "<link> <sub_id1> <sub_id2> <sub_id3>" (link ở ĐẦU tin nhắn) -> có kèm sub_id.
"""
from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from curl_parser import SESSION_HELP_TEXT, CurlParseError, parse_session_input
from lazada_client import LazadaApiError, LazadaSession, create_shortlink
from session_store import load_session, save_session
from url_resolver import UrlResolveError, resolve_and_normalize

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logger = logging.getLogger("lazada_aff_bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]  # bắt buộc phải có, không đặt default
_owner_env = os.environ.get("ALLOWED_USER_IDS", os.environ.get("OWNER_ID", ""))
ALLOWED_USER_IDS = {int(x) for x in _owner_env.replace(" ", "").split(",") if x}
LAZADA_APP_KEY = os.environ.get("LAZADA_APP_KEY", "24677475")

# state đơn giản trong RAM: những user_id nào đang ở giữa luồng /setsession
# (đã gõ /setsession, bot đang chờ họ dán curl/cookie ở tin nhắn kế tiếp)
_awaiting_session: set[int] = set()

_session: LazadaSession | None = None


def _bootstrap_session() -> None:
    """Nạp session đã lưu trên đĩa; nếu chưa có file lưu nào thì thử nạp
    từ biến môi trường LAZADA_CURL/LAZADA_COOKIE (tiện cho lần deploy đầu)."""
    global _session
    _session = load_session()
    if _session is not None:
        logger.info("Đã nạp session đã lưu từ trước (%s).", os.environ.get(
            "SESSION_FILE", "data/session.json"))
        return
    raw = os.environ.get("LAZADA_CURL") or os.environ.get("LAZADA_COOKIE")
    if raw:
        try:
            _session = parse_session_input(raw, app_key=LAZADA_APP_KEY)
            save_session(_session)
            logger.info("Đã khởi tạo session từ biến môi trường LAZADA_CURL/LAZADA_COOKIE.")
        except CurlParseError as e:
            logger.warning("Không parse được LAZADA_CURL/LAZADA_COOKIE trong env: %s", e)


async def _check_authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ Bot chưa được cấu hình ALLOWED_USER_IDS nên tạm khoá mọi thao "
                "tác để tránh lộ session Lazada của bạn cho người khác.\n"
                "Vào Render -> Environment, đặt ALLOWED_USER_IDS = Telegram user ID "
                "của bạn (số), rồi restart bot."
            )
        return False
    user = update.effective_user
    if not user or user.id not in ALLOWED_USER_IDS:
        if update.effective_message:
            await update.effective_message.reply_text("Bạn không có quyền dùng bot này.")
        logger.warning("Từ chối user không được phép: %s", user.id if user else None)
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_authorized(update):
        return
    await update.effective_message.reply_text(
        "Bot tạo affiliate shortlink Lazada.\n\n"
        "• Gửi 1 link Lazada bất kỳ (link sản phẩm, link rút gọn, link share "
        "từ app...) để bot giải mã + tạo affiliate shortlink.\n"
        "• Muốn gắn sub_id, gửi theo dạng (link phải ở đầu tin nhắn):\n"
        "   <link> <sub_id1> <sub_id2> <sub_id3>\n"
        "• /setsession - nhập/làm mới phiên đăng nhập Lazada\n"
        "• /status - xem trạng thái session hiện tại"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_authorized(update):
        return
    if _session is None or not _session.is_configured():
        await update.effective_message.reply_text(
            "Chưa có session Lazada nào được cấu hình. Dùng /setsession trước."
        )
        return
    masked = f"{_session.cookie[:12]}…({len(_session.cookie)} ký tự)"
    extra = ", ".join(sorted(_session.extra_headers)) or "(không có)"
    await update.effective_message.reply_text(
        "Session hiện tại:\n"
        f"- Cookie: {masked}\n"
        f"- appKey: {_session.app_key}\n"
        f"- Header phụ: {extra}\n\n"
        "Lưu ý: bot không thể tự biết cookie đã hết hạn hay chưa cho tới khi "
        "thử tạo shortlink thật."
    )


async def cmd_setsession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_authorized(update):
        return
    text_after_command = " ".join(context.args) if context.args else ""
    if text_after_command.strip():
        await _try_set_session(update, text_after_command)
        return
    _awaiting_session.add(update.effective_user.id)
    await update.effective_message.reply_text(
        "Dán nguyên lệnh curl (khuyên dùng) hoặc chuỗi cookie vào tin nhắn "
        "tiếp theo. Gửi /cancel để huỷ.\n\n" + SESSION_HELP_TEXT
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        _awaiting_session.discard(update.effective_user.id)
    await update.effective_message.reply_text("Đã huỷ.")


async def _try_set_session(update: Update, raw_text: str) -> None:
    global _session
    try:
        new_session = parse_session_input(raw_text, app_key=LAZADA_APP_KEY)
    except CurlParseError as e:
        await update.effective_message.reply_text(f"❌ {e}")
        return
    _session = new_session
    save_session(_session)
    if update.effective_user:
        _awaiting_session.discard(update.effective_user.id)
    await update.effective_message.reply_text(
        "✅ Đã lưu session mới. Thử gửi 1 link để kiểm tra nhé."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_authorized(update):
        return
    message = update.effective_message
    user_id = update.effective_user.id
    text = (message.text or "").strip()
    if not text:
        return

    if user_id in _awaiting_session:
        await _try_set_session(update, text)
        return

    if _session is None or not _session.is_configured():
        await message.reply_text("Chưa có session Lazada. Dùng /setsession trước khi tạo link.")
        return

    # Nếu tin nhắn bắt đầu bằng link -> cho phép kèm sub_id1/2/3 phía sau.
    # Ngược lại (link nằm giữa câu chữ khác) -> chỉ lấy link, bỏ qua sub_id
    # để tránh nhầm mấy từ trong câu thành sub_id.
    if text.startswith("http"):
        parts = text.split()
        link_part, sub_id_parts = parts[0], parts[1:]
        sub_ids = (sub_id_parts + ["", "", ""])[:3]
    else:
        link_part, sub_ids = text, ["", "", ""]

    try:
        master_link = resolve_and_normalize(link_part)
    except UrlResolveError as e:
        await message.reply_text(f"Không xử lý được link: {e}")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        shortlink = create_shortlink(
            _session,
            master_link=master_link,
            source_url=master_link,
            sub_id1=sub_ids[0],
            sub_id2=sub_ids[1],
            sub_id3=sub_ids[2],
        )
    except LazadaApiError as e:
        msg = str(e)
        hint = ""
        if any(k in msg.lower() for k in ("hết hạn", "session", "token")):
            hint = "\nDùng /setsession để cập nhật phiên đăng nhập mới."
        await message.reply_text(f"❌ Lỗi tạo shortlink: {msg}{hint}")
        return

    await message.reply_text(f"✅ {shortlink}")


def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("setsession", cmd_setsession))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def main() -> None:
    if not ALLOWED_USER_IDS:
        logger.warning(
            "ALLOWED_USER_IDS/OWNER_ID chưa được đặt - bot sẽ từ chối MỌI thao tác "
            "cho tới khi biến này được cấu hình. Xem README để lấy Telegram user ID."
        )
    _bootstrap_session()
    app = build_application()

    mode = os.environ.get("MODE", "polling").lower()
    if mode == "webhook":
        port = int(os.environ.get("PORT", "10000"))
        # Trên Render, RENDER_EXTERNAL_URL được tự cấp cho Web Service - không
        # cần tự tay điền, nhưng vẫn cho phép override qua WEBHOOK_URL.
        base_url = (
            os.environ.get("WEBHOOK_URL")
            or os.environ.get("RENDER_EXTERNAL_URL")
        )
        if not base_url:
            raise RuntimeError(
                "MODE=webhook nhưng không có WEBHOOK_URL lẫn RENDER_EXTERNAL_URL. "
                "Đặt WEBHOOK_URL thủ công (vd https://ten-app.onrender.com)."
            )
        secret = os.environ.get("WEBHOOK_SECRET") or None
        path = "webhook"
        logger.info("Chạy ở chế độ webhook trên port %s, url %s/%s", port, base_url, path)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=path,
            webhook_url=f"{base_url.rstrip('/')}/{path}",
            secret_token=secret,
        )
    else:
        logger.info("Chạy ở chế độ polling.")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
