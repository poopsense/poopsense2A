from copy import deepcopy

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AgentAction, FamilyGrant, OutboxEvent
from app.worker import run_until_empty


DEVICE_HEADERS = {"X-Device-Key": "dev-secret"}
OWNER_HEADERS = {"X-Household-Key": "household-secret"}
VIEWER_HEADERS = {"X-Household-Key": "viewer-secret"}


def grant_viewer(client, member_id="m_001"):
    return client.post(
        f"/api/v1/households/hh_001/members/{member_id}/grants",
        json={"viewer_user_id": "u_viewer", "can_view": True, "redline_notifications": True},
        headers=OWNER_HEADERS,
    )


def upload_redline_and_claim(client, normal_payload, session_id="ses_redline"):
    payload = deepcopy(normal_payload)
    payload["session_id"] = session_id
    payload["correlation_id"] = f"cor_{session_id}"
    payload["observations"]["color"]["value"] = "red"
    received = client.post("/api/v1/device-sessions", json=payload, headers=DEVICE_HEADERS)
    assert received.status_code == 202
    claimed = client.post(
        f"/api/v1/households/hh_001/sessions/{session_id}/claim",
        json={"member_id": "m_001"}, headers=OWNER_HEADERS,
    )
    assert claimed.status_code == 200


def test_view_permission_starts_and_stops_with_grant(client):
    before = client.get(
        "/api/v1/households/hh_001/members/m_001/trends", headers=VIEWER_HEADERS
    )
    assert before.status_code == 403
    granted = grant_viewer(client)
    assert granted.status_code == 200
    assert granted.json()["status"] == "active"
    during = client.get(
        "/api/v1/households/hh_001/members/m_001/trends", headers=VIEWER_HEADERS
    )
    assert during.status_code == 200
    revoked = client.delete(
        f"/api/v1/households/hh_001/grants/{granted.json()['grant_id']}",
        headers=OWNER_HEADERS,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    after = client.get(
        "/api/v1/households/hh_001/members/m_001/trends", headers=VIEWER_HEADERS
    )
    assert after.status_code == 403


def test_revocation_cancels_queued_viewer_redline_but_not_subject(client, normal_payload):
    granted = grant_viewer(client).json()
    upload_redline_and_claim(client, normal_payload)
    revoked = client.delete(
        f"/api/v1/households/hh_001/grants/{granted['grant_id']}", headers=OWNER_HEADERS
    )
    assert revoked.json()["cancelled_actions"] == 1
    with SessionLocal() as db:
        run_until_empty(db)
        actions = db.scalars(select(AgentAction).order_by(AgentAction.recipient_id)).all()
        by_recipient = {item.recipient_id: item for item in actions}
        assert by_recipient["u_owner"].status == "succeeded"
        assert by_recipient["u_viewer"].status == "cancelled_by_revocation"
        assert by_recipient["u_viewer"].processed_at is None


def test_send_time_check_blocks_revoked_grant_even_if_action_is_requeued(client, normal_payload):
    granted = grant_viewer(client).json()
    upload_redline_and_claim(client, normal_payload, "ses_race")
    client.delete(
        f"/api/v1/households/hh_001/grants/{granted['grant_id']}", headers=OWNER_HEADERS
    )
    with SessionLocal() as db:
        viewer_action = db.scalar(select(AgentAction).where(AgentAction.recipient_id == "u_viewer"))
        viewer_action.status = "pending"  # 模拟撤回与已出队任务之间的竞态
        dispatch = db.scalar(select(OutboxEvent).where(
            OutboxEvent.topic == "agent_action.dispatch",
            OutboxEvent.payload["action_id"].as_integer() == viewer_action.id,
        ))
        db.commit()
        run_until_empty(db)
        db.refresh(viewer_action)
        assert viewer_action.status == "cancelled_by_revocation"
        assert viewer_action.result["reason"] == "authorization_invalid_at_send_time"


def test_only_owner_can_manage_grants(client):
    response = client.post(
        "/api/v1/households/hh_001/members/m_001/grants",
        json={"viewer_user_id": "u_viewer"}, headers=VIEWER_HEADERS,
    )
    assert response.status_code == 403


def test_in_app_notification_is_idempotent_and_hidden_after_revocation(client, normal_payload):
    granted = grant_viewer(client).json()
    upload_redline_and_claim(client, normal_payload, "ses_notification")
    with SessionLocal() as db:
        run_until_empty(db)
        run_until_empty(db)
    inbox = client.get(
        "/api/v1/households/hh_001/notifications", headers=VIEWER_HEADERS,
    )
    assert inbox.status_code == 200
    assert len(inbox.json()) == 1
    notice = inbox.json()[0]
    assert notice["priority"] == "urgent"
    marked = client.post(
        f"/api/v1/households/hh_001/notifications/{notice['notification_id']}/read",
        headers=VIEWER_HEADERS,
    )
    assert marked.json()["status"] == "read"
    acknowledged = client.post(
        f"/api/v1/households/hh_001/notifications/{notice['notification_id']}/acknowledge",
        headers=VIEWER_HEADERS,
    )
    assert acknowledged.json()["status"] == "acknowledged"
    client.delete(
        f"/api/v1/households/hh_001/grants/{granted['grant_id']}", headers=OWNER_HEADERS,
    )
    assert client.get(
        "/api/v1/households/hh_001/notifications", headers=VIEWER_HEADERS,
    ).json() == []
    assert client.post(
        f"/api/v1/households/hh_001/notifications/{notice['notification_id']}/read",
        headers=VIEWER_HEADERS,
    ).status_code == 404


def test_member_directory_and_session_history_follow_view_permissions(client, normal_payload):
    owner_members = client.get(
        "/api/v1/households/hh_001/members", headers=OWNER_HEADERS
    )
    assert {item["member_id"] for item in owner_members.json()} == {"m_001", "m_002"}
    assert client.get(
        "/api/v1/households/hh_001/members", headers=VIEWER_HEADERS
    ).json() == []
    grant_viewer(client, "m_001")
    viewer_members = client.get(
        "/api/v1/households/hh_001/members", headers=VIEWER_HEADERS
    )
    assert [item["member_id"] for item in viewer_members.json()] == ["m_001"]
    upload_redline_and_claim(client, normal_payload, "ses_history")
    history = client.get(
        "/api/v1/households/hh_001/members/m_001/sessions", headers=VIEWER_HEADERS
    )
    assert history.status_code == 200
    assert history.json()[0]["session_id"] == "ses_history"
    denied = client.get(
        "/api/v1/households/hh_001/members/m_002/sessions", headers=VIEWER_HEADERS
    )
    assert denied.status_code == 403
