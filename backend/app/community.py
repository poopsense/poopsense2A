import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_native import get_or_create_profile
from .memory import authorize_memory_edit
from .models import AgentAction, CommunityPost
from .service import AuthContext, POLICY_VERSION


CONSENT_VERSION = "community-explicit-v1"


def _result(post: CommunityPost, auth: AuthContext) -> dict:
    return {
        "post_id": post.id, "agent_alias": post.agent_alias, "topic": post.topic,
        "content": post.content, "status": post.status, "created_at": post.created_at,
        "can_withdraw": post.author_user_id == auth.user_id or (
            post.household_id == auth.household_id and auth.role == "owner"
        ),
    }


def list_posts(db: Session, auth: AuthContext, limit: int = 20) -> list[dict]:
    posts = db.scalars(select(CommunityPost).where(
        CommunityPost.status == "active"
    ).order_by(CommunityPost.created_at.desc()).limit(min(limit, 50))).all()
    return [_result(post, auth) for post in posts]


def publish(db: Session, auth: AuthContext, member_id: str, topic: str, content: str) -> dict:
    authorize_memory_edit(db, auth, member_id)
    profile = get_or_create_profile(db, auth.household_id, member_id)
    now = datetime.now(timezone.utc)
    post = CommunityPost(
        id=f"post_{uuid.uuid4().hex}", household_id=auth.household_id,
        subject_member_id=member_id, author_user_id=auth.user_id,
        agent_alias=profile.display_name, topic=topic, content=content.strip(),
        consent_version=CONSENT_VERSION, status="active", created_at=now,
        withdrawn_at=None,
    )
    db.add(post)
    db.add(AgentAction(
        session_id=None, subject_member_id=member_id, grant_id=None,
        action_type="community_publish", status="completed", recipient_id="anp_community",
        authorization_basis=f"explicit_consent:{CONSENT_VERSION}", policy_version=POLICY_VERSION,
        model_version=None, input_summary={"topic": topic, "length": len(content)},
        result={"post_id": post.id}, idempotency_key=f"community-publish:{post.id}",
        created_at=now, processed_at=now,
    ))
    db.commit()
    return _result(post, auth)


def withdraw(db: Session, auth: AuthContext, post_id: str) -> dict:
    post = db.get(CommunityPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail={"code": "COMMUNITY_POST_NOT_FOUND"})
    if post.author_user_id != auth.user_id and not (
        post.household_id == auth.household_id and auth.role == "owner"
    ):
        raise HTTPException(status_code=403, detail={"code": "COMMUNITY_WITHDRAW_DENIED"})
    if post.status == "active":
        now = datetime.now(timezone.utc)
        post.status, post.withdrawn_at = "withdrawn", now
        db.add(AgentAction(
            session_id=None, subject_member_id=post.subject_member_id, grant_id=None,
            action_type="community_withdraw", status="completed", recipient_id="anp_community",
            authorization_basis="author_or_household_owner", policy_version=POLICY_VERSION,
            model_version=None, input_summary={"post_id": post.id}, result={"status": "withdrawn"},
            idempotency_key=f"community-withdraw:{post.id}", created_at=now, processed_at=now,
        ))
        db.commit()
    return _result(post, auth)
