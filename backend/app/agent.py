import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AgentAction, AgentConversation, AgentFeedback, AgentHandoff, AgentMemoryEntry, AgentMessage, AgentRun, AgentStep, Assessment, MemberAssignment, OutboxEvent, SessionRecord
from .service import AuthContext, POLICY_VERSION, authorize_member_view, member_trend
from .agent_native import AGENT_SPECS, get_or_create_profile, in_quiet_hours, route_skill
from .agent_loop import cancel_run, fail_run, finish_run, pause_run, resume_run, start_chat_run
from .skills import (
    contract_for, should_pause_for_confirmation, validate_skill_input,
    validate_skill_output,
)


RED_FLAG_WORDS = {"血便", "出血", "黑便", "剧痛", "昏厥", "意识异常", "高烧"}


def parse_model_decision(raw: str) -> dict[str, Any]:
    """Accept JSON-only replies and the common fenced-JSON provider variant."""
    candidate = raw.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise HTTPException(status_code=502, detail={"code": "MODEL_INVALID_DECISION"})
        try:
            value = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail={"code": "MODEL_INVALID_DECISION"}) from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail={"code": "MODEL_INVALID_DECISION"})
    return value


def authorization_basis(db: Session, auth: AuthContext, member_id: str) -> str:
    authorize_member_view(db, auth, member_id)
    from .models import FamilyGrant, HouseholdMember
    member = db.get(HouseholdMember, member_id)
    if auth.role == "owner":
        return "household_owner"
    if member and member.linked_user_id == auth.user_id:
        return "subject_self"
    grant = db.scalar(select(FamilyGrant).where(
        FamilyGrant.household_id == auth.household_id,
        FamilyGrant.subject_member_id == member_id,
        FamilyGrant.viewer_user_id == auth.user_id,
        FamilyGrant.active.is_(True), FamilyGrant.status == "active",
        FamilyGrant.can_view.is_(True),
    ))
    return f"family_grant:{grant.id}"


def safety_decision(message: str) -> tuple[str, list[str]]:
    if any(word in message for word in RED_FLAG_WORDS):
        return "urgent_care", ["explain_safety_limit", "recommend_urgent_care"]
    if any(word in message for word in ("趋势", "最近", "记录")):
        return "explain_trend", ["read_authorized_trend", "explain"]
    if any(word in message for word in ("喝水", "饮水", "补水", "水分")):
        return "health_education", ["explain", "ask_follow_up", "offer_water_pickup"]
    return "health_education", ["explain", "ask_follow_up"]


def call_model(messages: list[dict[str, str]]) -> str:
    if not settings.llm_api_key:
        raise HTTPException(status_code=503, detail={"code": "MODEL_NOT_CONFIGURED"})
    try:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "messages": messages, "temperature": 0.2},
            timeout=settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "MODEL_PROVIDER_FAILED"}) from exc


def chat(db: Session, auth: AuthContext, member_id: str, text: str,
         conversation_id: str | None = None, model_caller=call_model) -> dict[str, Any]:
    basis = authorization_basis(db, auth, member_id)
    now = datetime.now(timezone.utc)
    conversation = db.get(AgentConversation, conversation_id) if conversation_id else None
    if conversation and (conversation.household_id != auth.household_id or
                         conversation.created_by_user_id != auth.user_id or
                         conversation.subject_member_id != member_id):
        raise HTTPException(status_code=403, detail={"code": "CONVERSATION_ACCESS_DENIED"})
    if not conversation:
        conversation = AgentConversation(
            id=f"conv_{uuid.uuid4().hex}", household_id=auth.household_id,
            subject_member_id=member_id, created_by_user_id=auth.user_id,
            status="active", created_at=now, updated_at=now,
        )
        db.add(conversation)
    user_message = AgentMessage(
        conversation_id=conversation.id, role="user", content=text,
        model_version=None, authorization_basis=basis, policy_version=POLICY_VERSION,
        message_metadata={}, created_at=now,
    )
    db.add(user_message)
    db.flush()
    decision, allowed = safety_decision(text)
    delegated_agent, skill = route_skill(text, decision)
    contract = contract_for(skill)
    if contract.agent != delegated_agent:
        raise HTTPException(status_code=500, detail={"code": "SKILL_AGENT_MISMATCH"})
    skill_input = {"goal": text, "member_id": member_id, "decision": decision}
    validate_skill_input(contract, skill_input, auth.role)
    profile = get_or_create_profile(db, auth.household_id, member_id)
    feedback_rows = db.scalars(select(AgentFeedback).where(
        AgentFeedback.household_id == auth.household_id,
        AgentFeedback.subject_member_id == member_id,
        AgentFeedback.created_by_user_id == auth.user_id,
    ).order_by(AgentFeedback.updated_at.desc()).limit(20)).all()
    feedback_context = {
        "helpful_count": sum(item.rating == "helpful" for item in feedback_rows),
        "not_helpful_count": sum(item.rating == "not_helpful" for item in feedback_rows),
        "recent_reasons": [item.reason for item in feedback_rows if item.reason][:3],
    }
    run, specialist_step = start_chat_run(
        db, household_id=auth.household_id, member_id=member_id,
        conversation_id=conversation.id, user_id=auth.user_id, goal=text,
        authorization_basis=basis, delegated_agent=delegated_agent, skill=skill,
        skill_version=contract.version,
        context_domains=contract.context_domains,
        policy_version=POLICY_VERSION,
    )
    if should_pause_for_confirmation(contract, text):
        pause_run(db, run, specialist_step, "high_impact_household_action")
        assistant = AgentMessage(
            conversation_id=conversation.id, role="assistant",
            content="这项家庭操作会改变成员归属或授权。请确认继续，或取消本次任务。",
            model_version="policy-engine", authorization_basis=basis,
            policy_version=POLICY_VERSION,
            message_metadata={
                "decision": decision, "delegated_agent": delegated_agent,
                "skill": skill, "skill_version": contract.version,
                "waiting_for": "user_confirmation",
            }, created_at=datetime.now(timezone.utc),
        )
        db.add(assistant)
        conversation.updated_at = assistant.created_at
        audit = AgentAction(
            session_id=None, subject_member_id=member_id, grant_id=None,
            action_type="agent_waiting_confirmation", status="waiting_input",
            recipient_id=auth.user_id, authorization_basis=basis,
            policy_version=POLICY_VERSION, model_version=None,
            input_summary={"run_id": run.id, "skill": skill,
                           "skill_version": contract.version},
            result={"waiting_for": "user_confirmation"},
            idempotency_key=f"agent-wait:{run.id}", created_at=now, processed_at=now,
        )
        db.add(audit)
        db.commit()
        db.refresh(assistant)
        return {
            "conversation": conversation, "message": assistant,
            "decision": decision, "allowed_actions": allowed,
            "authorization_basis": basis, "delegated_agent": delegated_agent,
            "skill": skill, "skill_version": contract.version, "run": run,
        }
    if delegated_agent == "household_steward":
        safe_context = {
            "decision": decision, "allowed_actions": allowed,
            "household_scope": {"household_id": auth.household_id, "member_id": member_id},
        }
    else:
        trend = member_trend(db, auth.household_id, member_id, 30)
        memory_query = select(AgentMemoryEntry).where(
            AgentMemoryEntry.household_id == auth.household_id,
            AgentMemoryEntry.subject_member_id == member_id,
            AgentMemoryEntry.active.is_(True),
        )
        if delegated_agent == "life_coach":
            memory_query = memory_query.where(AgentMemoryEntry.source_type == "self_report")
            safe_context = {
                "decision": decision, "allowed_actions": allowed, "trend": trend,
                "feedback_preferences": feedback_context,
                "self_report_memory": [
                    {"source": item.source_type, "key": item.memory_key,
                     "content": item.content, "version": item.version}
                    for item in db.scalars(memory_query).all()
                ],
            }
        else:
            recent = db.execute(
                select(SessionRecord, Assessment)
                .join(MemberAssignment, MemberAssignment.session_id == SessionRecord.id)
                .join(Assessment, Assessment.session_id == SessionRecord.id)
                .where(MemberAssignment.active.is_(True), MemberAssignment.member_id == member_id,
                       Assessment.active.is_(True))
                .order_by(SessionRecord.occurred_at.desc()).limit(5)
            ).all()
            safe_context = {
                "decision": decision, "allowed_actions": allowed, "trend": trend,
                "feedback_preferences": feedback_context,
                "recent_assessments": [
                    {"at": r.occurred_at.isoformat(), "status": a.status,
                     "risk_level": a.risk_level, "message": a.message}
                    for r, a in recent
                ],
                "visible_memory": [
                    {"source": item.source_type, "key": item.memory_key,
                     "content": item.content, "version": item.version}
                    for item in db.scalars(memory_query).all()
                ],
            }
    system = (
        f"你是 {profile.display_name} 的主 Agent，当前委派给 {delegated_agent} 执行 {skill} skill。"
        f"专业职责：{AGENT_SPECS[delegated_agent]['purpose']}。"
        f"你的 Soul：{json.dumps(profile.soul, ensure_ascii=False)}。"
        "规则引擎已经决定风险等级和允许动作；"
        "你只能在 allowed_actions 内组织语言，不得诊断、改写风险等级、扩大接收人或执行未授权动作。"
        "若 decision=urgent_care，必须明确建议尽快线下就医；严重或紧急症状建议急诊。"
        "低质量或缺失数据必须明确说无法可靠判断。回答简洁、中文。\n"
        f"安全上下文：{json.dumps(safe_context, ensure_ascii=False)}"
    )
    audit = AgentAction(
        session_id=None, subject_member_id=member_id, grant_id=(int(basis.split(":")[1]) if basis.startswith("family_grant:") else None),
        action_type="agent_chat_response", status="processing", recipient_id=auth.user_id,
        authorization_basis=basis, policy_version=POLICY_VERSION, model_version=settings.llm_model,
        input_summary={"conversation_id": conversation.id, "message_id": user_message.id,
                       "decision": decision, "allowed_actions": allowed,
                       "delegated_agent": delegated_agent, "skill": skill,
                       "skill_version": contract.version},
        result={}, idempotency_key=f"agent-chat:{conversation.id}:{user_message.id}",
        created_at=now, processed_at=None,
    )
    db.add(audit)
    db.commit()
    try:
        reply = model_caller([{"role": "system", "content": system}, {"role": "user", "content": text}])
        validate_skill_output(contract, {"reply": reply, "decision": decision})
        if skill == "comprehensive_review":
            review_now = datetime.now(timezone.utc)
            specialist_step.status = "succeeded"
            specialist_step.output_summary = {"role": "risk_review", "reply_length": len(reply)}
            specialist_step.completed_at = review_now
            coach_step = AgentStep(
                run_id=run.id, step_index=3, agent_name="life_coach",
                skill_name="lifestyle_coaching", skill_version="1.0.0", status="running",
                input_summary={"delegated_by": "health_doctor", "domains": ["trend", "self_report_memory"]},
                output_summary={}, authorization_basis=basis, started_at=review_now, completed_at=None,
            )
            db.add(coach_step)
            db.add(AgentHandoff(
                run_id=run.id, from_step_index=2, to_step_index=3,
                from_agent="health_doctor", to_agent="life_coach",
                skill_name="lifestyle_coaching", skill_version="1.0.0",
                context_domains=["trend", "self_report_memory", "feedback_preferences"],
                payload={"goal_summary": text[:500]}, authorization_basis=basis,
                status="accepted", created_at=review_now, accepted_at=review_now,
            ))
            self_reports = db.scalars(select(AgentMemoryEntry).where(
                AgentMemoryEntry.household_id == auth.household_id,
                AgentMemoryEntry.subject_member_id == member_id,
                AgentMemoryEntry.active.is_(True), AgentMemoryEntry.source_type == "self_report",
            )).all()
            coach_context = {"trend": trend, "self_report_memory": [
                {"key": item.memory_key, "content": item.content, "version": item.version}
                for item in self_reports
            ], "allowed_actions": allowed}
            coach_reply = model_caller([
                {"role": "system", "content": "你是生活教练，只给低风险饮水、饮食、运动与作息行动，不诊断。只能使用以下最小上下文：" + json.dumps(coach_context, ensure_ascii=False)},
                {"role": "user", "content": text},
            ])
            coach_step.status = "succeeded"
            coach_step.output_summary = {"role": "lifestyle_review", "reply_length": len(coach_reply)}
            coach_step.completed_at = datetime.now(timezone.utc)
            arbiter_step = AgentStep(
                run_id=run.id, step_index=4, agent_name="safety_arbiter",
                skill_name="deterministic_arbitration", skill_version="1.0.0", status="succeeded",
                input_summary={"decision": decision, "allowed_actions": allowed},
                output_summary={"precedence": "policy_then_health_then_lifestyle"},
                authorization_basis=basis, started_at=coach_step.completed_at,
                completed_at=coach_step.completed_at,
            )
            db.add(arbiter_step)
            db.add(AgentHandoff(
                run_id=run.id, from_step_index=3, to_step_index=4,
                from_agent="life_coach", to_agent="safety_arbiter",
                skill_name="deterministic_arbitration", skill_version="1.0.0",
                context_domains=["policy_decision", "expert_summaries"],
                payload={"decision": decision}, authorization_basis=basis,
                status="accepted", created_at=coach_step.completed_at, accepted_at=coach_step.completed_at,
            ))
            reply = f"健康医生复核：{reply}\n\n生活教练建议：{coach_reply}\n\n安全仲裁：以上内容受规则引擎约束，健康风险结论优先。"
            specialist_step = arbiter_step
    except HTTPException as exc:
        fail_run(db, run, specialist_step, str(exc.detail))
        audit.status = "failed"
        audit.result = {"error": exc.detail}
        audit.processed_at = datetime.now(timezone.utc)
        db.commit()
        raise
    assistant = AgentMessage(
        conversation_id=conversation.id, role="assistant", content=reply,
        model_version=settings.llm_model, authorization_basis=basis,
        policy_version=POLICY_VERSION, message_metadata={
            "decision": decision, "allowed_actions": allowed,
            "delegated_agent": delegated_agent, "skill": skill,
            "skill_version": contract.version,
            "context_domains": list(contract.context_domains),
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(assistant)
    conversation.updated_at = assistant.created_at
    audit.status = "succeeded"
    audit.result = {"assistant_message_pending_id": True, "decision": decision}
    audit.processed_at = assistant.created_at
    finish_run(db, run, specialist_step, {
        "decision": decision, "delegated_agent": delegated_agent,
        "skill": skill, "skill_version": contract.version,
        "assistant_message_pending_id": True,
    })
    db.commit()
    db.refresh(assistant)
    audit.result = {"assistant_message_id": assistant.id, "decision": decision,
                    "delegated_agent": delegated_agent, "skill": skill}
    db.commit()
    return {"conversation": conversation, "message": assistant, "decision": decision,
            "allowed_actions": allowed, "authorization_basis": basis,
            "delegated_agent": delegated_agent, "skill": skill,
            "skill_version": contract.version, "run": run}


def resume_paused_chat(db: Session, auth: AuthContext, run_id: str, confirmed: bool,
                       model_caller=call_model) -> dict[str, Any]:
    run = db.get(AgentRun, run_id)
    if not run or run.household_id != auth.household_id:
        raise HTTPException(status_code=404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    if auth.role != "owner" and run.created_by_user_id != auth.user_id:
        raise HTTPException(status_code=403, detail={"code": "AGENT_RUN_PRIVATE"})
    if not run.subject_member_id:
        raise HTTPException(status_code=409, detail={"code": "RUN_HAS_NO_MEMBER"})
    basis = authorization_basis(db, auth, run.subject_member_id)
    step = db.scalar(select(AgentStep).where(
        AgentStep.run_id == run.id, AgentStep.status == "waiting_input"
    ).order_by(AgentStep.step_index.desc()))
    if not step or run.status != "paused":
        raise HTTPException(status_code=409, detail={"code": "RUN_NOT_WAITING_INPUT"})
    contract = contract_for(step.skill_name)
    validate_skill_input(contract, {
        "goal": run.goal, "member_id": run.subject_member_id,
        "decision": "confirmed_household_action",
    }, auth.role)
    conversation = db.get(AgentConversation, run.conversation_id)
    if not conversation:
        raise HTTPException(status_code=409, detail={"code": "RUN_CONVERSATION_MISSING"})
    now = datetime.now(timezone.utc)
    waiting_audit = db.scalar(select(AgentAction).where(
        AgentAction.idempotency_key == f"agent-wait:{run.id}"
    ))
    if not confirmed:
        cancel_run(db, run, step, "cancelled_by_user")
        reply = "已取消，本次没有执行任何家庭变更。"
        model_version = "policy-engine"
        if waiting_audit:
            waiting_audit.status = "cancelled_by_user"
            waiting_audit.result = {"reason": "cancelled_by_user"}
    else:
        resume_run(db, run, step)
        system = (
            "你是家庭管家。用户已明确确认继续当前家庭事务。"
            "只解释下一步和所需信息，不得自行更改授权、归属或成员；"
            "真正的变更必须由后端受权工具执行。回答简洁、中文。"
            f"\n任务：{run.goal}\n授权依据：{basis}"
        )
        try:
            reply = model_caller([
                {"role": "system", "content": system},
                {"role": "user", "content": "我确认继续"},
            ])
            validate_skill_output(contract, {
                "reply": reply, "decision": "confirmed_household_action"
            })
        except HTTPException as exc:
            fail_run(db, run, step, str(exc.detail))
            db.commit()
            raise
        finish_run(db, run, step, {
            "confirmed": True, "skill": contract.name,
            "skill_version": contract.version, "reply": reply,
        })
        model_version = settings.llm_model
        if waiting_audit:
            waiting_audit.status = "succeeded"
            waiting_audit.result = {"confirmed": True, "completed_run_id": run.id}
    assistant = AgentMessage(
        conversation_id=conversation.id, role="assistant", content=reply,
        model_version=model_version, authorization_basis=basis,
        policy_version=POLICY_VERSION,
        message_metadata={"run_id": run.id, "resumed": confirmed,
                          "skill": contract.name, "skill_version": contract.version},
        created_at=now,
    )
    db.add(assistant)
    conversation.updated_at = now
    db.commit()
    db.refresh(assistant)
    return {"run": run, "message": assistant}


def orchestrate_session(db: Session, session_record_id: int, model_caller=call_model) -> AgentAction:
    record = db.get(SessionRecord, session_record_id)
    assignment = db.scalar(select(MemberAssignment).where(
        MemberAssignment.session_id == session_record_id, MemberAssignment.active.is_(True),
        MemberAssignment.assignment_status == "confirmed",
    ))
    assessment = db.scalar(select(Assessment).where(
        Assessment.session_id == session_record_id, Assessment.active.is_(True),
    ))
    if not record or not assignment or not assessment:
        raise ValueError("session is not ready for orchestration")
    if not assessment.reliable:
        allowed = ["no_action"]
    elif assessment.risk_level == "redline":
        allowed = ["redline_notification"]
    else:
        allowed = ["no_action", "send_check_in"]
    prompt = (
        "从 allowed_actions 中选择且只能选择一个动作，返回严格 JSON："
        '{"action":"...","reason":"...","message":"..."}。'
        f"\n{json.dumps({'allowed_actions': allowed, 'assessment': {'status': assessment.status, 'risk_level': assessment.risk_level, 'message': assessment.message}}, ensure_ascii=False)}"
    )
    raw = model_caller([
        {"role": "system", "content": "你是受确定性安全护栏约束的调度器，不得发明动作。"},
        {"role": "user", "content": prompt},
    ])
    decision = parse_model_decision(raw)
    selected = decision.get("action")
    if selected not in allowed:
        raise HTTPException(status_code=502, detail={"code": "MODEL_ACTION_NOT_ALLOWED"})
    member_id = assignment.member_id
    from .models import HouseholdMember
    member = db.get(HouseholdMember, member_id)
    now = datetime.now(timezone.utc)
    profile = get_or_create_profile(db, record.household_id, member_id)
    if selected == "send_check_in":
        if not profile.proactive_enabled:
            selected = "no_action"
            decision["reason"] = "member_proactive_disabled"
        elif in_quiet_hours(profile, now):
            selected = "no_action"
            decision["reason"] = "member_quiet_hours"
        else:
            since = now - timedelta(hours=24)
            # SQLAlchemy count is expressed explicitly for portability.
            from sqlalchemy import func
            sent = db.scalar(select(func.count(AgentAction.id)).where(
                AgentAction.subject_member_id == member_id,
                AgentAction.action_type == "llm_send_check_in",
                AgentAction.created_at >= since,
                AgentAction.status.in_(["pending", "processing", "succeeded"]),
            )) or 0
            if sent >= profile.daily_non_redline_limit:
                selected = "no_action"
                decision["reason"] = "daily_proactive_limit_reached"
    key = f"orchestration:{record.id}:{assignment.version}:{selected}"
    existing = db.scalar(select(AgentAction).where(AgentAction.idempotency_key == key))
    if existing:
        return existing
    status = "pending" if selected == "send_check_in" and member and member.linked_user_id else "succeeded"
    action = AgentAction(
        session_id=record.id, subject_member_id=member_id, grant_id=None,
        action_type=f"llm_{selected}", status=status,
        recipient_id=member.linked_user_id if member else None,
        authorization_basis="subject_member" if member and member.linked_user_id else "policy_only",
        policy_version=POLICY_VERSION, model_version=settings.llm_model,
        input_summary={"assessment_id": assessment.id, "allowed_actions": allowed},
        result={"reason": decision.get("reason", ""), "message": decision.get("message", "")},
        idempotency_key=key, created_at=now,
        processed_at=None if status == "pending" else now,
    )
    db.add(action)
    db.flush()
    if status == "pending":
        db.add(OutboxEvent(
            topic="agent_action.dispatch", aggregate_id=str(action.id),
            payload={"action_id": action.id}, status="pending", attempts=0,
            idempotency_key=f"dispatch:{key}", created_at=now, next_attempt_at=now,
        ))
    db.commit()
    return action
