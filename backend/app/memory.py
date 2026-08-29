import uuid
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentMemoryEntry, HouseholdMember
from .schemas import HealthProfileInput, MemoryCreateInput, MemoryUpdateInput
from .service import AuthContext, authorize_member_view


def authorize_memory_edit(db: Session, auth: AuthContext, member_id: str) -> None:
    member = db.get(HouseholdMember, member_id)
    if not member or not member.active or member.household_id != auth.household_id:
        raise HTTPException(status_code=404, detail={"code": "MEMBER_NOT_FOUND"})
    if auth.role != "owner" and member.linked_user_id != auth.user_id:
        raise HTTPException(status_code=403, detail={"code": "MEMORY_EDIT_NOT_AUTHORIZED"})


def list_memory(db: Session, auth: AuthContext, member_id: str,
                include_history: bool = False) -> list[AgentMemoryEntry]:
    authorize_member_view(db, auth, member_id)
    query = select(AgentMemoryEntry).where(
        AgentMemoryEntry.household_id == auth.household_id,
        AgentMemoryEntry.subject_member_id == member_id,
    )
    if not include_history:
        query = query.where(AgentMemoryEntry.active.is_(True))
    return list(db.scalars(query.order_by(
        AgentMemoryEntry.memory_key, AgentMemoryEntry.version.desc()
    )).all())


def create_self_report(db: Session, auth: AuthContext, member_id: str,
                       payload: MemoryCreateInput) -> AgentMemoryEntry:
    authorize_memory_edit(db, auth, member_id)
    entry = AgentMemoryEntry(
        logical_id=f"mem_{uuid.uuid4().hex}", household_id=auth.household_id,
        subject_member_id=member_id, version=1, source_type="self_report",
        memory_key=payload.memory_key.strip(), content=payload.content.strip(),
        authored_by_user_id=auth.user_id, correction_reason=None, active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    return entry


def update_memory(db: Session, auth: AuthContext, member_id: str, logical_id: str,
                  payload: MemoryUpdateInput) -> AgentMemoryEntry:
    authorize_memory_edit(db, auth, member_id)
    current = db.scalar(select(AgentMemoryEntry).where(
        AgentMemoryEntry.logical_id == logical_id,
        AgentMemoryEntry.household_id == auth.household_id,
        AgentMemoryEntry.subject_member_id == member_id,
        AgentMemoryEntry.active.is_(True),
    ))
    if not current:
        raise HTTPException(status_code=404, detail={"code": "ACTIVE_MEMORY_NOT_FOUND"})
    if current.source_type == "sensor_fact":
        raise HTTPException(status_code=409, detail={"code": "SENSOR_FACT_IMMUTABLE"})
    current.active = False
    replacement = AgentMemoryEntry(
        logical_id=current.logical_id, household_id=current.household_id,
        subject_member_id=current.subject_member_id, version=current.version + 1,
        source_type=current.source_type, memory_key=current.memory_key,
        content=payload.content.strip(), authored_by_user_id=auth.user_id,
        correction_reason=payload.correction_reason, active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(replacement)
    db.commit()
    return replacement


HEALTH_PROFILE_FIELDS = {
    "conditions": "health_profile.conditions",
    "diet_pattern": "health_profile.diet_pattern",
    "sleep_pattern": "health_profile.sleep_pattern",
    "medications": "health_profile.medications",
    "goals": "health_profile.goals",
}


def get_health_profile(db: Session, auth: AuthContext, member_id: str) -> dict:
    authorize_member_view(db, auth, member_id)
    entries = db.scalars(select(AgentMemoryEntry).where(
        AgentMemoryEntry.household_id == auth.household_id,
        AgentMemoryEntry.subject_member_id == member_id,
        AgentMemoryEntry.source_type == "self_report",
        AgentMemoryEntry.memory_key.in_(HEALTH_PROFILE_FIELDS.values()),
        AgentMemoryEntry.active.is_(True),
    )).all()
    by_key = {entry.memory_key: entry for entry in entries}
    values = {}
    for field, key in HEALTH_PROFILE_FIELDS.items():
        entry = by_key.get(key)
        if not entry:
            values[field] = [] if field in {"conditions", "medications", "goals"} else ""
            continue
        try:
            values[field] = json.loads(entry.content)
        except json.JSONDecodeError:
            values[field] = entry.content
    populated = sum(bool(value) for value in values.values())
    values.update({
        "member_id": member_id,
        "completeness": round(populated / len(HEALTH_PROFILE_FIELDS), 2),
        "updated_at": max((entry.created_at for entry in entries), default=None),
    })
    return values


def save_health_profile(db: Session, auth: AuthContext, member_id: str,
                        payload: HealthProfileInput) -> dict:
    authorize_memory_edit(db, auth, member_id)
    now = datetime.now(timezone.utc)
    for field, key in HEALTH_PROFILE_FIELDS.items():
        current = db.scalar(select(AgentMemoryEntry).where(
            AgentMemoryEntry.household_id == auth.household_id,
            AgentMemoryEntry.subject_member_id == member_id,
            AgentMemoryEntry.memory_key == key,
            AgentMemoryEntry.active.is_(True),
        ))
        content = json.dumps(getattr(payload, field), ensure_ascii=False)
        if current and current.content == content:
            continue
        if current:
            current.active = False
        db.add(AgentMemoryEntry(
            logical_id=current.logical_id if current else f"mem_{uuid.uuid4().hex}",
            household_id=auth.household_id, subject_member_id=member_id,
            version=current.version + 1 if current else 1,
            source_type="self_report", memory_key=key, content=content,
            authored_by_user_id=auth.user_id, correction_reason="health_profile_update",
            active=True, created_at=now,
        ))
    db.commit()
    return get_health_profile(db, auth, member_id)
