from copy import deepcopy
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Assessment, OutboxEvent, SessionRecord
from app.worker import process_one, replay_dead_letter, run_until_empty


DEVICE_HEADERS = {"X-Device-Key": "dev-secret"}
HOUSEHOLD_HEADERS = {"X-Household-Key": "household-secret"}


def upload(client, base, session_id, sequence, *, confidence=0.8, shape="normal", color="brown"):
    payload = deepcopy(base)
    payload["session_id"] = session_id
    payload["correlation_id"] = f"cor_{session_id}"
    payload["sequence_number"] = sequence
    payload["quality"]["overall_confidence"] = confidence
    for observation in payload["observations"].values():
        observation["confidence"] = confidence
    payload["observations"]["shape"]["value"] = shape
    payload["observations"]["color"]["value"] = color
    return client.post("/api/v1/device-sessions", json=payload, headers=DEVICE_HEADERS)


def claim(client, session_id, member_id="m_001", method="user_claim"):
    return client.post(
        f"/api/v1/households/hh_001/sessions/{session_id}/claim",
        json={"member_id": member_id, "claim_method": method},
        headers=HOUSEHOLD_HEADERS,
    )


def test_outbox_worker_succeeds_once_and_does_not_repeat(client, normal_payload):
    upload(client, normal_payload, "ses_worker_ok", 1)
    with SessionLocal() as db:
        assert run_until_empty(db) == 1
        event = db.scalar(select(OutboxEvent))
        assert event.status == "succeeded"
        assert event.attempts == 1
        assert event.processed_at is not None
        assert run_until_empty(db) == 0


def test_outbox_worker_retries_then_moves_to_dead_letter(client, normal_payload):
    upload(client, normal_payload, "ses_worker_fail", 1)

    def fail(_: OutboxEvent):
        raise RuntimeError("simulated downstream failure")

    with SessionLocal() as db:
        for attempt in range(1, 4):
            event = process_one(db, fail)
            assert event is not None
            assert event.attempts == attempt
            if attempt < 3:
                assert event.status == "retry"
                event.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
        assert event.status == "dead_letter"
        assert "simulated downstream failure" in event.last_error
        original_key = event.idempotency_key
        replay_dead_letter(db, event.id)
        assert event.status == "pending"
        assert event.attempts == 0
        assert event.idempotency_key == original_key
        assert process_one(db).status == "succeeded"


def test_outbox_worker_recovers_expired_processing_lease(client, normal_payload):
    upload(client, normal_payload, "ses_worker_lease", 1)
    with SessionLocal() as db:
        event = db.scalar(select(OutboxEvent))
        event.status = "processing"
        event.attempts = 1
        event.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        recovered = process_one(db)
        assert recovered.id == event.id
        assert recovered.status == "succeeded"
        assert recovered.attempts == 2


def test_reassessment_appends_version_and_keeps_history(client, normal_payload):
    upload(client, normal_payload, "ses_reassess", 1, color="red")
    response = client.post(
        "/api/v1/households/hh_001/sessions/ses_reassess/reassess",
        headers=HOUSEHOLD_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["risk_level"] == "redline"
    with SessionLocal() as db:
        versions = db.scalars(select(Assessment).order_by(Assessment.version)).all()
        assert [item.version for item in versions] == [1, 2]
        assert [item.active for item in versions] == [False, True]


def test_trends_exclude_pending_and_count_low_quality_only_in_coverage(client, normal_payload):
    upload(client, normal_payload, "ses_valid", 1, shape="normal")
    claim(client, "ses_valid")
    upload(client, normal_payload, "ses_low", 2, confidence=0.2, shape="loose")
    claim(client, "ses_low")
    upload(client, normal_payload, "ses_pending", 3, shape="hard")

    response = client.get(
        "/api/v1/households/hh_001/members/m_001/trends?days=30",
        headers=HOUSEHOLD_HEADERS,
    )
    assert response.status_code == 200
    trend = response.json()
    assert trend["assigned_sessions"] == 2
    assert trend["valid_sessions"] == 1
    assert trend["valid_sample_coverage"] == 0.5
    assert trend["dimensions"]["shape"]["categories"] == {"normal": 1}
    assert "hard" not in trend["dimensions"]["shape"]["categories"]
    assert "loose" not in trend["dimensions"]["shape"]["categories"]


def test_assignment_correction_moves_session_between_member_trends(client, normal_payload):
    upload(client, normal_payload, "ses_move", 1)
    claim(client, "ses_move", "m_001")
    claim(client, "ses_move", "m_002", "correction")
    first = client.get(
        "/api/v1/households/hh_001/members/m_001/trends", headers=HOUSEHOLD_HEADERS
    ).json()
    second = client.get(
        "/api/v1/households/hh_001/members/m_002/trends", headers=HOUSEHOLD_HEADERS
    ).json()
    assert first["assigned_sessions"] == 0
    assert second["assigned_sessions"] == 1


def test_trend_endpoint_requires_household_auth(client):
    response = client.get(
        "/api/v1/households/hh_001/members/m_001/trends",
        headers={"X-Household-Key": "wrong"},
    )
    assert response.status_code == 401


def test_personal_baseline_requires_history_then_detects_categorical_deviation(client, normal_payload):
    session_ids = [f"ses_baseline_{index}" for index in range(5)]
    for index, session_id in enumerate(session_ids):
        upload(client, normal_payload, session_id, index + 1,
               shape="hard" if index == 4 else "normal")
        claim(client, session_id)
    with SessionLocal() as db:
        records = db.scalars(select(SessionRecord).where(
            SessionRecord.external_session_id.in_(session_ids)
        )).all()
        base = datetime(2026, 8, 1, tzinfo=timezone.utc)
        for record in records:
            index = session_ids.index(record.external_session_id)
            record.occurred_at = base + timedelta(days=index)
        db.commit()
    trend = client.get(
        "/api/v1/households/hh_001/members/m_001/trends?days=60",
        headers=HOUSEHOLD_HEADERS,
    ).json()
    shape = trend["dimensions"]["shape"]
    assert shape["baseline_category"] == "normal"
    assert shape["baseline_sample_count"] == 4
    assert shape["baseline_deviation_rate"] == 1.0
    assert shape["baseline_status"] == "deviated"
