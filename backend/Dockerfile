# Cortex backend — API và **toàn bộ worker nền** trong một tiến trình.
#
# Bảy worker (LLM, Reminder, StateEvaluator, AttentionBundle, Delivery,
# GoogleSync, TaskFlush) chạy trong thread của chính tiến trình FastAPI, dựng
# lên ở `lifespan` của `app/__init__.py`. Hệ quả cho việc vận hành: một
# container là đủ, và cũng là giới hạn trên — hai bản sao nghĩa là hai bộ
# worker cùng quét một DB, và Gate sẽ nhắc mỗi thứ hai lần.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libglib2.0-0: opencv-python-headless vẫn liên kết tới nó. Và `cv2` được
# nạp ngay lúc khởi động chứ không phải lúc dùng — `app/services/ocr/__init__.py`
# import `video_pipeline_service` ở mức module. Thiếu gói này thì backend
# không lên nổi, dù OCR đang đóng băng.
# curl: cho HEALTHCHECK bên dưới.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
# easyocr bị loại khỏi **ảnh**, không bị loại khỏi requirements.txt. Trong
# backend nó chỉ tồn tại dưới dạng *tên engine* trong payload gửi sang
# ocr_service (`app/services/redis/ocr_processor_task.py`) — không dòng nào
# trong `backend/app` import gói này. Nó kéo theo torch, khoảng 2.5GB.
#
# Lọc bằng grep tại đây thay vì duy trì một requirements thứ hai: hai file sẽ
# trôi khỏi nhau và không ai biết lúc nào, một dòng grep thì không.
RUN grep -v '^easyocr' requirements.txt > /tmp/requirements.docker.txt \
 && pip install --no-cache-dir -r /tmp/requirements.docker.txt

# Nướng sẵn bảng BPE của tiktoken vào ảnh.
#
# `app/utils/tokens.py` gọi `tiktoken.get_encoding("cl100k_base")` lần đầu
# ngay trong lượt chat đầu tiên — và lần đầu đó **tải 1.7MB từ Internet, đồng
# bộ, ngay trong event loop**. Đo được trên chính máy này: 4 trong 8 giây từ
# lúc người dùng gõ tới lúc chữ đầu tiên hiện ra là chờ file này về.
#
# Chạy trên host thì đó là cái giá trả một lần rồi thôi, vì cache nằm ở
# /tmp và sống qua các lần khởi động. Trong container thì /tmp mới tinh sau
# mỗi lần tạo lại — nên đóng gói đã biến một lần trả thành trả mãi. Đây là
# chỗ sửa nó: TIKTOKEN_CACHE_DIR trỏ vào một thư mục thuộc về ảnh, và lệnh
# dưới làm cho nó ấm ngay lúc build.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY . .

EXPOSE 8000

# start-period rộng: lần khởi động đầu còn phải chạy migration trước khi mở
# cổng, và số migration hiện tại không nhỏ.
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Migration chạy **trước** khi mở cổng, không song song với nó: một backend
# lên với schema cũ là một backend trả 500 cho tới khi có người nhớ ra.
# `main.py` chứ không phải `uvicorn` CLI — nó gọi `_configure_root_logger()`
# trước khi import app và truyền `log_config=None`, tức là cấu hình log của
# dự án. Gọi CLI là để uvicorn ghi đè cấu hình đó.
CMD ["sh", "-c", "alembic upgrade head && exec python main.py"]
