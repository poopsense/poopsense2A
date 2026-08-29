def test_readiness_reports_database_and_agent_state(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert isinstance(body["agent_configured"], bool)
    assert isinstance(body["proactive_enabled"], bool)
    assert isinstance(body["worker_enabled"], bool)
    assert isinstance(body["worker_running"], bool)
    assert body["worker_last_error"] is None
