from sqlalchemy import select

from app.database import SessionLocal
from app.models import AgentAction, CommunityPost


OWNER = {"X-Household-Key": "household-secret"}
VIEWER = {"X-Household-Key": "viewer-secret"}
BASE = "/api/v1/households/hh_001/community/posts"


def test_publish_requires_explicit_consent_and_is_audited(client):
    missing = client.post(BASE, json={
        "member_id": "m_001", "topic": "hydration", "content": "今天记得喝水",
        "explicit_consent": False,
    }, headers=OWNER)
    assert missing.status_code == 422
    created = client.post(BASE, json={
        "member_id": "m_001", "topic": "hydration", "content": "今天记得喝水",
        "explicit_consent": True,
    }, headers=OWNER)
    assert created.status_code == 200
    assert created.json()["can_withdraw"] is True
    with SessionLocal() as db:
        post = db.get(CommunityPost, created.json()["post_id"])
        assert post.consent_version == "community-explicit-v1"
        action = db.scalar(select(AgentAction).where(AgentAction.action_type == "community_publish"))
        assert action.authorization_basis == "explicit_consent:community-explicit-v1"


def test_viewer_cannot_publish_for_member_and_withdraw_hides_post(client):
    created = client.post(BASE, json={
        "member_id": "m_001", "topic": "routine", "content": "早点睡",
        "explicit_consent": True,
    }, headers=OWNER).json()
    denied = client.post(BASE, json={
        "member_id": "m_001", "topic": "routine", "content": "越权发布",
        "explicit_consent": True,
    }, headers=VIEWER)
    assert denied.status_code == 403
    assert len(client.get(BASE, headers=VIEWER).json()) == 1
    withdrawn = client.post(f"{BASE}/{created['post_id']}/withdraw", headers=OWNER)
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert client.get(BASE, headers=OWNER).json() == []


def test_public_result_does_not_expose_household_member_or_user_ids(client):
    client.post(BASE, json={
        "member_id": "m_001", "topic": "diet", "content": "多吃蔬菜",
        "explicit_consent": True,
    }, headers=OWNER)
    item = client.get(BASE, headers=VIEWER).json()[0]
    assert "household_id" not in item
    assert "member_id" not in item
    assert "author_user_id" not in item
