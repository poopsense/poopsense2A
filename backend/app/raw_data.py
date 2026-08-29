import hmac
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AgentAction, DeviceBinding, RawDataAuthorization, RawDataUpload
from .service import AuthContext, POLICY_VERSION, hash_secret


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _effective_status(item: RawDataAuthorization, now: datetime) -> str:
    if item.status == "active" and _as_utc(item.expires_at) <= now:
        return "expired"
    return item.status


def _expire_if_needed(db: Session, item: RawDataAuthorization, now: datetime) -> bool:
    if item.status != "active" or _as_utc(item.expires_at) > now:
        return False
    item.status = "expired"
    stored = db.scalar(select(func.count()).select_from(RawDataUpload).where(
        RawDataUpload.authorization_id == item.id, RawDataUpload.status == "stored",
    )) or 0
    item.deletion_status = "pending" if stored else "completed"
    if not stored:
        item.deleted_at = now
    return True


def _view(db: Session, item: RawDataAuthorization) -> dict:
    now = datetime.now(timezone.utc)
    status = _effective_status(item, now)
    count = db.scalar(select(func.count()).select_from(RawDataUpload).where(
        RawDataUpload.authorization_id == item.id,
    )) or 0
    return {
        "authorization_id": item.id, "device_id": item.device_id,
        "purpose": item.purpose, "data_types": item.data_types,
        "retention_days": item.retention_days, "status": status,
        "deletion_status": item.deletion_status, "upload_count": count,
        "granted_at": item.granted_at, "expires_at": item.expires_at,
        "revoked_at": item.revoked_at, "deleted_at": item.deleted_at,
    }


def list_authorizations(db: Session, auth: AuthContext) -> list[dict]:
    if auth.role != "owner":
        raise HTTPException(status_code=403, detail={"code": "HOUSEHOLD_ROLE_DENIED"})
    rows = db.scalars(select(RawDataAuthorization).where(
        RawDataAuthorization.household_id == auth.household_id,
    ).order_by(RawDataAuthorization.granted_at.desc())).all()
    now = datetime.now(timezone.utc)
    if any([_expire_if_needed(db, row, now) for row in rows]):
        db.commit()
    return [_view(db, row) for row in rows]


def create_authorization(db: Session, auth: AuthContext, payload) -> dict:
    if auth.role != "owner":
        raise HTTPException(status_code=403, detail={"code": "HOUSEHOLD_ROLE_DENIED"})
    device = db.get(DeviceBinding, payload.device_id)
    if not device or not device.active or device.household_id != auth.household_id:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND"})
    now = datetime.now(timezone.utc)
    active = db.scalar(select(RawDataAuthorization).where(
        RawDataAuthorization.household_id == auth.household_id,
        RawDataAuthorization.device_id == payload.device_id,
        RawDataAuthorization.status == "active",
        RawDataAuthorization.expires_at > now,
    ))
    if active:
        raise HTTPException(status_code=409, detail={"code": "RAW_AUTH_ALREADY_ACTIVE"})
    item = RawDataAuthorization(
        id=f"rawauth_{uuid.uuid4().hex}", household_id=auth.household_id,
        device_id=payload.device_id, purpose=payload.purpose,
        data_types=sorted(set(payload.data_types)), retention_days=payload.retention_days,
        status="active", deletion_status="not_required", granted_by_user_id=auth.user_id,
        granted_at=now, expires_at=now + timedelta(days=payload.retention_days),
        revoked_at=None, deleted_at=None,
    )
    db.add(item)
    db.add(AgentAction(
        session_id=None, subject_member_id=None, grant_id=None,
        action_type="raw_data_authorization_created", status="succeeded", recipient_id=auth.user_id,
        authorization_basis="explicit_raw_data_consent:v1", policy_version=POLICY_VERSION,
        model_version=None, input_summary={"device_id": payload.device_id, "data_types": item.data_types,
                                           "retention_days": payload.retention_days},
        result={"authorization_id": item.id}, idempotency_key=f"raw-auth-create:{item.id}",
        created_at=now, processed_at=now,
    ))
    db.commit()
    return _view(db, item)


def revoke(db: Session, auth: AuthContext, authorization_id: str) -> dict:
    if auth.role != "owner":
        raise HTTPException(status_code=403, detail={"code": "HOUSEHOLD_ROLE_DENIED"})
    item = db.get(RawDataAuthorization, authorization_id)
    if not item or item.household_id != auth.household_id:
        raise HTTPException(status_code=404, detail={"code": "RAW_AUTH_NOT_FOUND"})
    if item.status == "active":
        now = datetime.now(timezone.utc)
        item.status, item.revoked_at = "revoked", now
        stored = db.scalar(select(func.count()).select_from(RawDataUpload).where(
            RawDataUpload.authorization_id == item.id, RawDataUpload.status == "stored",
        )) or 0
        item.deletion_status = "pending" if stored else "completed"
        if not stored:
            item.deleted_at = now
        db.add(AgentAction(
            session_id=None, subject_member_id=None, grant_id=None,
            action_type="raw_data_authorization_revoked", status="succeeded", recipient_id=auth.user_id,
            authorization_basis="raw_data_consent_withdrawn", policy_version=POLICY_VERSION,
            model_version=None, input_summary={"authorization_id": item.id},
            result={"deletion_status": item.deletion_status}, idempotency_key=f"raw-auth-revoke:{item.id}",
            created_at=now, processed_at=now,
        ))
        db.commit()
    return _view(db, item)


def complete_deletion(db: Session, auth: AuthContext, authorization_id: str) -> dict:
    if auth.role != "owner":
        raise HTTPException(status_code=403, detail={"code": "HOUSEHOLD_ROLE_DENIED"})
    item = db.get(RawDataAuthorization, authorization_id)
    if not item or item.household_id != auth.household_id:
        raise HTTPException(status_code=404, detail={"code": "RAW_AUTH_NOT_FOUND"})
    if item.status == "active":
        raise HTTPException(status_code=409, detail={"code": "RAW_AUTH_STILL_ACTIVE"})
    now = datetime.now(timezone.utc)
    for upload in db.scalars(select(RawDataUpload).where(
        RawDataUpload.authorization_id == item.id, RawDataUpload.status == "stored",
    )).all():
        upload.status, upload.deleted_at = "deleted", now
    item.deletion_status, item.deleted_at = "completed", now
    db.commit()
    return _view(db, item)


def register_upload(db: Session, payload, api_key: str) -> dict:
    device = db.get(DeviceBinding, payload.device_id)
    if not device or not device.active or not hmac.compare_digest(device.api_key_hash, hash_secret(api_key)):
        raise HTTPException(status_code=401, detail={"code": "DEVICE_AUTH_FAILED"})
    if device.household_id != payload.household_id:
        raise HTTPException(status_code=403, detail={"code": "DEVICE_HOUSEHOLD_MISMATCH"})
    item = db.get(RawDataAuthorization, payload.authorization_id)
    now = datetime.now(timezone.utc)
    if not item or item.household_id != payload.household_id or item.device_id != payload.device_id:
        raise HTTPException(status_code=403, detail={"code": "RAW_UPLOAD_NOT_AUTHORIZED"})
    if _expire_if_needed(db, item, now):
        db.commit()
        raise HTTPException(status_code=403, detail={"code": "RAW_AUTH_INACTIVE"})
    if item.status != "active":
        raise HTTPException(status_code=403, detail={"code": "RAW_AUTH_INACTIVE"})
    if payload.data_type not in item.data_types:
        raise HTTPException(status_code=403, detail={"code": "RAW_DATA_TYPE_NOT_AUTHORIZED"})
    existing = db.scalar(select(RawDataUpload).where(
        RawDataUpload.device_id == payload.device_id, RawDataUpload.object_key == payload.object_key,
    ))
    if existing:
        if existing.sha256 != payload.sha256 or existing.byte_size != payload.byte_size:
            raise HTTPException(status_code=409, detail={"code": "RAW_UPLOAD_IDEMPOTENCY_CONFLICT"})
        return {"upload_id": existing.id, "status": existing.status, "duplicate": True}
    upload = RawDataUpload(
        id=f"raw_{uuid.uuid4().hex}", authorization_id=item.id,
        household_id=payload.household_id, device_id=payload.device_id,
        object_key=payload.object_key, data_type=payload.data_type,
        byte_size=payload.byte_size, sha256=payload.sha256,
        status="stored", uploaded_at=now, deleted_at=None,
    )
    db.add(upload); db.commit()
    return {"upload_id": upload.id, "status": upload.status, "duplicate": False}
