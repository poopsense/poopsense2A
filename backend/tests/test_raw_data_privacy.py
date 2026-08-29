from sqlalchemy import select

from app.database import SessionLocal
from app.models import RawDataAuthorization, RawDataUpload


OWNER = {"X-Household-Key": "household-secret"}
VIEWER = {"X-Household-Key": "viewer-secret"}
DEVICE = {"X-Device-Key": "dev-secret"}
BASE = "/api/v1/households/hh_001/raw-data-authorizations"


def grant(client):
    return client.post(BASE, headers=OWNER, json={
        "device_id": "dev_001", "purpose": "改进气味分类模型",
        "data_types": ["odor"], "retention_days": 7, "explicit_consent": True,
    })


def upload_payload(authorization_id, *, data_type="odor"):
    return {
        "authorization_id": authorization_id, "household_id": "hh_001",
        "device_id": "dev_001", "object_key": "raw/demo-001.bin",
        "data_type": data_type, "byte_size": 128, "sha256": "a" * 64,
    }


def test_raw_upload_requires_explicit_active_scoped_authorization(client):
    invalid = client.post(BASE, headers=OWNER, json={
        "device_id": "dev_001", "purpose": "改进模型", "data_types": ["odor"],
        "retention_days": 7, "explicit_consent": False,
    })
    assert invalid.status_code == 422
    unauthorized = client.post("/api/v1/raw-data-uploads", headers=DEVICE,
                               json=upload_payload("missing"))
    assert unauthorized.status_code == 403
    created = grant(client)
    assert created.status_code == 200
    authorization_id = created.json()["authorization_id"]
    wrong_type = client.post("/api/v1/raw-data-uploads", headers=DEVICE,
                             json=upload_payload(authorization_id, data_type="thermal"))
    assert wrong_type.status_code == 403
    stored = client.post("/api/v1/raw-data-uploads", headers=DEVICE,
                         json=upload_payload(authorization_id))
    duplicate = client.post("/api/v1/raw-data-uploads", headers=DEVICE,
                            json=upload_payload(authorization_id))
    assert stored.status_code == duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True


def test_revoke_stops_upload_and_tracks_cloud_deletion(client):
    authorization_id = grant(client).json()["authorization_id"]
    client.post("/api/v1/raw-data-uploads", headers=DEVICE,
                json=upload_payload(authorization_id))
    revoked = client.delete(f"{BASE}/{authorization_id}", headers=OWNER)
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["deletion_status"] == "pending"
    blocked = client.post("/api/v1/raw-data-uploads", headers=DEVICE,
                          json={**upload_payload(authorization_id), "object_key": "raw/blocked.bin"})
    assert blocked.status_code == 403
    deleted = client.post(f"{BASE}/{authorization_id}/complete-deletion", headers=OWNER)
    assert deleted.json()["deletion_status"] == "completed"
    with SessionLocal() as db:
        assert db.get(RawDataAuthorization, authorization_id).deleted_at is not None
        assert db.scalar(select(RawDataUpload).where(
            RawDataUpload.authorization_id == authorization_id)).status == "deleted"


def test_only_owner_can_manage_raw_authorization(client):
    assert client.get(BASE, headers=VIEWER).status_code == 403
    assert client.post(BASE, headers=VIEWER, json={
        "device_id": "dev_001", "purpose": "改进模型", "data_types": ["odor"],
        "retention_days": 7, "explicit_consent": True,
    }).status_code == 403
