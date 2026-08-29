import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .agent_native import get_or_create_profile
from .memory import authorize_memory_edit
from .models import AgentAction, AgentConnection, CommunityPost
from .service import AuthContext, POLICY_VERSION


CONSENT = "agent-match-l1-v1"


def _view(item: AgentConnection, member_id: str) -> dict:
    outbound = item.initiator_member_id == member_id
    return {
        "connection_id": item.id, "member_id": member_id,
        "other_agent_alias": item.target_alias if outbound else item.initiator_alias,
        "direction": "outbound" if outbound else "inbound", "status": item.status,
        "created_at": item.created_at,
        "can_respond": not outbound and item.status == "pending",
        "can_end": item.status in ("pending", "connected"),
    }


def _audit(db: Session, *, member_id: str, user_id: str, action: str,
           connection_id: str, basis: str, now: datetime) -> None:
    db.add(AgentAction(
        session_id=None, subject_member_id=member_id, grant_id=None,
        action_type=action, status="completed", recipient_id=user_id,
        authorization_basis=basis, policy_version=POLICY_VERSION, model_version=None,
        input_summary={"connection_id": connection_id}, result={"connection_id": connection_id},
        idempotency_key=f"{action}:{connection_id}:{uuid.uuid4().hex}",
        created_at=now, processed_at=now,
    ))


def create_request(db: Session, auth: AuthContext, member_id: str, post_id: str) -> dict:
    authorize_memory_edit(db, auth, member_id)
    post = db.get(CommunityPost, post_id)
    if not post or post.status != "active":
        raise HTTPException(status_code=404, detail={"code": "TARGET_POST_NOT_FOUND"})
    if post.subject_member_id == member_id and post.household_id == auth.household_id:
        raise HTTPException(status_code=409, detail={"code": "AGENT_MATCH_SELF"})
    existing = db.scalar(select(AgentConnection).where(
        or_(
            and_(AgentConnection.initiator_member_id == member_id, AgentConnection.target_member_id == post.subject_member_id),
            and_(AgentConnection.initiator_member_id == post.subject_member_id, AgentConnection.target_member_id == member_id),
        ), AgentConnection.status.in_(("pending", "connected")),
    ))
    if existing:
        raise HTTPException(status_code=409, detail={"code": "AGENT_MATCH_EXISTS"})
    profile = get_or_create_profile(db, auth.household_id, member_id)
    now = datetime.now(timezone.utc)
    item = AgentConnection(
        id=f"match_{uuid.uuid4().hex}", initiator_household_id=auth.household_id,
        initiator_member_id=member_id, target_household_id=post.household_id,
        target_member_id=post.subject_member_id, initiator_alias=profile.display_name,
        target_alias=post.agent_alias, status="pending", consent_version=CONSENT,
        created_by_user_id=auth.user_id, responded_by_user_id=None,
        created_at=now, responded_at=None, ended_at=None,
    )
    db.add(item)
    _audit(db, member_id=member_id, user_id=auth.user_id, action="agent_match_request",
           connection_id=item.id, basis=f"explicit_consent:{CONSENT}", now=now)
    db.commit()
    return _view(item, member_id)


def list_connections(db: Session, auth: AuthContext, member_id: str) -> list[dict]:
    authorize_memory_edit(db, auth, member_id)
    items = db.scalars(select(AgentConnection).where(or_(
        AgentConnection.initiator_member_id == member_id,
        AgentConnection.target_member_id == member_id,
    )).order_by(AgentConnection.created_at.desc())).all()
    return [_view(item, member_id) for item in items]


def respond(db: Session, auth: AuthContext, connection_id: str, member_id: str, accept: bool) -> dict:
    authorize_memory_edit(db, auth, member_id)
    item = db.get(AgentConnection, connection_id)
    if not item or item.target_member_id != member_id or item.target_household_id != auth.household_id:
        raise HTTPException(status_code=404, detail={"code": "AGENT_MATCH_NOT_FOUND"})
    if item.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "AGENT_MATCH_NOT_PENDING"})
    now = datetime.now(timezone.utc)
    item.status = "connected" if accept else "rejected"
    item.responded_by_user_id, item.responded_at = auth.user_id, now
    _audit(db, member_id=member_id, user_id=auth.user_id,
           action="agent_match_accept" if accept else "agent_match_reject",
           connection_id=item.id, basis="target_explicit_response", now=now)
    db.commit()
    return _view(item, member_id)


def end(db: Session, auth: AuthContext, connection_id: str, member_id: str) -> dict:
    authorize_memory_edit(db, auth, member_id)
    item = db.get(AgentConnection, connection_id)
    if not item or member_id not in (item.initiator_member_id, item.target_member_id):
        raise HTTPException(status_code=404, detail={"code": "AGENT_MATCH_NOT_FOUND"})
    if item.status not in ("pending", "connected"):
        raise HTTPException(status_code=409, detail={"code": "AGENT_MATCH_NOT_ACTIVE"})
    now = datetime.now(timezone.utc)
    item.status, item.ended_at = "ended", now
    _audit(db, member_id=member_id, user_id=auth.user_id, action="agent_match_end",
           connection_id=item.id, basis="connection_party", now=now)
    db.commit()
    return _view(item, member_id)
