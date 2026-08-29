from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .memory import authorize_memory_edit
from .models import Assessment, MemberAssignment, PetCheckin, PetProfile, SessionRecord
from .service import AuthContext, authorize_member_view, member_trend


def _today():
    # Product currently has one deployment timezone (China Standard Time).
    # A fixed UTC+8 offset also works on minimal Windows/Python installations
    # where the optional IANA tzdata package is not present.
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()


def _get_or_create_profile(db: Session, auth: AuthContext, member_id: str) -> PetProfile:
    authorize_member_view(db, auth, member_id)
    profile = db.scalar(select(PetProfile).where(
        PetProfile.household_id == auth.household_id,
        PetProfile.subject_member_id == member_id,
    ))
    if profile:
        return profile
    now = datetime.now(timezone.utc)
    profile = PetProfile(
        household_id=auth.household_id, subject_member_id=member_id,
        name="小噗", selected_skin="classic", version=1,
        updated_by_user_id=None, created_at=now, updated_at=now,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def pet_snapshot(db: Session, auth: AuthContext, member_id: str) -> dict:
    profile = _get_or_create_profile(db, auth, member_id)
    dates = list(db.scalars(select(PetCheckin.checkin_date).where(
        PetCheckin.household_id == auth.household_id,
        PetCheckin.subject_member_id == member_id,
    ).order_by(PetCheckin.checkin_date.desc())).all())
    today = _today()
    streak = 0
    cursor = today
    date_set = set(dates)
    while cursor in date_set:
        streak += 1
        cursor -= timedelta(days=1)
    total = len(dates)
    unlocked = ["classic"]
    if total >= 3:
        unlocked.append("blue_wave")
    if total >= 7:
        unlocked.append("pop_star")
    trend = member_trend(db, auth.household_id, member_id, 30)
    if trend["insufficient_coverage"] or trend["valid_sessions"] < 3:
        mood, basis = "curious", "insufficient"
        message = "我们还在积累可靠记录，先一起认识你的身体节奏。"
    elif trend["consecutive_abnormal"]:
        mood, basis = "concerned", "reliable_summary"
        message = "最近有连续变化，去健康页看看可靠记录，必要时咨询医生。"
    else:
        mood, basis = "cheerful", "reliable_summary"
        latest = db.scalar(
            select(Assessment).join(SessionRecord, Assessment.session_id == SessionRecord.id)
            .join(MemberAssignment, MemberAssignment.session_id == SessionRecord.id)
            .where(
                SessionRecord.household_id == auth.household_id,
                MemberAssignment.active.is_(True), MemberAssignment.member_id == member_id,
                Assessment.active.is_(True), Assessment.reliable.is_(True),
            ).order_by(SessionRecord.occurred_at.desc())
        )
        message = latest.message if latest else "今天也一起保持规律记录吧。"
    stage = "grown_up" if streak >= 7 else "companion" if streak >= 3 else "new_friend"
    return {
        "member_id": member_id, "name": profile.name,
        "selected_skin": profile.selected_skin,
        "unlocked_skins": unlocked, "mood": mood, "stage": stage,
        "message": message, "streak_days": streak, "total_checkins": total,
        "checked_in_today": today in date_set, "health_basis": basis,
        "profile_version": profile.version,
    }


def check_in(db: Session, auth: AuthContext, member_id: str) -> tuple[bool, dict]:
    authorize_memory_edit(db, auth, member_id)
    today = _today()
    existing = db.scalar(select(PetCheckin).where(
        PetCheckin.household_id == auth.household_id,
        PetCheckin.subject_member_id == member_id,
        PetCheckin.checkin_date == today,
    ))
    duplicate = existing is not None
    if not existing:
        db.add(PetCheckin(
            household_id=auth.household_id, subject_member_id=member_id,
            checkin_date=today, source="user_visit", created_by_user_id=auth.user_id,
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()
    return duplicate, pet_snapshot(db, auth, member_id)


def update_pet_profile(db: Session, auth: AuthContext, member_id: str,
                       name: str, selected_skin: str) -> dict:
    authorize_memory_edit(db, auth, member_id)
    profile = _get_or_create_profile(db, auth, member_id)
    current = pet_snapshot(db, auth, member_id)
    if selected_skin not in current["unlocked_skins"]:
        raise HTTPException(status_code=409, detail={"code": "PET_SKIN_LOCKED"})
    profile.name = name.strip()
    profile.selected_skin = selected_skin
    profile.version += 1
    profile.updated_by_user_id = auth.user_id
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    return pet_snapshot(db, auth, member_id)
