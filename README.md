# Lazada Affiliate Shortlink Bot (Telegram)

Bot Telegram cá nhân: gửi 1 link Lazada bất kỳ, bot tự "giải mã" (theo
redirect, bỏ tracking param) để lấy link đích thật, rồi gọi API nội bộ
(mtop) mà chính trang affiliate của Lazada dùng để tạo affiliate
shortlink (`s.lazada.vn/...`), bằng session đăng nhập của chính bạn.

## Cấu trúc project

```
lazada_client.py   API client gọi mtop.lazada.cheetah.aff.shortlink.create
                    (file bạn đã cung cấp - giữ nguyên, đã xác nhận sign khớp)
url_resolver.py     "Giải mã" link: theo redirect + bỏ query param tracking
curl_parser.py      Parse lệnh curl (hoặc cookie thô) dán vào /setsession
session_store.py    Lưu/nạp session bằng file JSON để sống sót qua restart
bot.py              Bot Telegram chính (nối các module trên lại)
tests/test_parsing.py  Test phần logic thuần, không cần mạng thật
requirements.txt
render.yaml         Blueprint deploy Render (mặc định: Web Service free + webhook)
.env.example        Danh sách biến môi trường cần cấu hình
```

> **Phần tôi phải viết lại từ đầu:** file bạn gửi chỉ có `lazada_client.py`.
> Log làm việc trước đó có nhắc tới "URL normalizer" và "curl parser" đã
> làm xong, nhưng không có trong nội dung gửi kèm, nên `url_resolver.py`
> và `curl_parser.py` là tôi viết lại theo đúng mô tả yêu cầu (giải mã link
> trước khi tạo shortlink) và đã unit-test bằng dữ liệu giả lập. Nếu link
> Lazada thật cho kết quả khác 3 ví dụ bạn từng test trước đó, gửi lại ví
> dụ cụ thể để tôi chỉnh cho khớp.

## Cách dùng bot (sau khi đã deploy)

- Gửi thẳng 1 link Lazada bất kỳ (link sản phẩm, link rút gọn `s.lazada.vn/...`,
  link share từ app...) → bot tự tìm, giải mã, tạo shortlink.
- Muốn gắn `sub_id`, gửi **link ở đầu tin nhắn**, theo sau là tối đa 3 sub_id
  cách nhau bằng dấu cách: `<link> <sub_id1> <sub_id2> <sub_id3>`.
- `/setsession` — nhập/làm mới phiên đăng nhập Lazada (xem hướng dẫn bên dưới).
- `/status` — xem trạng thái session hiện tại.
- `/cancel` — huỷ thao tác `/setsession` đang dở.

## 1. Chuẩn bị

### Lấy BOT_TOKEN
Nhắn `/newbot` cho [@BotFather](https://t.me/BotFather) trên Telegram, làm theo hướng dẫn.

### Lấy ALLOWED_USER_IDS (bắt buộc — bảo mật)
Bot **mặc định khoá mọi thao tác** nếu chưa đặt biến này, để tránh người lạ
dùng ké session Lazada của bạn. Nhắn `/start` cho [@userinfobot](https://t.me/userinfobot)
để lấy ID Telegram (dạng số) của chính bạn.

### Lấy session Lazada (dùng cho `/setsession`)
1. Đăng nhập tài khoản affiliate Lazada trên **Chrome/Edge** (máy tính).
2. Mở trang tạo affiliate shortlink, bấm **F12** → tab **Network**.
3. Bấm nút "Tạo shortlink" trên trang Lazada như bình thường.
4. Trong tab Network, tìm request tới
   `acs-m.lazada.vn/h5/mtop.lazada.cheetah.aff.shortlink.create/...`
5. Chuột phải request đó → **Copy** → **Copy as cURL (bash)**.
6. Giữ nguyên, dán vào lệnh `/setsession` của bot (hoặc gõ `/setsession` rồi
   dán vào tin nhắn kế tiếp bot yêu cầu).

Dùng nguyên lệnh curl (thay vì chỉ cookie) sẽ giữ được cả các header chống
bot (`x-ua`, `x-umidtoken`, `sec-ch-ua`...) mà cơ chế `AntiCreep` của Lazada
có thể kiểm tra — ổn định hơn nhiều so với chỉ dán mỗi cookie.

Cookie/token sẽ hết hạn sau một thời gian; hễ bot báo lỗi kiểu "phiên đăng
nhập hết hạn", lặp lại các bước trên rồi `/setsession` lại.

## 2. Chạy thử ở máy local (khuyên làm trước khi deploy)

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export BOT_TOKEN="..."            # Windows PowerShell: $env:BOT_TOKEN="..."
export ALLOWED_USER_IDS="..."
export MODE=polling                # local luôn dùng polling, không cần webhook

python bot.py
```

Chạy test phần logic thuần (không cần token/mạng thật):

```bash
python -m unittest discover -s tests -v
```

## 3. Deploy lên Render

Có 2 phương án — code hỗ trợ cả hai qua biến môi trường `MODE`, không cần
sửa code khi đổi phương án.

### Phương án A — Web Service, gói Free, chế độ webhook (khuyến nghị để bắt đầu, $0)

Đây là cấu hình mặc định trong `render.yaml`.

1. Đẩy code này lên 1 repo GitHub (**thêm `.gitignore` đã có sẵn — đừng bao
   giờ commit `data/session.json` hay cookie thật**).
2. Render Dashboard → **New** → **Blueprint** → chọn repo vừa tạo. Render
   đọc `render.yaml` và tạo sẵn service `lazada-aff-bot` (plan Free, region
   Singapore — gần Việt Nam nhất trong các region Render đang hỗ trợ).
3. Vào service vừa tạo → **Environment**, điền các biến đang để trống
   (`sync: false` trong blueprint):
   - `BOT_TOKEN`
   - `ALLOWED_USER_IDS`
   - (tuỳ chọn) `LAZADA_CURL` — dán nguyên lệnh curl để có sẵn session ngay
     từ lần deploy đầu, đỡ phải `/setsession` thủ công. Nếu bỏ trống, sau
     khi bot chạy thì `/setsession` trong Telegram như bình thường.
   - `WEBHOOK_SECRET` Render đã tự sinh ngẫu nhiên (`generateValue: true`),
     không cần đụng vào.
4. Deploy xong, gửi `/start` cho bot trên Telegram để kiểm tra.

**Đánh đổi của gói Free:** service "ngủ" sau 15 phút không có request, tin
nhắn đầu tiên sau đó có thể mất 30–60 giây để bot "thức dậy" và trả lời (vì
mỗi tin nhắn Telegram gửi tới bot dưới dạng 1 HTTP request tới webhook, nên
chính nó sẽ đánh thức service). Với bot dùng cá nhân, không thường xuyên,
mức này thường chấp nhận được.

### Phương án B — Background Worker, chế độ polling (ổn định hơn, không cold-start, KHÔNG có gói free)

Background Worker trên Render **không có gói miễn phí** (tối thiểu gói
Starter, hiện khoảng 7 USD/tháng — kiểm tra lại giá mới nhất tại
render.com/pricing vì có thể đổi). Đổi lại: luôn chạy, không cold-start,
không cần lo webhook/URL public.

Cách làm: trong Render Dashboard tạo **New → Background Worker** (thay vì
dùng Blueprint sẵn, hoặc sửa `render.yaml`: đổi `type: web` → `type: worker`,
bỏ `MODE`/`WEBHOOK_SECRET` khỏi envVars vì không cần nữa). Cấu hình:
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Env vars: `BOT_TOKEN`, `ALLOWED_USER_IDS`, (tuỳ chọn) `LAZADA_CURL`.
  Không set `MODE` (mặc định đã là `polling`).

## 4. Các lỗi thường gặp khi deploy

**`ValueError: invalid literal for int() with base 10: 'curl...'` (hoặc tương
tự) ngay khi vừa deploy, kèm "Port scan timeout"**
→ Bạn đã dán nhầm nội dung (thường là lệnh curl) vào biến `ALLOWED_USER_IDS`.
Biến này CHỈ chứa số Telegram user ID (vd `111111111`), không chứa curl/cookie
gì cả. Vào Render → service → **Environment**, kiểm tra lại cả 3 biến
`BOT_TOKEN` / `ALLOWED_USER_IDS` / `LAZADA_CURL` xem có bị lẫn giá trị không,
sửa lại đúng loại nội dung cho từng biến rồi deploy lại. "Port scan timeout"
chỉ là hậu quả (bot crash trước khi kịp mở port) — tự hết khi sửa xong lỗi trên.

**`CurlParseError` báo "có vẻ được copy ở dạng cmd/PowerShell"**
→ Bạn bấm nhầm "Copy as cURL (cmd)" thay vì **"Copy as cURL (bash)"** trong
menu chuột phải ở DevTools (Chrome/Edge luôn có cả 2 lựa chọn dù bạn dùng
Windows). Copy lại, chọn đúng "(bash)". Nếu vẫn không được, dùng cách fallback
đơn giản hơn: copy riêng giá trị header `cookie:` (xem chi tiết trong hướng
dẫn `/setsession` của bot).

**`telegram.error.BadRequest: Secret token contains unallowed characters`**
→ `WEBHOOK_SECRET` đang chứa ký tự Telegram không cho phép (thường là `/` hoặc
`=` - do dùng `generateValue: true` trong render.yaml, giá trị Render tự sinh
đôi khi ra dạng base64 có các ký tự này). Telegram chỉ nhận chữ, số, `_`, `-`.
Vào Render → Environment → `WEBHOOK_SECRET`, đặt lại 1 chuỗi khác chỉ gồm các
ký tự đó, ví dụ tự sinh bằng `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
rồi dán kết quả vào (bot cũng tự kiểm tra và báo lỗi rõ ràng nếu bạn đặt sai
lần sau, thay vì để Telegram trả lỗi khó hiểu như trên).

**Mẹo tránh nhầm lẫn biến môi trường:** thay vì set `LAZADA_CURL` lúc tạo
Blueprint (dễ dán nhầm ô), có thể để trống, deploy trước, rồi sau khi bot
chạy thì nhắn `/setsession` cho bot trên Telegram và dán curl ở đó — vừa
tránh nhầm ô, vừa dễ sửa lại khi cookie hết hạn sau này.

## 5. Lưu ý quan trọng

- **API dùng ở đây không phải API chính thức/công khai của Lazada** — nó là
  API nội bộ mà chính trang web affiliate của Lazada gọi khi bạn bấm nút
  "Tạo shortlink", được suy ra từ request thật. Bot chỉ dùng session đăng
  nhập của chính bạn để tự động hoá lại thao tác bạn vốn có quyền làm qua
  giao diện web — không truy cập trái phép vào hệ thống hay tài khoản người
  khác. Rủi ro chủ yếu là: (1) Lazada có thể đổi cấu trúc API này bất cứ
  lúc nào khiến bot ngừng hoạt động, và (2) việc tự động hoá qua API nội bộ
  thay vì thao tác tay trên trình duyệt có thể không đúng tinh thần Điều
  khoản dịch vụ của Lazada dành cho affiliate — đáng để bạn biết trước khi
  dùng cho quy mô lớn/liên tục.
- **Bảo mật session:** ai có được session (cookie) này có toàn quyền tạo
  affiliate link nhân danh tài khoản bạn. Vì vậy bot mặc định khoá hết thao
  tác nếu chưa cấu hình `ALLOWED_USER_IDS`, và `/status` chỉ hiện cookie đã
  che bớt. Đừng chia sẻ token bot hay nội dung curl cho ai, đừng commit
  `data/session.json` lên Git công khai.
- **Session không bền qua redeploy trên Render** trừ khi bạn gắn thêm
  Persistent Disk và trỏ biến `SESSION_FILE` vào đó — vì cookie vốn cũng
  hết hạn định kỳ nên đơn giản nhất là `/setsession` lại sau mỗi lần
  redeploy hoặc khi bot báo lỗi phiên đăng nhập.
