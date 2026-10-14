async def test_health_and_conditional_mount(app_client) -> None:
    r = await app_client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
