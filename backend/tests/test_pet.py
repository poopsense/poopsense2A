from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Assessment, PetCheckin, SessionRecord
from app.pet import _today


OWNER = {"X-Household-Key": "household-secret"}
VIEWER = {"X-Household-Key": "viewer-secret"}
BASE = "/api/v1/households/hh_001/members/m_001/pet"


def test_pet_stays_curious_without_reliable_health_coverage(client):
    response = client.get(BASE, headers=OWNER)
    assert response.status_code == 200
    body = response.json()
    assert body["mood"] == "curious"
    assert body["health_basis"] == "insufficient"
    assert body["selected_skin"] == "classic"
    assert body["unlocked_skins"] == ["classic"]


def test_daily_checkin_is_idempotent_and_does_not_change_health_facts(client):
    with SessionLocal() as db:
        sessions_before = db.scalar(select(func.count()).select_from(SessionRecord))
        assessments_before = db.scalar(select(func.count()).select_from(Assessment))
    first = client.post(f"{BASE}/check-in", headers=OWNER)
    second = client.post(f"{BASE}/check-in", headers=OWNER)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert second.json()["pet"]["total_checkins"] == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PetCheckin)) == 1
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == sessions_before
        assert db.scalar(select(func.count()).select_from(Assessment)) == assessments_before


def test_skin_unlock_and_profile_version(client):
    client.get(BASE, headers=OWNER)
    with SessionLocal() as db:
        for offset in (2, 1, 0):
            db.add(PetCheckin(
                household_id="hh_001", subject_member_id="m_001",
                checkin_date=_today() - timedelta(days=offset), source="test",
                created_by_user_id="u_owner", created_at=datetime.now(timezone.utc),
            ))
        db.commit()
    snapshot = client.get(BASE, headers=OWNER).json()
    assert snapshot["streak_days"] == 3
    assert "blue_wave" in snapshot["unlocked_skins"]
    updated = client.put(
        BASE, json={"name": "蓝噗", "selected_skin": "blue_wave"}, headers=OWNER,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "蓝噗"
    assert updated.json()["profile_version"] == 2


def test_locked_skin_and_view_only_grant(client):
    locked = client.put(
        BASE, json={"name": "小噗", "selected_skin": "pop_star"}, headers=OWNER,
    )
    assert locked.status_code == 409
    assert locked.json()["detail"]["code"] == "PET_SKIN_LOCKED"

    grant = client.post(
        "/api/v1/households/hh_001/members/m_001/grants",
        json={"viewer_user_id": "u_viewer"}, headers=OWNER,
    )
    assert grant.status_code == 200
    assert client.get(BASE, headers=VIEWER).status_code == 200
    assert client.post(f"{BASE}/check-in", headers=VIEWER).status_code == 403
    assert client.put(
        BASE, json={"name": "越权", "selected_skin": "classic"}, headers=VIEWER,
    ).status_code == 403
