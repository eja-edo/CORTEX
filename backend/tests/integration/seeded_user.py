"""Tài khoản dev mà mười tệp test hardcode.

Id `73552833-…` từng là một hàng có sẵn trong DB dev, và các test dưới đây
được viết dựa vào giả định đó. Giả định ấy **đã sai một lần**: khi dữ liệu
cũ bị dọn sạch, 120 test đỏ cùng lúc vì một hàng `users` biến mất — không
liên quan gì tới code chúng đang kiểm.

Đây là cùng bài học với `seeded_workspace.py` (đã gỡ cùng workspace): một
test không được phụ thuộc vào trạng thái mà không ai chịu trách nhiệm duy
trì. Fixture tự dựng lấy hàng nó cần.

Giữ nguyên id thay vì đổi sang uuid ngẫu nhiên: mười tệp đang tham chiếu
nó, và các hàng dữ liệu dev cũ trỏ vào nó vẫn còn ý nghĩa khi debug.
"""

from uuid import UUID

from sqlalchemy import text

SEEDED_TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")
SEEDED_TEST_USER_EMAIL = "pytest-seeded@cortex.invalid"


async def ensure_seeded_user(db) -> UUID:
    """Dựng tài khoản nếu chưa có. `.invalid` là TLD dành riêng (RFC 2606)
    nên nó không thể trùng địa chỉ thật của ai."""
    await db.execute(
        text(
            "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
            "created_at, updated_at) "
            "VALUES (:id, :email, 'pytest seeded user', 'not-a-real-hash', true, "
            "NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": SEEDED_TEST_USER_ID, "email": SEEDED_TEST_USER_EMAIL},
    )
    await db.commit()
    return SEEDED_TEST_USER_ID
