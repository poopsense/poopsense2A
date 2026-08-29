from sqlalchemy import func, select
from app.database import SessionLocal
from app.models import AgentAction, UserNotification, WeeklyHealthReport

OWNER = {"X-Household-Key": "household-secret"}
VIEWER = {"X-Household-Key": "viewer-secret"}
URL = "/api/v1/households/hh_001/members/m_001/weekly-reports"


def test_insufficient_weekly_report_is_idempotent_audited_and_notified(client):
    first = client.post(URL, headers=OWNER)
    second = client.post(URL, headers=OWNER)
    assert first.status_code == 200
    assert first.json()["status"] == "insufficient"
    assert "可靠样本不足" in first.json()["summary"]
    assert second.json()["report_id"] == first.json()["report_id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WeeklyHealthReport)) == 1
        assert db.scalar(select(func.count()).select_from(UserNotification)) == 1
        action = db.scalar(select(AgentAction).where(AgentAction.action_type == "weekly_report_ready"))
        assert action.policy_version


def test_viewer_needs_grant_and_cannot_generate(client):
    assert client.get(URL, headers=VIEWER).status_code == 403
    client.post("/api/v1/households/hh_001/members/m_001/grants",
                json={"viewer_user_id": "u_viewer"}, headers=OWNER)
    assert client.get(URL, headers=VIEWER).status_code == 200
    assert client.post(URL, headers=VIEWER).status_code == 403
