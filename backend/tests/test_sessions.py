from copy import deepcopy

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Assessment, MemberAssignment, Observation, OutboxEvent, SessionRecord


HEADERS = {"X-Device-Key": "dev-secret"}
HOUSEHOLD_HEADERS = {"X-Household-Key": "household-secret"}


def test_normal_upload_creates_auditable_facts_and_pending_claim(client, normal_payload):
    response = client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    assert response.status_code == 202
    assert response.json()["assignment_status"] == "pending_claim"
    assert response.json()["assessment_status"] == "assessed"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 1
        assert db.scalar(select(func.count()).select_from(Observation)) == 3
        assert db.scalar(select(func.count()).select_from(MemberAssignment)) == 1
        assert db.scalar(select(func.count()).select_from(Assessment)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1


def test_duplicate_upload_is_idempotent(client, normal_payload):
    first = client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    second = client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    assert first.status_code == second.status_code == 202
    assert second.json()["duplicate"] is True
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1


def test_same_key_with_changed_payload_conflicts(client, normal_payload):
    assert client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS).status_code == 202
    changed = deepcopy(normal_payload)
    changed["quality"]["overall_confidence"] = 0.8
    response = client.post("/api/v1/device-sessions", json=changed, headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_low_confidence_has_no_weak_conclusion(client, normal_payload):
    normal_payload["observations"]["odor"]["confidence"] = 0.2
    response = client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    assert response.status_code == 202
    assert response.json()["assessment_status"] == "unable_to_determine"
    assert response.json()["message"] == "本次无法可靠判断"


def test_reliable_hard_shape_preserves_the_user_facing_fact(client, normal_payload):
    normal_payload["observations"]["shape"]["value"] = "hard"
    response = client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    assert response.status_code == 202
    assert response.json()["message"] == "检测到便便呈一颗颗、偏干硬形态"


def test_reliable_sensor_facts_create_auditable_scattered_visual(client, normal_payload):
    normal_payload["observations"]["shape"]["value"] = "hard"
    client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    client.post(
        "/api/v1/households/hh_001/sessions/ses_001/claim",
        json={"member_id": "m_001"},
        headers=HOUSEHOLD_HEADERS,
    )

    response = client.get(
        "/api/v1/households/hh_001/members/m_001/sessions",
        headers=HOUSEHOLD_HEADERS,
    )
    visual = response.json()[0]["visual_profile"]
    assert visual["mapping_version"] == "poop-visual-v1"
    assert visual["variant"] == "scattered"
    assert visual["reliable"] is True
    assert visual["shape"] == {
        "value": "hard",
        "confidence": 0.76,
        "source": "sensor",
        "model_version": "shape-0.1",
    }


def test_unreliable_sensor_facts_never_select_a_specific_visual(client, normal_payload):
    normal_payload["observations"]["shape"]["value"] = "hard"
    normal_payload["observations"]["odor"]["confidence"] = 0.2
    client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    client.post(
        "/api/v1/households/hh_001/sessions/ses_001/claim",
        json={"member_id": "m_001"},
        headers=HOUSEHOLD_HEADERS,
    )

    response = client.get(
        "/api/v1/households/hh_001/members/m_001/sessions",
        headers=HOUSEHOLD_HEADERS,
    )
    visual = response.json()[0]["visual_profile"]
    assert visual["variant"] == "uncertain"
    assert visual["reliable"] is False
    assert visual["shape"] is None
    assert visual["color"] is None
    assert visual["odor"] is None


def test_missing_observation_requires_reason(client, normal_payload):
    normal_payload["observations"]["odor"]["value"] = None
    response = client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    assert response.status_code == 422


def test_household_is_verified_from_device_binding(client, normal_payload):
    normal_payload["household_id"] = "hh_attacker"
    response = client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DEVICE_HOUSEHOLD_MISMATCH"


def test_claim_and_correction_preserve_assignment_history(client, normal_payload):
    client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    inbox = client.get("/api/v1/households/hh_001/claim-inbox", headers=HOUSEHOLD_HEADERS)
    assert [item["session_id"] for item in inbox.json()] == ["ses_001"]
    first = client.post("/api/v1/households/hh_001/sessions/ses_001/claim", json={"member_id": "m_001"}, headers=HOUSEHOLD_HEADERS)
    assert first.json()["version"] == 2
    correction = client.post("/api/v1/households/hh_001/sessions/ses_001/claim", json={"member_id": "m_002", "claim_method": "correction"}, headers=HOUSEHOLD_HEADERS)
    assert correction.json()["version"] == 3
    assert client.get("/api/v1/households/hh_001/claim-inbox", headers=HOUSEHOLD_HEADERS).json() == []
    with SessionLocal() as db:
        assignments = db.scalars(select(MemberAssignment).order_by(MemberAssignment.version)).all()
        assert [a.active for a in assignments] == [False, False, True]
        assert assignments[-1].member_id == "m_002"
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 3


def test_household_endpoints_require_matching_household_key(client, normal_payload):
    client.post("/api/v1/device-sessions", json=normal_payload, headers=HEADERS)
    inbox = client.get("/api/v1/households/hh_001/claim-inbox", headers={"X-Household-Key": "wrong"})
    assert inbox.status_code == 401
    claim = client.post("/api/v1/households/hh_other/sessions/ses_001/claim",
                        json={"member_id": "m_001"}, headers=HOUSEHOLD_HEADERS)
    assert claim.status_code == 403
