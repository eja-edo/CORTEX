"""Where a person's token version lives (auth/versions.py) and what a token of an older version means (auth/sessions.py): the cache is never the
truth. Run against the memory store everywhere, and against a real Redis when one answers (`CL_TEST_REDIS_URL`, default the compose service on
6390); those runs are skipped when none does."""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from support import PASSWORD, account_for_key, h, sign_in

from cortex_leads.app import create_app
from cortex_leads.auth import sessions, tokens
from cortex_leads.auth.versions import MemoryStore, RedisStore, StoreDown, set_store
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

REDIS_URL = os.environ.get("CL_TEST_REDIS_URL", "redis://localhost:6390/0")


async def _redis_up() -> bool:
    try:
        import redis.asyncio as aioredis
        return bool(await aioredis.Redis.from_url(REDIS_URL, socket_connect_timeout=0.3).ping())
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(params=["memory", "redis"])
async def store(request):
    if request.param == "memory":
        st = MemoryStore()
    else:
        if not await _redis_up():
            pytest.skip("no Redis to test against")
        st = RedisStore(REDIS_URL, "t" + uuid.uuid4().hex[:8])  # its own namespace: no test can see another's keys
    set_store(st)
    yield st
    set_store(None)


async def _in(app_client, world, api_key_factory, role="staff", ref="nv1"):
    _, key = await api_key_factory(world.t, role, ref if role == "staff" else None)
    app_client.cookies.clear()
    csrf = await sign_in(app_client, key)
    return csrf, await account_for_key(key)


async def _forget(store):
    """Redis emptied or restarted."""
    if isinstance(store, MemoryStore):
        store.forget_everything()
        return
    import redis.asyncio as aioredis
    r = aioredis.Redis.from_url(REDIS_URL)
    async for k in r.scan_iter(match=f"{store._p}:*"):
        await r.delete(k)


def _second_device():
    from httpx import ASGITransport, AsyncClient
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def test_the_cache_holds_one_number_per_person_and_nothing_else(store, app_client, world, api_key_factory):
    csrf, email = await _in(app_client, world, api_key_factory)
    assert (await app_client.get("/api/v1/session")).status_code == 200
    async with tenant_session(world.t.id) as s:
        uid = (await s.execute(select(m.AppUser.id).where(m.AppUser.email == email))).scalar_one()
    assert await store.get(uid) == 0
    if isinstance(store, RedisStore):
        import redis.asyncio as aioredis
        keys = [k async for k in aioredis.Redis.from_url(REDIS_URL, decode_responses=True).scan_iter(match=f"{store._p}:*")]
        assert keys == [f"{store._p}:v:{uid}"]  # a user id and a version: no per-device key, no marker


async def test_signing_out_everywhere_ends_every_device_at_once_and_nobody_else(store, app_client, world, api_key_factory):
    csrf, email = await _in(app_client, world, api_key_factory)
    async with _second_device() as phone:
        assert (await phone.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})).status_code == 200
        assert (await phone.get("/api/v1/session")).status_code == 200 and (await app_client.get("/api/v1/session")).status_code == 200
        owner_csrf, _ = await _in(app_client, world, api_key_factory, "owner")
        who = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["email"] == email)
        assert (await app_client.post(f"/api/v1/team/{who['id']}/end-sessions", headers=h(owner_csrf))).json()["ended"] == 2
        assert (await phone.get("/api/v1/session")).status_code == 401
        assert (await app_client.get("/api/v1/session")).status_code == 200  # the owner's own sign-in is another person's version: untouched
        assert (await phone.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})).status_code == 200  # and they can sign in again
        assert (await phone.get("/api/v1/session")).status_code == 200


async def test_one_device_is_signed_out_at_once_and_the_others_carry_on(store, app_client, world, api_key_factory):
    csrf, email = await _in(app_client, world, api_key_factory)
    async with _second_device() as phone:
        assert (await phone.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})).status_code == 200
        before = tokens.decode(app_client.cookies.get("cl_session"))
        others = [x for x in (await app_client.get("/api/v1/session/sessions")).json()["items"] if not x["current"]]
        assert len(others) == 1
        assert (await app_client.post(f"/api/v1/session/sessions/{others[0]['id']}/revoke", headers=h(csrf))).status_code == 200
        assert (await phone.get("/api/v1/session")).status_code == 401  # that device, on its very next request
        assert (await phone.get("/api/v1/session")).status_code == 401
        # the device that did it: its token is one version behind now, found good in the database and quietly re-issued
        r = await app_client.get("/api/v1/session")
        assert r.status_code == 200 and r.headers.get("set-cookie", "").startswith("cl_session=")
        after = tokens.decode(app_client.cookies.get("cl_session"))
        assert after.version == before.version + 1 and after.sid == before.sid
        assert (await app_client.get("/api/v1/session")).headers.get("set-cookie") is None  # once, not on every request


async def test_signing_out_the_device_in_use_kills_a_copied_cookie_at_once(store, app_client, world, api_key_factory):
    csrf, _ = await _in(app_client, world, api_key_factory)
    copied = app_client.cookies.get("cl_session")
    assert (await app_client.post("/api/v1/session/logout", headers=h(csrf))).status_code == 200
    app_client.cookies.set("cl_session", copied, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401


async def test_an_emptied_cache_loses_speed_not_sign_outs(store, app_client, world, api_key_factory):
    """Redis restarted or flushed: a device signed out on its own, and a person signed out everywhere, must still be out."""
    csrf, email = await _in(app_client, world, api_key_factory)
    async with _second_device() as phone, _second_device() as old:
        await phone.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})
        await old.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})
        items = [x for x in (await app_client.get("/api/v1/session/sessions")).json()["items"] if not x["current"]]
        assert (await app_client.post(f"/api/v1/session/sessions/{items[0]['id']}/revoke", headers=h(csrf))).status_code == 200
        gone = [c for c in (phone, old) if (await c.get("/api/v1/session")).status_code == 401]
        assert len(gone) == 1
        alive = phone if gone[0] is old else old
        assert (await alive.get("/api/v1/session")).status_code == 200
        await _forget(store)
        assert (await gone[0].get("/api/v1/session")).status_code == 401  # nothing remembered it, the database did
        assert (await alive.get("/api/v1/session")).status_code == 200
        assert (await app_client.post("/api/v1/session/logout-all", headers=h(csrf))).status_code == 200
        await _forget(store)
        assert (await alive.get("/api/v1/session")).status_code == 401


async def test_without_redis_every_request_asks_the_database_and_signing_out_still_works(app_client, world, api_key_factory):
    class Down:
        async def get(self, *_):
            raise StoreDown("down")

        async def set(self, *_): ...

    set_store(Down())
    try:
        csrf, email = await _in(app_client, world, api_key_factory)
        assert (await app_client.get("/api/v1/session")).status_code == 200
        assert (await app_client.post("/api/v1/session/logout-all", headers=h(csrf))).status_code == 200
        assert (await app_client.get("/api/v1/session")).status_code == 401
    finally:
        set_store(None)


async def test_a_lost_cache_write_heals_within_the_cache_lifetime(app_client, world, api_key_factory):
    """A bump reached the database but not Redis: the old number may be believed only until its key expires."""
    st = MemoryStore()
    set_store(st)
    try:
        csrf, email = await _in(app_client, world, api_key_factory)
        assert (await app_client.get("/api/v1/session")).status_code == 200
        async with tenant_session(world.t.id) as s:
            uid = (await s.execute(select(m.AppUser.id).where(m.AppUser.email == email))).scalar_one()
            await s.execute(text("update app_user set token_version = token_version + 1 where id = :i"), {"i": uid})
            await s.execute(text("update auth_session set revoked_at = now() where user_id = :i"), {"i": uid})  # as every real bump does
        assert (await app_client.get("/api/v1/session")).status_code == 200  # still believed for now
        st._v = {k: (v, 0.0) for k, (v, _) in st._v.items()}  # the cached number is past its lifetime
        assert (await app_client.get("/api/v1/session")).status_code == 401  # read again from the truth
    finally:
        set_store(None)


async def test_an_old_version_alone_never_lets_a_revoked_sign_in_through(app_client, world, api_key_factory):
    csrf, email = await _in(app_client, world, api_key_factory)
    stale = app_client.cookies.get("cl_session")
    assert (await app_client.post("/api/v1/session/logout-all", headers=h(csrf))).status_code == 200
    app_client.cookies.set("cl_session", stale, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401
    c = tokens.decode(stale)
    assert c is not None and c.expires_at > datetime.now(UTC) - timedelta(seconds=1)  # the token itself is fine: its sign-in was ended
    assert await sessions.verify(stale) is None


async def test_a_disabled_person_is_out_whatever_version_their_token_has(app_client, world, api_key_factory):
    from cortex_leads.auth.users import change_role_or_status
    csrf, email = await _in(app_client, world, api_key_factory)
    async with tenant_session(world.t.id) as s:
        user = (await s.execute(select(m.AppUser).where(m.AppUser.email == email))).scalar_one()
        await change_role_or_status(s, user, role=None, status="disabled", now=datetime.now(UTC))
    assert (await app_client.get("/api/v1/session")).status_code == 401
