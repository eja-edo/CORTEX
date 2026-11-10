"""Forgotten password by email: the same answer whoever asks, a link that works once for a short time, and nothing secret in the mail."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import text
from support import PASSWORD, account_for_key, sign_in
from wp5_support import rows

from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.notify.mailer import FileMailer, MemoryMailer, SmtpMailer, get_mailer, set_mailer

A = "/api/v1/auth"
NEW = "Mat-khau-moi-7391"
BASE = "https://cortex.example.vn"


@pytest.fixture
async def person(world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    return await account_for_key(key)


def token_of(mailbox: MemoryMailer, n: int = -1) -> str:
    return re.search(r"#token=([\w\-]+)", mailbox.sent[n]["body"]).group(1)


async def login(client, email, password):
    return await client.post("/api/v1/session/login", json={"email": email, "password": password})


async def test_without_a_mail_server_the_feature_says_it_is_off_and_the_login_page_keeps_the_old_advice(app_client, monkeypatch):
    set_mailer(None)
    monkeypatch.setattr(get_settings(), "MAIL_DIR", None)
    monkeypatch.setattr(get_settings(), "SMTP_HOST", None)
    assert (await app_client.get(f"{A}/recovery")).json() == {"enabled": False}
    r = await app_client.post(f"{A}/forgot", json={"email": "a@b.vn"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "RECOVERY_OFF"


async def test_a_mail_server_without_a_public_address_is_not_enough(app_client, monkeypatch):
    set_mailer(MemoryMailer())
    monkeypatch.setattr(get_settings(), "PUBLIC_BASE_URL", None)  # nowhere to point the link
    try:
        assert (await app_client.get(f"{A}/recovery")).json() == {"enabled": False}
    finally:
        set_mailer(None)


def test_the_mailer_is_chosen_from_configuration(monkeypatch, tmp_path):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "SMTP_HOST", None)
    monkeypatch.setattr(cfg, "MAIL_DIR", None)
    assert get_mailer() is None
    monkeypatch.setattr(cfg, "MAIL_DIR", str(tmp_path))
    assert isinstance(get_mailer(), FileMailer)
    monkeypatch.setattr(cfg, "SMTP_HOST", "smtp.example.vn")
    assert get_mailer() is None or isinstance(get_mailer(), FileMailer)  # a host without a sender address is not a working setup
    monkeypatch.setattr(cfg, "MAIL_FROM", "Cortex <no-reply@example.vn>")
    assert isinstance(get_mailer(), SmtpMailer)


async def test_the_mail_holds_a_link_with_the_token_in_the_fragment_and_never_a_password(app_client, mail, person):
    r = await app_client.post(f"{A}/forgot", json={"email": person})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    (sent,) = mail.sent
    assert sent["to"] == person and "mật khẩu" in sent["subject"].lower()
    assert re.search(rf"{re.escape(BASE)}/app/reset#token=[\w\-]{{40,}}", sent["body"])  # a fragment is not sent to a server or a Referer
    assert PASSWORD not in sent["body"]


async def test_the_link_is_built_from_configuration_never_from_the_request_host(app_client, mail, person):
    await app_client.post(f"{A}/forgot", json={"email": person}, headers={"Host": "evil.test", "X-Forwarded-Host": "evil.test"})
    assert mail.sent[0]["body"].count(BASE) == 1 and "evil.test" not in mail.sent[0]["body"]


async def test_asking_gives_the_same_answer_for_an_account_a_stranger_and_a_disabled_account(app_client, mail, person, world):
    async with tenant_session(world.t.id) as s:
        from cortex_leads.auth.users import create_user
        off = await create_user(s, world.t.id, email="nghi@example.vn", name="Người Nghỉ", role="staff", password=PASSWORD, created_by="test")
        off.status = "disabled"
    answers = [await app_client.post(f"{A}/forgot", json={"email": e}) for e in (person, "khong-ai-ca@nowhere.test", "nghi@example.vn", "not an email")]
    assert {(a.status_code, a.text) for a in answers} == {(200, '{"status":"ok"}')}
    assert [x["to"] for x in mail.sent] == [person]  # only the real, active account got a mail


async def test_the_new_password_works_the_old_does_not_and_every_sign_in_ends(app_client, mail, person, world):
    assert (await login(app_client, person, PASSWORD)).status_code == 200
    stale = app_client.cookies.get("cl_session")
    await app_client.post(f"{A}/forgot", json={"email": person})
    app_client.cookies.clear()
    r = await app_client.post(f"{A}/reset", json={"token": token_of(mail), "password": NEW})
    assert r.status_code == 200
    app_client.cookies.set("cl_session", stale, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401  # signed out everywhere
    app_client.cookies.clear()
    assert (await login(app_client, person, PASSWORD)).status_code == 401
    ok = await login(app_client, person, NEW)
    assert ok.status_code == 200
    events = [e for e in await rows(world, m.AuditEvent) if e.action.startswith("password.reset")]
    assert {e.action for e in events} == {"password.reset_requested", "password.reset_by_email"}
    blob = "".join(e.summary + str(e.metadata_) + e.actor for e in events)
    assert token_of(mail) not in blob and NEW not in blob  # neither the token nor the password is in the trail


async def test_only_a_hash_of_the_token_is_stored(app_client, mail, person, world):
    await app_client.post(f"{A}/forgot", json={"email": person})
    token = token_of(mail)
    async with tenant_session(world.t.id) as s:
        (row,) = (await s.execute(text("select token_hash, used_at, expires_at - created_at as ttl from password_reset"))).all()
    assert row.token_hash != token and token not in row.token_hash and len(row.token_hash) == 64 and row.used_at is None
    assert timedelta(minutes=29) < row.ttl <= timedelta(minutes=30, seconds=1)  # created_at is the DB clock at the start of the transaction, expires_at is computed a moment later


async def test_a_link_works_once(app_client, mail, person):
    await app_client.post(f"{A}/forgot", json={"email": person})
    token = token_of(mail)
    assert (await app_client.post(f"{A}/reset", json={"token": token, "password": NEW})).status_code == 200
    again = await app_client.post(f"{A}/reset", json={"token": token, "password": "Mat-khau-khac-5512"})
    assert again.status_code == 400 and again.json()["detail"]["code"] == "BAD_RESET_TOKEN"
    assert (await login(app_client, person, NEW)).status_code == 200  # the second try changed nothing


async def test_a_weak_password_is_refused_and_the_link_is_not_spent(app_client, mail, person):
    await app_client.post(f"{A}/forgot", json={"email": person})
    token = token_of(mail)
    weak = await app_client.post(f"{A}/reset", json={"token": token, "password": "ngan1"})
    assert weak.status_code == 422 and weak.json()["detail"]["code"] == "WEAK_PASSWORD"
    assert (await app_client.post(f"{A}/reset", json={"token": token, "password": NEW})).status_code == 200


async def test_an_expired_link_a_made_up_one_and_a_used_one_get_the_same_refusal(app_client, mail, person, owner_engine):
    await app_client.post(f"{A}/forgot", json={"email": person})
    token = token_of(mail)
    async with owner_engine.begin() as c:
        await c.execute(text("update password_reset set expires_at = now() - interval '1 second'"))
    outcomes = [await app_client.post(f"{A}/reset", json={"token": t, "password": NEW}) for t in (token, "x" * 43, "y" * 20)]
    assert {(o.status_code, o.text) for o in outcomes} == {(400, outcomes[0].text)} and outcomes[0].json()["detail"]["code"] == "BAD_RESET_TOKEN"
    assert (await login(app_client, person, NEW)).status_code == 401


async def test_asking_again_cancels_the_earlier_link(app_client, mail, person):
    await app_client.post(f"{A}/forgot", json={"email": person})
    await app_client.post(f"{A}/forgot", json={"email": person})
    first, second = token_of(mail, 0), token_of(mail, 1)
    assert (await app_client.post(f"{A}/reset", json={"token": first, "password": NEW})).status_code == 400
    assert (await app_client.post(f"{A}/reset", json={"token": second, "password": NEW})).status_code == 200


async def test_an_account_disabled_after_asking_cannot_use_the_link(app_client, mail, person, world):
    await app_client.post(f"{A}/forgot", json={"email": person})
    async with tenant_session(world.t.id) as s:
        from sqlalchemy import update
        await s.execute(update(m.AppUser).where(m.AppUser.email == person).values(status="disabled"))
    assert (await app_client.post(f"{A}/reset", json={"token": token_of(mail), "password": NEW})).status_code == 400


async def test_one_address_gets_three_mails_an_hour_and_the_fourth_is_silent(app_client, mail, person):
    answers = [await app_client.post(f"{A}/forgot", json={"email": person}) for _ in range(5)]
    assert {a.status_code for a in answers} == {200}  # the limit is not visible from outside, so it cannot be used to find accounts
    assert len(mail.sent) == 3


async def test_one_address_on_the_network_is_stopped_after_too_many_asks(app_client, mail):
    codes = [(await app_client.post(f"{A}/forgot", json={"email": f"nguoi{i}@nowhere.test"})).status_code for i in range(13)]
    assert codes[:10] == [200] * 10 and set(codes[10:]) == {429}


async def test_guessing_tokens_is_slowed_too(app_client, mail):
    codes = [(await app_client.post(f"{A}/reset", json={"token": f"{i:040d}", "password": NEW})).status_code for i in range(34)]
    assert set(codes[:30]) == {400} and 429 in codes[30:]


async def test_a_failing_mail_server_does_not_change_what_the_person_sees(app_client, mail, person):
    mail.fail = True
    r = await app_client.post(f"{A}/forgot", json={"email": person})
    assert r.status_code == 200 and r.json() == {"status": "ok"} and mail.sent == []


async def test_resetting_lifts_the_lock_a_guesser_put_on_the_account(app_client, mail, person):
    for _ in range(5):
        await login(app_client, person, "sai-mat-khau-1")
    assert (await login(app_client, person, PASSWORD)).status_code == 429
    await app_client.post(f"{A}/forgot", json={"email": person})
    assert (await app_client.post(f"{A}/reset", json={"token": token_of(mail), "password": NEW})).status_code == 200
    assert (await login(app_client, person, NEW)).status_code == 200


async def test_an_invited_account_with_no_password_can_also_be_opened_by_the_forgot_link(app_client, mail, world):
    async with tenant_session(world.t.id) as s:
        from cortex_leads.auth.users import create_user
        await create_user(s, world.t.id, email="moi@example.vn", name="Người Mới", role="staff", created_by="test")  # invited: no password yet
    await app_client.post(f"{A}/forgot", json={"email": "moi@example.vn"})
    assert (await app_client.post(f"{A}/reset", json={"token": token_of(mail), "password": NEW})).status_code == 200
    assert (await login(app_client, "moi@example.vn", NEW)).status_code == 200


async def test_the_database_shows_a_link_only_to_whoever_names_its_token_and_never_across_businesses(app_client, mail, person, world, tenant_factory):
    await app_client.post(f"{A}/forgot", json={"email": person})
    async with system_session() as s:
        assert (await s.execute(text("select count(*) from password_reset"))).scalar_one() == 0  # no business, no token named: nothing
    other = await tenant_factory("Khác")
    async with tenant_session(other.id) as s:
        assert (await s.execute(text("select count(*) from password_reset"))).scalar_one() == 0
    from cortex_leads.console.recovery import token_hash
    async with system_session() as s:
        await s.execute(text("select set_config('app.reset_token', :h, true)"), {"h": token_hash(token_of(mail))})
        assert (await s.execute(text("select count(*) from password_reset"))).scalar_one() == 1  # exactly the one named


async def test_signing_in_still_works_after_all_this(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    assert await sign_in(app_client, key)


async def test_a_mail_is_written_to_a_directory_in_development(tmp_path):
    await FileMailer(str(tmp_path / "out"), "Cortex <no-reply@localhost>").send("a@b.vn", "Chủ đề", "Nội dung\nhttp://x/#token=abc")
    (f,) = (tmp_path / "out").iterdir()
    assert "To: a@b.vn" in f.read_text() and "token=abc" in f.read_text()


async def test_a_line_break_cannot_be_smuggled_into_a_mail_header(tmp_path):
    from cortex_leads.notify.mailer import MailError
    with pytest.raises(MailError):
        await FileMailer(str(tmp_path), "x@y.vn").send("a@b.vn\nBcc: victim@x.vn", "s", "b")


async def test_smtp_goes_through_starttls_and_login_and_hides_the_server_reply_on_failure(monkeypatch):
    import smtplib

    from cortex_leads.notify.mailer import MailError
    calls = []

    class FakeSmtp:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            calls.append(("starttls", context is not None))

        def login(self, u, p):
            calls.append(("login", u))

        def send_message(self, msg):
            calls.append(("send", msg["To"]))
            if msg["To"] == "bad@b.vn":
                raise smtplib.SMTPRecipientsRefused({"bad@b.vn": (550, b"password=hunter2 rejected")})

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    mailer = SmtpMailer("smtp.example.vn", 587, "user", "pw", "Cortex <no-reply@example.vn>", True)
    await mailer.send("a@b.vn", "s", "b")
    assert calls == [("connect", "smtp.example.vn", 587), ("starttls", True), ("login", "user"), ("send", "a@b.vn")]
    with pytest.raises(MailError) as e:
        await mailer.send("bad@b.vn", "s", "b")
    assert "hunter2" not in str(e.value) and "bad@b.vn" not in str(e.value)  # the class name only
