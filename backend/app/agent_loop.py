import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentHandoff, AgentRun, AgentStep


MAX_AGENT_STEPS = 4


def start_chat_run(db: Session, *, household_id: str, member_id: str,
                   conversation_id: str, user_id: str, goal: str,
                   authorization_basis: str, delegated_agent: str,
                   skill: str, skill_version: str,
                   context_domains: tuple[str, ...],
                   policy_version: str) -> tuple[AgentRun, AgentStep]:
    now = datetime.now(timezone.utc)
    run = AgentRun(
        id=f"run_{uuid.uuid4().hex}", household_id=household_id,
        subject_member_id=member_id, conversation_id=conversation_id,
        trigger="user_message", goal=goal, status="running", current_step=1,
        max_steps=MAX_AGENT_STEPS, created_by_user_id=user_id,
        policy_version=policy_version, authorization_basis=authorization_basis,
        result={}, error=None, created_at=now, updated_at=now, completed_at=None,
    )
    coordinator = AgentStep(
        run_id=run.id, step_index=1, agent_name="main_agent",
        skill_name="route_request", skill_version="1.0.0", status="succeeded",
        input_summary={"goal": goal[:500]},
        output_summary={"delegated_agent": delegated_agent, "skill": skill},
        authorization_basis=authorization_basis, started_at=now, completed_at=now,
    )
    specialist = AgentStep(
        run_id=run.id, step_index=2, agent_name=delegated_agent,
        skill_name=skill, skill_version=skill_version, status="running",
        input_summary={"delegated_by": "main_agent"}, output_summary={},
        authorization_basis=authorization_basis, started_at=now, completed_at=None,
    )
    handoff = AgentHandoff(
        run_id=run.id, from_step_index=1, to_step_index=2,
        from_agent="main_agent", to_agent=delegated_agent,
        skill_name=skill, skill_version=skill_version,
        context_domains=list(context_domains),
        payload={"goal_summary": goal[:500]},
        authorization_basis=authorization_basis, status="accepted",
        created_at=now, accepted_at=now,
    )
    db.add_all([run, coordinator, specialist, handoff])
    run.current_step = 2
    db.flush()
    return run, specialist


def finish_run(db: Session, run: AgentRun, step: AgentStep, output: dict) -> None:
    now = datetime.now(timezone.utc)
    step.status = "succeeded"
    step.output_summary = output
    step.completed_at = now
    run.status = "completed"
    run.result = output
    run.updated_at = now
    run.completed_at = now


def pause_run(db: Session, run: AgentRun, step: AgentStep, reason: str) -> None:
    now = datetime.now(timezone.utc)
    step.status = "waiting_input"
    step.output_summary = {"pause_reason": reason}
    run.status = "paused"
    run.result = {"waiting_for": "user_confirmation", "reason": reason}
    run.updated_at = now


def resume_run(db: Session, run: AgentRun, step: AgentStep) -> None:
    if run.status != "paused" or step.status != "waiting_input":
        raise ValueError("run is not waiting for input")
    now = datetime.now(timezone.utc)
    run.status = "running"
    run.updated_at = now
    step.status = "running"
    step.started_at = step.started_at or now


def cancel_run(db: Session, run: AgentRun, step: AgentStep, reason: str) -> None:
    now = datetime.now(timezone.utc)
    step.status = "cancelled"
    step.output_summary = {"reason": reason}
    step.completed_at = now
    run.status = "cancelled"
    run.result = {"reason": reason}
    run.updated_at = now
    run.completed_at = now


def fail_run(db: Session, run: AgentRun, step: AgentStep, error: str) -> None:
    now = datetime.now(timezone.utc)
    step.status = "failed"
    step.error = error[:500]
    step.completed_at = now
    run.status = "failed"
    run.error = error[:500]
    run.updated_at = now
    run.completed_at = now


def list_steps(db: Session, run_id: str) -> list[AgentStep]:
    return list(db.scalars(select(AgentStep).where(
        AgentStep.run_id == run_id
    ).order_by(AgentStep.step_index)).all())


def list_handoffs(db: Session, run_id: str) -> list[AgentHandoff]:
    return list(db.scalars(select(AgentHandoff).where(
        AgentHandoff.run_id == run_id
    ).order_by(AgentHandoff.from_step_index, AgentHandoff.to_step_index)).all())
