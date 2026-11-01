"""Password storage and policy. scrypt from the standard library (memory-hard, no extra dependency), a random salt per password,
parameters stored with the hash so they can be raised later without locking anyone out. Comparison is constant-time."""
import base64
import hashlib
import hmac
import re
import secrets

N, R, P = 2**15, 8, 1
MIN_LEN, MAX_LEN = 10, 128  # the upper bound keeps one request from making the server hash a megabyte
_COMMON = {"password", "matkhau", "12345678", "123456789", "1234567890", "qwertyuiop", "iloveyou", "admin12345", "letmein123",
           "welcome123", "password1", "password123", "matkhau123", "abc1234567", "cortex12345"}


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=128 * n * r * 2)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


# Verified against when the account does not exist, so "no such account" and "wrong password" take the same time.
_DUMMY = hash_password("not-a-real-password")


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, n, r, p, salt, digest = (stored or _DUMMY).split("$")
        got = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        ok = hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False
    return ok and stored is not None


def strength_errors(password: str, *, email: str = "", name: str = "") -> list[str]:
    """What is wrong with a chosen password, in words a person can act on. [] = acceptable."""
    errs = []
    if len(password) < MIN_LEN:
        errs.append(f"Mật khẩu cần ít nhất {MIN_LEN} ký tự.")
    if len(password) > MAX_LEN:
        errs.append(f"Mật khẩu tối đa {MAX_LEN} ký tự.")
    low = password.lower()
    local = email.split("@")[0].lower()
    if low in _COMMON or len(set(low)) < 4:
        errs.append("Mật khẩu này quá dễ đoán.")
    if (email and low == email.lower()) or (len(local) >= 4 and local in low):
        errs.append("Mật khẩu không được chứa tên đăng nhập (email).")
    if len(name.strip()) >= 4 and name.strip().lower() in low:
        errs.append("Mật khẩu không được chứa tên của bạn.")
    if not re.search(r"[A-Za-zÀ-ỹ]", password) or not re.search(r"[0-9\W_]", password):
        errs.append("Mật khẩu cần có cả chữ và số (hoặc ký tự đặc biệt).")
    return errs


def temporary_password() -> str:
    """For a new account or a reset: shown once to the owner, valid only until the person sets their own."""
    return secrets.token_urlsafe(12) + "7a"  # always has a digit and a letter
