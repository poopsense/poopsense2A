import os

os.environ["POOPSENSE_DATABASE_URL"] = "sqlite:///./poopsense-test.db"
os.environ["POOPSENSE_BOOTSTRAP_DEMO_DEVICE"] = "true"
os.environ["POOPSENSE_BOOTSTRAP_DEMO_DATA"] = "false"
os.environ["POOPSENSE_INLINE_WORKER_ENABLED"] = "false"
# Keep test outbox counts deterministic even when the developer shell has a
# real model credential configured.
os.environ["POOPSENSE_LLM_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def normal_payload():
    return {
        "schema_version": "1.0", "session_id": "ses_001", "correlation_id": "cor_001",
        "device_id": "dev_001", "household_id": "hh_001", "firmware_version": "0.3.0",
        "model_version": "edge-0.2.0", "sequence_number": 42, "source": "device",
        "timestamp": "2026-08-22T08:30:12+08:00", "end_timestamp": "2026-08-22T08:31:45+08:00",
        "duration_s": 93, "clock_status": "synced", "clock_offset_ms": 120,
        "presence_state": "present", "collection_state": "completed",
        "observations": {
            "shape": {"value": "normal", "confidence": 0.76, "missing_reason": None, "source": "sensor", "model_version": "shape-0.1"},
            "color": {"value": "brown", "confidence": 0.82, "missing_reason": None, "source": "sensor", "model_version": "color-0.2"},
            "odor": {"value": "moderate", "confidence": 0.71, "change_pct": 31.2, "missing_reason": None, "source": "sensor", "model_version": "odor-0.1"},
        },
        "temperature_c": 24.8, "humidity_pct": 63.1,
        "quality": {"overall_confidence": 0.74, "reasons": []},
        "member_candidates": [{"member_ref": "m_001", "confidence": 0.58}],
    }
