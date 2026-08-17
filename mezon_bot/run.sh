#!/usr/bin/env bash
# Chạy bot (mặc định) hoặc probe M0.
#
#   ./run.sh          → bot thật (src/index.js)
#   ./run.sh probe    → probe M0 (probe.js)
#
# Ctrl+C để dừng.
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-bot}"

# Hai process cùng một bot token = hai socket tới gateway, và gateway chỉ
# giao mỗi tin nhắn cho MỘT trong số đó. Triệu chứng là bot "chạy bản cũ":
# tin nhắn rơi vào process kia. Không có lỗi nào báo ra, nên phải chặn ở
# đây thay vì đi tìm sau.
RUNNING=$(pgrep -f '^node (src/index\.js|probe\.js)' || true)
if [ -n "$RUNNING" ]; then
  echo "❌ Đã có process bot/probe đang chạy — hai process cùng token sẽ tranh nhau tin nhắn:"
  ps -o pid=,args= -p $RUNNING | sed 's/^/   /'
  echo
  echo "   Dừng nó trước:  pkill -f '^node src/index.js'  hoặc  pkill -f '^node probe.js'"
  exit 1
fi

export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
# shellcheck disable=SC1091
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# Node 22 bắt buộc: better-sqlite3 (phụ thuộc của mezon-sdk) không có
# prebuilt binary cho Node 24, và build từ source cần make/gcc.
nvm use 22 >/dev/null 2>&1 || {
  echo "❌ Không dùng được Node 22. Chạy: nvm install 22"; exit 1;
}
echo "▶ Node $(node --version)"

[ -f .env ] || { echo "❌ Thiếu .env — cp .env.example .env rồi điền"; exit 1; }

if [ "$MODE" = "probe" ]; then
  # Mỗi lần chạy ghi ra file riêng theo dấu thời gian, để dữ liệu các vòng
  # không lẫn vào nhau — quan trọng khi so hành vi giữa các lần thử.
  STAMP=$(date +%Y%m%d-%H%M%S)
  export PROBE_FINDINGS="probe-findings-$STAMP.jsonl"
  echo "▶ Probe M0 — findings: $PROBE_FINDINGS"
  echo "▶ Ctrl+C để dừng"
  echo
  exec node probe.js
fi

echo "▶ Bot — lệnh: *help *ping *link"
echo "▶ Log: bot.log (ghi song song với màn hình)"
echo "▶ Ctrl+C để dừng"
echo
# Node chạy thẳng CommonJS, không có bước build. Sửa code xong chỉ cần
# khởi động lại script này.
#
# `tee` chứ không phải `exec`: bot phải chạy trong terminal của người dùng
# (tiến trình nền bị dọn dẹp sau một thời gian), nhưng log cũng phải nằm
# trong file thì mới đọc lại được để chẩn đoán. Không có file log, mỗi lần
# "bot không trả lời" lại phải dựng lại hiện trường từ đầu.
#
# LOG_LEVEL=debug bật log từng event một, hữu ích khi nghi ngờ tin nhắn
# không tới nơi.
node src/index.js 2>&1 | tee bot.log
