from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AgentMemoryEntry


OWNER = {"X-Household-Key": "household-secret"}
VIEWER = {"X-Household-Key": "viewer-secret"}


def test_self_report_update_appends_version_and_preserves_history(client):
    created = client.post(
        "/api/v1/households/hh_001/members/m_001/memory",
        json={"memory_key": "饮食偏好", "content": "很少吃辣"}, headers=OWNER,
    )
    assert created.status_code == 200
    logical_id = created.json()["logical_id"]
    updated = client.put(
        f"/api/v1/households/hh_001/members/m_001/memory/{logical_id}",
        json={"content": "偶尔吃辣", "correction_reason": "生活习惯改变"}, headers=OWNER,
    )
    assert updated.json()["version"] == 2
    current = client.get(
        "/api/v1/households/hh_001/members/m_001/memory", headers=OWNER,
    ).json()
    assert [item["content"] for item in current] == ["偶尔吃辣"]
    history = client.get(
        "/api/v1/households/hh_001/members/m_001/memory?include_history=true", headers=OWNER,
    ).json()
    assert [item["version"] for item in history] == [2, 1]


def test_sensor_fact_cannot_be_overwritten(client):
    with SessionLocal() as db:
        fact = AgentMemoryEntry(
            logical_id="mem_sensor", household_id="hh_001", subject_member_id="m_001",
            version=1, source_type="sensor_fact", memory_key="传感事实",
            content="可靠样本频率为每周 1 次", authored_by_user_id=None,
            correction_reason=None, active=True, created_at=datetime.now(timezone.utc),
        )
        db.add(fact)
        db.commit()
    response = client.put(
        "/api/v1/households/hh_001/members/m_001/memory/mem_sensor",
        json={"content": "覆盖原始事实"}, headers=OWNER,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SENSOR_FACT_IMMUTABLE"


def test_view_grant_does_not_grant_memory_edit_permission(client):
    client.post(
        "/api/v1/households/hh_001/members/m_001/grants",
        json={"viewer_user_id": "u_viewer"}, headers=OWNER,
    )
    assert client.get(
        "/api/v1/households/hh_001/members/m_001/memory", headers=VIEWER,
    ).status_code == 200
    denied = client.post(
        "/api/v1/households/hh_001/members/m_001/memory",
        json={"memory_key": "目标", "content": "多喝水"}, headers=VIEWER,
    )
    assert denied.status_code == 403


def test_structured_health_profile_is_versioned_memory(client):
    url = "/api/v1/households/hh_001/members/m_001/health-profile"
    first = client.put(url, json={
        "conditions": ["无"], "diet_pattern": "常吃辣", "sleep_pattern": "晚睡",
        "medications": [], "goals": ["规律排便"],
    }, headers=OWNER)
    assert first.status_code == 200
    assert first.json()["completeness"] == 0.8
    second = client.put(url, json={
        "conditions": ["无"], "diet_pattern": "少吃辣", "sleep_pattern": "晚睡",
        "medications": [], "goals": ["规律排便"],
    }, headers=OWNER)
    assert second.status_code == 200
    with SessionLocal() as db:
        diet_versions = db.scalars(select(AgentMemoryEntry).where(
            AgentMemoryEntry.memory_key == "health_profile.diet_pattern"
        ).order_by(AgentMemoryEntry.version)).all()
        assert [item.version for item in diet_versions] == [1, 2]
        assert [item.active for item in diet_versions] == [False, True]
    client.post(
        "/api/v1/households/hh_001/members/m_001/grants",
        json={"viewer_user_id": "u_viewer"}, headers=OWNER,
    )
    assert client.get(url, headers=VIEWER).status_code == 200
    assert client.put(url, json={"goals": ["越权修改"]}, headers=VIEWER).status_code == 403
