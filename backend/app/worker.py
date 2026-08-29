import argparse
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import AgentAction, FamilyGrant, HouseholdMember, OutboxEvent, SessionRecord, UserNotification


EventHandler = Callable[[OutboxEvent], None]


def dispatch_outbox_event(db: Session, event: OutboxEvent) -> None:
    if event.topic == "agent.orchestration.requested":
        from .agent import orchestrate_session
        orchestrate_session(db, int(event.payload["session_record_id"]))
        return
    if event.topic != "agent_action.dispatch":
        return
    action = db.get(AgentAction, event.payload["action_id"])
    # Outbox events can outlive the action they reference. Only dispatch an action
    # that is still explicitly sendable; every cancellation state is terminal.
    if not action or action.status not in {"pending", "retry", "processing"}:
        return
    authorized = False
    if action.grant_id is not None:
        grant = db.get(FamilyGrant, action.grant_id)
        authorized = bool(
            grant and grant.active and grant.status == "active"
            and grant.can_view and grant.redline_notifications
            and grant.viewer_user_id == action.recipient_id
        )
    else:
        member = db.get(HouseholdMember, action.subject_member_id)
        authorized = bool(member and member.active and member.linked_user_id == action.recipient_id)
    if not authorized:
        action.status = "cancelled_by_revocation"
        action.result = {"reason": "authorization_invalid_at_send_time"}
        action.processed_at = datetime.now(timezone.utc)
        return
    notification = db.scalar(select(UserNotification).where(
        UserNotification.agent_action_id == action.id
    ))
    if notification is None:
        session = db.get(SessionRecord, action.session_id) if action.session_id else None
        body = str(action.result.get("message") or action.input_summary.get("message")
                   or "PoopSense 有一条新的健康提醒。")
        urgent = "redline" in action.action_type
        notification = UserNotification(
            household_id=session.household_id if session else (member.household_id if action.grant_id is None else grant.household_id),
            recipient_user_id=action.recipient_id,
            subject_member_id=action.subject_member_id,
            agent_action_id=action.id,
            notification_type=action.action_type,
            title="需要关注的身体信号" if urgent else "PoopSense 主动关怀",
            body=body, priority="urgent" if urgent else "normal", status="unread",
            authorization_basis=action.authorization_basis or "authorized_agent_action",
            payload={"policy_version": action.policy_version, "model_version": action.model_version},
            created_at=datetime.now(timezone.utc), read_at=None, acknowledged_at=None,
        )
        db.add(notification)
        db.flush()
    action.status = "succeeded"
    action.result = {**action.result, "delivery": "in_app", "notification_id": notification.id,
                     "authorized_at_send_time": True}
    action.processed_at = datetime.now(timezone.utc)


def process_one(db: Session, handler: EventHandler | None = None) -> OutboxEvent | None:
    now = datetime.now(timezone.utc)
    event = db.scalar(
        select(OutboxEvent)
        .where(
            or_(
                OutboxEvent.status.in_(["pending", "retry"]),
                and_(
                    OutboxEvent.status == "processing",
                    OutboxEvent.next_attempt_at <= now,
                ),
            ),
            OutboxEvent.next_attempt_at <= now,
        )
        .order_by(OutboxEvent.id)
        .with_for_update(skip_locked=True)
    )
    if event is None:
        return None
    if event.attempts >= settings.outbox_max_attempts:
        event.status = "dead_letter"
        event.last_error = event.last_error or "worker lease expired after maximum attempts"
        db.commit()
        return event
    event.status = "processing"
    event.attempts += 1
    event.next_attempt_at = now + timedelta(seconds=settings.outbox_lease_seconds)
    db.commit()
    try:
        (handler or (lambda item: dispatch_outbox_event(db, item)))(event)
    except Exception as exc:
        event.last_error = str(exc)[:2000]
        if event.attempts >= settings.outbox_max_attempts:
            event.status = "dead_letter"
        else:
            event.status = "retry"
            delay = settings.outbox_retry_base_seconds * (2 ** (event.attempts - 1))
            event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        db.commit()
        return event
    event.status = "succeeded"
    event.processed_at = datetime.now(timezone.utc)
    event.last_error = None
    db.commit()
    return event


def replay_dead_letter(db: Session, event_id: int) -> OutboxEvent:
    event = db.get(OutboxEvent, event_id)
    if event is None:
        raise ValueError("outbox event not found")
    if event.status != "dead_letter":
        raise ValueError("only dead-letter events can be replayed")
    event.status = "pending"
    event.attempts = 0
    event.last_error = None
    event.processed_at = None
    event.next_attempt_at = datetime.now(timezone.utc)
    db.commit()
    return event


def run_until_empty(db: Session, handler: EventHandler | None = None, limit: int = 100) -> int:
    processed = 0
    while processed < limit and process_one(db, handler) is not None:
        processed += 1
    return processed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--replay-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as session:
        if args.replay_id is not None:
            replayed = replay_dead_letter(session, args.replay_id)
            print(f"replayed={replayed.id} idempotency_key={replayed.idempotency_key}")
        print(f"processed={run_until_empty(session, limit=args.limit)}")
