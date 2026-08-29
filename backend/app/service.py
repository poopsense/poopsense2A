import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    AgentAction, ApiCredential, Assessment, DeviceBinding, FamilyGrant, HouseholdMember,
    HouseholdMembership, MemberAssignment, Observation, OutboxEvent, SessionRecord,
    UserAccount,
)
from .schemas import ClaimInput, DeviceSessionInput, GrantInput


POLICY_VERSION = "safety-v1"
REDLINE_COLORS = {"red", "black", "clay"}


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    role: str
    household_id: str


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_hash(payload: DeviceSessionInput) -> str:
    raw = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def authenticate_device(db: Session, payload: DeviceSessionInput, api_key: str) -> DeviceBinding:
    binding = db.get(DeviceBinding, payload.device_id)
    if not binding or not binding.active or not hmac.compare_digest(binding.api_key_hash, hash_secret(api_key)):
        raise HTTPException(status_code=401, detail={"code": "DEVICE_AUTH_FAILED"})
    if binding.household_id != payload.household_id:
        raise HTTPException(status_code=403, detail={"code": "DEVICE_HOUSEHOLD_MISMATCH"})
    return binding


def authorize_household(
    db: Session,
    household_id: str,
    api_key: str,
    allowed_roles: set[str] | None = None,
) -> AuthContext:
    credential = db.get(ApiCredential, hash_secret(api_key))
    if not credential or not credential.active:
        raise HTTPException(status_code=401, detail={"code": "HOUSEHOLD_AUTH_FAILED"})
    user = db.get(UserAccount, credential.user_id)
    membership = db.scalar(select(HouseholdMembership).where(
        HouseholdMembership.household_id == household_id,
        HouseholdMembership.user_id == credential.user_id,
        HouseholdMembership.active.is_(True),
    ))
    if not user or not user.active or not membership:
        raise HTTPException(status_code=403, detail={"code": "HOUSEHOLD_ACCESS_DENIED"})
    if allowed_roles and membership.role not in allowed_roles:
        raise HTTPException(status_code=403, detail={"code": "HOUSEHOLD_ROLE_DENIED"})
    return AuthContext(user_id=user.id, role=membership.role, household_id=household_id)


def authorize_member_view(db: Session, auth: AuthContext, member_id: str) -> None:
    member = db.get(HouseholdMember, member_id)
    if not member or not member.active or member.household_id != auth.household_id:
        raise HTTPException(status_code=404, detail={"code": "MEMBER_NOT_FOUND"})
    if auth.role == "owner" or member.linked_user_id == auth.user_id:
        return
    grant = db.scalar(select(FamilyGrant).where(
        FamilyGrant.household_id == auth.household_id,
        FamilyGrant.subject_member_id == member_id,
        FamilyGrant.viewer_user_id == auth.user_id,
        FamilyGrant.active.is_(True),
        FamilyGrant.status == "active",
        FamilyGrant.can_view.is_(True),
    ))
    if not grant:
        raise HTTPException(status_code=403, detail={"code": "MEMBER_VIEW_NOT_AUTHORIZED"})


def evaluate_observations(
    collection_state: str,
    quality: dict,
    observations: list[Observation],
) -> tuple[bool, list[str], str]:
    reasons: list[str] = []
    if collection_state != "completed":
        reasons.append("collection_not_completed")
    if quality.get("overall_confidence", 0) < settings.reliable_confidence_threshold:
        reasons.append("overall_confidence_low")
    for observation in observations:
        if observation.value is None:
            reasons.append(f"{observation.dimension}_missing")
        elif observation.confidence is None or observation.confidence < settings.reliable_confidence_threshold:
            reasons.append(f"{observation.dimension}_confidence_low")
    if reasons:
        return False, reasons, "not_evaluated"
    color = next((item.value for item in observations if item.dimension == "color"), None)
    return True, [], "redline" if color in REDLINE_COLORS else "none_detected"


def create_assessment_version(db: Session, record: SessionRecord) -> Assessment:
    observations = db.scalars(select(Observation).where(Observation.session_id == record.id)).all()
    shape = next((item.value for item in observations if item.dimension == "shape"), None)
    current = db.scalar(select(Assessment).where(
        Assessment.session_id == record.id, Assessment.active.is_(True)
    ))
    version = 1 if current is None else current.version + 1
    if current:
        current.active = False
    reliable, reasons, risk_level = evaluate_observations(
        record.collection_state, record.quality, observations
    )
    if not reliable:
        message = "本次无法可靠判断"
    elif risk_level == "redline":
        message = "检测到需进入安全流程的信号"
    elif shape == "hard":
        message = "检测到便便呈一颗颗、偏干硬形态"
    elif shape == "loose":
        message = "检测到便便形态偏稀"
    else:
        message = "本次未检测到规则定义的红线信号"
    assessment = Assessment(
        session_id=record.id,
        version=version,
        status="assessed" if reliable else "unable_to_determine",
        reliable=reliable,
        message=message,
        risk_level=risk_level,
        policy_version=POLICY_VERSION,
        reasons=reasons,
        active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(assessment)
    return assessment


def ingest(db: Session, payload: DeviceSessionInput, api_key: str):
    authenticate_device(db, payload, api_key)
    digest = canonical_hash(payload)
    existing = db.scalar(
        select(SessionRecord).where(
            SessionRecord.device_id == payload.device_id,
            SessionRecord.external_session_id == payload.session_id,
        )
    )
    if existing:
        if existing.payload_hash != digest:
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT"})
        assignment = db.scalar(
            select(MemberAssignment).where(MemberAssignment.session_id == existing.id, MemberAssignment.active.is_(True))
        )
        assessment = db.scalar(select(Assessment).where(
            Assessment.session_id == existing.id, Assessment.active.is_(True)
        ))
        return existing, assignment, assessment, True

    received_at = datetime.now(timezone.utc)
    record = SessionRecord(
        external_session_id=payload.session_id,
        schema_version=payload.schema_version,
        correlation_id=payload.correlation_id,
        device_id=payload.device_id,
        household_id=payload.household_id,
        firmware_version=payload.firmware_version,
        model_version=payload.model_version,
        sequence_number=payload.sequence_number,
        source=payload.source,
        occurred_at=payload.timestamp,
        end_timestamp=payload.end_timestamp,
        received_at=received_at,
        duration_s=payload.duration_s,
        clock_status=payload.clock_status,
        clock_offset_ms=payload.clock_offset_ms,
        presence_state=payload.presence_state,
        collection_state=payload.collection_state,
        temperature_c=payload.temperature_c,
        humidity_pct=payload.humidity_pct,
        quality=payload.quality.model_dump(),
        member_candidates=[item.model_dump() for item in payload.member_candidates],
        payload_hash=digest,
    )
    db.add(record)
    db.flush()
    for dimension, item in payload.observations.items():
        extra = {"change_pct": item.change_pct} if item.change_pct is not None else {}
        db.add(Observation(session_id=record.id, dimension=dimension, value=item.value,
                           confidence=item.confidence, missing_reason=item.missing_reason,
                           source=item.source, model_version=item.model_version, extra=extra))
    assignment = MemberAssignment(
        session_id=record.id, version=1, assignment_status="pending_claim",
        member_id=None, candidates=[item.model_dump() for item in payload.member_candidates],
        confidence=None, claim_method=None, claimed_at=None, active=True,
    )
    db.add(assignment)
    db.flush()
    assessment = create_assessment_version(db, record)
    db.add(OutboxEvent(
        topic="session.received", aggregate_id=payload.session_id,
        payload={"session_id": payload.session_id, "household_id": payload.household_id},
        status="pending", attempts=0, idempotency_key=f"session.received:{payload.device_id}:{payload.session_id}",
        created_at=received_at, next_attempt_at=received_at,
    ))
    db.commit()
    return record, assignment, assessment, False


def claim_session(db: Session, record: SessionRecord, claim: ClaimInput):
    current = db.scalar(select(MemberAssignment).where(
        MemberAssignment.session_id == record.id, MemberAssignment.active.is_(True)
    ))
    if not current:
        raise HTTPException(status_code=409, detail={"code": "ASSIGNMENT_STATE_MISSING"})
    if current.member_id == claim.member_id and current.assignment_status == "confirmed":
        return current
    member = db.get(HouseholdMember, claim.member_id)
    if not member or not member.active or member.household_id != record.household_id:
        raise HTTPException(status_code=422, detail={"code": "INVALID_HOUSEHOLD_MEMBER"})
    db.query(AgentAction).filter(
        AgentAction.session_id == record.id,
        AgentAction.status.in_(["pending", "retry"]),
    ).update({AgentAction.status: "cancelled_by_assignment_correction"}, synchronize_session=False)
    current.active = False
    replacement = MemberAssignment(
        session_id=record.id, version=current.version + 1, assignment_status="confirmed",
        member_id=claim.member_id, candidates=current.candidates, confidence=1.0,
        claim_method=claim.claim_method, claimed_at=datetime.now(timezone.utc), active=True,
    )
    db.add_all([replacement, OutboxEvent(
        topic="assignment.confirmed", aggregate_id=record.external_session_id,
        payload={"session_id": record.external_session_id, "member_id": claim.member_id,
                 "assignment_version": replacement.version},
        status="pending", attempts=0,
        idempotency_key=f"assignment.confirmed:{record.id}:{replacement.version}",
        created_at=datetime.now(timezone.utc),
        next_attempt_at=datetime.now(timezone.utc),
    )])
    db.flush()
    queue_redline_actions(db, record, replacement)
    if settings.llm_proactive_enabled and settings.llm_api_key:
        now = datetime.now(timezone.utc)
        orchestration_key = f"agent.orchestrate:{record.id}:{replacement.version}"
        if not db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == orchestration_key)):
            db.add(OutboxEvent(
                topic="agent.orchestration.requested", aggregate_id=str(record.id),
                payload={"session_record_id": record.id, "assignment_version": replacement.version},
                status="pending", attempts=0, idempotency_key=orchestration_key,
                created_at=now, next_attempt_at=now,
            ))
    db.commit()
    return replacement


def queue_redline_actions(
    db: Session, record: SessionRecord, assignment: MemberAssignment
) -> list[AgentAction]:
    assessment = db.scalar(select(Assessment).where(
        Assessment.session_id == record.id, Assessment.active.is_(True)
    ))
    if not assessment or not assessment.reliable or assessment.risk_level != "redline":
        return []
    member = db.get(HouseholdMember, assignment.member_id)
    if not member:
        return []
    recipients: list[tuple[str, int | None, str]] = []
    if member.linked_user_id:
        recipients.append((member.linked_user_id, None, "subject_member"))
    grants = db.scalars(select(FamilyGrant).where(
        FamilyGrant.household_id == record.household_id,
        FamilyGrant.subject_member_id == member.id,
        FamilyGrant.active.is_(True),
        FamilyGrant.status == "active",
        FamilyGrant.can_view.is_(True),
        FamilyGrant.redline_notifications.is_(True),
    )).all()
    recipients.extend((grant.viewer_user_id, grant.id, f"family_grant:{grant.id}") for grant in grants)
    actions: list[AgentAction] = []
    now = datetime.now(timezone.utc)
    for recipient_id, grant_id, basis in recipients:
        key = f"redline:{record.id}:{assessment.version}:{recipient_id}"
        existing = db.scalar(select(AgentAction).where(AgentAction.idempotency_key == key))
        if existing:
            continue
        action = AgentAction(
            session_id=record.id, subject_member_id=member.id, grant_id=grant_id,
            action_type="redline_notification", status="pending", recipient_id=recipient_id,
            authorization_basis=basis, policy_version=assessment.policy_version,
            model_version=None,
            input_summary={"assessment_id": assessment.id, "risk_level": assessment.risk_level},
            result={}, idempotency_key=key, created_at=now, processed_at=None,
        )
        db.add(action)
        db.flush()
        db.add(OutboxEvent(
            topic="agent_action.dispatch", aggregate_id=str(action.id),
            payload={"action_id": action.id}, status="pending", attempts=0,
            idempotency_key=f"dispatch:{key}", created_at=now, next_attempt_at=now,
        ))
        actions.append(action)
    return actions


def grant_family_view(
    db: Session,
    auth: AuthContext,
    member_id: str,
    grant_input: GrantInput,
) -> FamilyGrant:
    member = db.get(HouseholdMember, member_id)
    viewer = db.get(UserAccount, grant_input.viewer_user_id)
    viewer_membership = db.scalar(select(HouseholdMembership).where(
        HouseholdMembership.household_id == auth.household_id,
        HouseholdMembership.user_id == grant_input.viewer_user_id,
        HouseholdMembership.active.is_(True),
    ))
    if not member or member.household_id != auth.household_id or not member.active:
        raise HTTPException(status_code=404, detail={"code": "MEMBER_NOT_FOUND"})
    if not viewer or not viewer.active or not viewer_membership:
        raise HTTPException(status_code=422, detail={"code": "VIEWER_NOT_IN_HOUSEHOLD"})
    current = db.scalar(select(FamilyGrant).where(
        FamilyGrant.household_id == auth.household_id,
        FamilyGrant.subject_member_id == member_id,
        FamilyGrant.viewer_user_id == grant_input.viewer_user_id,
        FamilyGrant.active.is_(True),
    ))
    version = 1
    if current:
        current.active = False
        current.status = "superseded"
        version = current.version + 1
    grant = FamilyGrant(
        household_id=auth.household_id, subject_member_id=member_id,
        viewer_user_id=grant_input.viewer_user_id, version=version, status="active",
        can_view=grant_input.can_view,
        redline_notifications=grant_input.redline_notifications,
        granted_by_user_id=auth.user_id, granted_at=datetime.now(timezone.utc),
        revoked_at=None, active=True,
    )
    db.add(grant)
    db.commit()
    return grant


def revoke_family_view(db: Session, auth: AuthContext, grant_id: int) -> tuple[FamilyGrant, int]:
    grant = db.get(FamilyGrant, grant_id)
    if not grant or grant.household_id != auth.household_id or not grant.active:
        raise HTTPException(status_code=404, detail={"code": "ACTIVE_GRANT_NOT_FOUND"})
    grant.status = "revoked"
    grant.active = False
    grant.revoked_at = datetime.now(timezone.utc)
    actions = db.scalars(select(AgentAction).where(
        AgentAction.grant_id == grant.id,
        AgentAction.status.in_(["pending", "retry"]),
    )).all()
    for action in actions:
        action.status = "cancelled_by_revocation"
        action.result = {"reason": "grant_revoked_before_send"}
    db.commit()
    return grant, len(actions)


def member_trend(db: Session, household_id: str, member_id: str, days: int) -> dict:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(SessionRecord, Assessment)
        .join(MemberAssignment, MemberAssignment.session_id == SessionRecord.id)
        .join(Assessment, Assessment.session_id == SessionRecord.id)
        .where(
            SessionRecord.household_id == household_id,
            SessionRecord.occurred_at >= start,
            MemberAssignment.active.is_(True),
            MemberAssignment.assignment_status == "confirmed",
            MemberAssignment.member_id == member_id,
            Assessment.active.is_(True),
        )
        .order_by(SessionRecord.occurred_at)
    ).all()
    assigned_count = len(rows)
    valid_ids = [record.id for record, assessment in rows if assessment.reliable]
    dimensions: dict[str, dict[str, int]] = {}
    observations_by_dimension: dict[str, list[Observation]] = {}
    if valid_ids:
        observations = db.scalars(select(Observation).where(
            Observation.session_id.in_(valid_ids), Observation.value.is_not(None)
        )).all()
        for item in observations:
            categories = dimensions.setdefault(item.dimension, {})
            categories[item.value] = categories.get(item.value, 0) + 1
            observations_by_dimension.setdefault(item.dimension, []).append(item)
    rendered = {}
    for dimension, categories in dimensions.items():
        total = sum(categories.values())
        rendered[dimension] = {
            "total": total,
            "categories": categories,
            "category_ratios": {key: round(value / total, 4) for key, value in categories.items()},
        }
        chronological = sorted(
            observations_by_dimension.get(dimension, []),
            key=lambda item: valid_ids.index(item.session_id),
        )
        recent_count = min(3, max(1, len(chronological) // 3))
        baseline_items = chronological[:-recent_count]
        recent_items = chronological[-recent_count:]
        if len(baseline_items) >= 3:
            baseline_counts: dict[str, int] = {}
            for item in baseline_items:
                baseline_counts[item.value] = baseline_counts.get(item.value, 0) + 1
            baseline_category = max(baseline_counts, key=baseline_counts.get)
            deviations = sum(item.value != baseline_category for item in recent_items)
            deviation_rate = round(deviations / len(recent_items), 4)
            rendered[dimension].update({
                "baseline_category": baseline_category,
                "baseline_sample_count": len(baseline_items),
                "recent_sample_count": len(recent_items),
                "baseline_deviation_rate": deviation_rate,
                "baseline_status": "deviated" if deviation_rate >= 0.5 else "within_baseline",
            })
        else:
            rendered[dimension].update({
                "baseline_category": None,
                "baseline_sample_count": len(baseline_items),
                "recent_sample_count": len(recent_items),
                "baseline_deviation_rate": None,
                "baseline_status": "insufficient",
            })
    consecutive = 0
    for record, assessment in reversed(rows):
        if not assessment.reliable:
            continue
        shape = db.scalar(select(Observation.value).where(
            Observation.session_id == record.id, Observation.dimension == "shape"
        ))
        if assessment.risk_level == "redline" or shape in {"hard", "loose"}:
            consecutive += 1
        else:
            break
    valid_count = len(valid_ids)
    coverage = valid_count / assigned_count if assigned_count else 0.0
    return {
        "household_id": household_id,
        "member_id": member_id,
        "period_days": days,
        "assigned_sessions": assigned_count,
        "valid_sessions": valid_count,
        "valid_sample_coverage": round(coverage, 4),
        "insufficient_coverage": coverage < 0.5,
        "frequency_per_week": round(valid_count / days * 7, 2),
        "consecutive_abnormal": consecutive,
        "dimensions": rendered,
    }
