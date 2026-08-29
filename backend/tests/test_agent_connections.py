from app.database import SessionLocal
from app.models import AgentAction
from sqlalchemy import select

OWNER = {"X-Household-Key": "household-secret"}
BASE = "/api/v1/households/hh_001"


def _post(client, member_id, content):
    return client.post(f"{BASE}/community/posts", json={
        "member_id": member_id, "topic": "encouragement", "content": content,
        "explicit_consent": True,
    }, headers=OWNER).json()


def test_agent_match_requires_two_distinct_explicit_parties(client):
    target = _post(client, "m_002", "一起坚持记录")
    requested = client.post(f"{BASE}/agent-connections", json={
        "initiator_member_id": "m_001", "target_post_id": target["post_id"],
        "explicit_consent": True,
    }, headers=OWNER)
    assert requested.status_code == 200
    assert requested.json()["status"] == "pending"
    connection_id = requested.json()["connection_id"]
    inbound = client.get(f"{BASE}/members/m_002/agent-connections", headers=OWNER).json()[0]
    assert inbound["direction"] == "inbound" and inbound["can_respond"] is True
    accepted = client.post(f"{BASE}/agent-connections/{connection_id}/respond", json={
        "member_id": "m_002", "accept": True,
    }, headers=OWNER)
    assert accepted.json()["status"] == "connected"
    ended = client.post(f"{BASE}/agent-connections/{connection_id}/end?member_id=m_001", headers=OWNER)
    assert ended.json()["status"] == "ended"
    with SessionLocal() as db:
        actions = db.scalars(select(AgentAction.action_type).where(AgentAction.action_type.like("agent_match_%"))).all()
        assert set(actions) == {"agent_match_request", "agent_match_accept", "agent_match_end"}


def test_agent_cannot_match_itself_or_create_duplicate(client):
    own = _post(client, "m_001", "自己的帖子")
    self_match = client.post(f"{BASE}/agent-connections", json={
        "initiator_member_id": "m_001", "target_post_id": own["post_id"], "explicit_consent": True,
    }, headers=OWNER)
    assert self_match.status_code == 409
    target = _post(client, "m_002", "另一个 Agent")
    payload = {"initiator_member_id": "m_001", "target_post_id": target["post_id"], "explicit_consent": True}
    assert client.post(f"{BASE}/agent-connections", json=payload, headers=OWNER).status_code == 200
    assert client.post(f"{BASE}/agent-connections", json=payload, headers=OWNER).status_code == 409
