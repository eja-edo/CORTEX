# Checklist chạy kịch bản chuẩn với Page thật

Điều kiện: đã làm `dev/README.md` mục 2-5; `dev.scenario` giả lập chạy xanh; skill thử đặt `after: 5m`; LLM lớp lite cấu hình `CL_LLM_*`.

- [ ] Lõi, bridge Messenger, bridge Twenty và tunnel đang chạy; `/health` của lõi trả 200.
- [ ] Tester (có vai trò trong Meta app) nhắn hỏi giá khóa học -> có `message.created` role `customer` trong DB.
- [ ] Người xây trả lời từ hộp thư Page (không qua Cortex) -> sự kiện role `staff`, không phải `bot`.
- [ ] Tester im 5 phút -> sweep -> job -> nháp `proposed` có `claims` trỏ đúng dòng catalog.
- [ ] Mở trang duyệt (WP13), thấy nháp, cửa sổ `human_agent`/`free`; bấm Duyệt & gửi (WP8) -> tin tới tester, `outbox=sent`.
- [ ] Tester nhắn "tuần sau chị bàn với chồng" -> fact `promised_date` + `decision_maker=vo_chong` (candidate/active đúng luật WP9); đồng hồ nhảy tới ngày hẹn.
- [ ] Trong Twenty kéo opportunity của tester sang stage Won (cortexRef đã điền) -> `deal.updated` accepted, `deal.linked=true`, hẹn `fulfilled`, không còn job.
- [ ] Thêm một dòng vào tab đơn hàng của Sheet -> lần poll tiếp theo nhận; poll lần nữa là `duplicate`.
- [ ] `GET /supervisor/summary` không chứa chữ nào của tester (tên, SĐT, nội dung nháp).
- [ ] Đặt `send_policy.mode=auto`, lặp lại từ bước hỏi giá; tin tự gửi, kill switch tắt được ngay.
- [ ] Ghi số liệu (số nháp, tỉ lệ nhân viên dùng, độ trễ) vào `docs/customers/`.
