import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import call_model
from .config import settings
from .memory import authorize_memory_edit
from .models import AgentAction, UserNotification, WeeklyHealthReport
from .service import AuthContext, POLICY_VERSION, authorize_member_view, member_trend


def _view(row: WeeklyHealthReport) -> dict:
    return {"report_id": row.id, "member_id": row.subject_member_id,
            "period_start": row.period_start, "period_end": row.period_end,
            "status": row.status, "facts": row.facts, "summary": row.summary,
            "recommendations": row.recommendations, "policy_version": row.policy_version,
            "model_version": row.model_version, "created_at": row.created_at}


def list_reports(db: Session, auth: AuthContext, member_id: str) -> list[dict]:
    authorize_member_view(db, auth, member_id)
    rows = db.scalars(select(WeeklyHealthReport).where(
        WeeklyHealthReport.household_id == auth.household_id,
        WeeklyHealthReport.subject_member_id == member_id,
    ).order_by(WeeklyHealthReport.period_start.desc()).limit(12)).all()
    return [_view(row) for row in rows]


def generate(db: Session, auth: AuthContext, member_id: str, model_caller=call_model) -> dict:
    authorize_memory_edit(db, auth, member_id)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=today.weekday())
    existing = db.scalar(select(WeeklyHealthReport).where(
        WeeklyHealthReport.household_id == auth.household_id,
        WeeklyHealthReport.subject_member_id == member_id,
        WeeklyHealthReport.period_start == start,
    ))
    if existing:
        return _view(existing)
    trend = member_trend(db, auth.household_id, member_id, 7)
    facts = {"valid_sessions": trend["valid_sessions"],
             "coverage": trend["valid_sample_coverage"],
             "frequency_per_week": trend["frequency_per_week"],
             "consecutive_abnormal": trend["consecutive_abnormal"],
             "dimensions": trend["dimensions"]}
    insufficient = trend["insufficient_coverage"] or trend["valid_sessions"] < 3
    if insufficient:
        summary = "本周可靠样本不足，暂不做趋势判断。继续积累记录后再回看。"
        recommendations = ["保持自然记录，不必为凑数据改变生活习惯"]
        model_version = "policy-engine"
    else:
        recommendations = ["保持规律饮水与作息", "如连续异常或不适加重，请咨询医生"]
        summary = f"本周有 {trend['valid_sessions']} 次可靠记录，每周频率约 {trend['frequency_per_week']:.1f} 次。"
        model_version = "policy-engine"
        if settings.llm_api_key:
            try:
                summary = model_caller([{"role": "system", "content": "只解释给定周报事实，不诊断、不新增事实，80字内中文。"},
                                        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}])
                model_version = settings.llm_model
            except Exception:
                pass
    now = datetime.now(timezone.utc)
    row = WeeklyHealthReport(
        id=f"weekly_{uuid.uuid4().hex}", household_id=auth.household_id,
        subject_member_id=member_id, period_start=start, period_end=start + timedelta(days=6),
        status="insufficient" if insufficient else "ready", facts=facts, summary=summary,
        recommendations=recommendations, policy_version=POLICY_VERSION,
        model_version=model_version, created_by_user_id=auth.user_id, created_at=now,
    )
    db.add(row)
    action = AgentAction(
        session_id=None, subject_member_id=member_id, grant_id=None,
        action_type="weekly_report_ready", status="succeeded", recipient_id=auth.user_id,
        authorization_basis="authorized_weekly_report_generation", policy_version=POLICY_VERSION,
        model_version=model_version, input_summary={"period_start": start.isoformat()},
        result={"report_id": row.id}, idempotency_key=f"weekly-report:{auth.household_id}:{member_id}:{start}",
        created_at=now, processed_at=now,
    )
    db.add(action); db.flush()
    db.add(UserNotification(
        household_id=auth.household_id, recipient_user_id=auth.user_id,
        subject_member_id=member_id, agent_action_id=action.id,
        notification_type="weekly_report_ready", title="本周健康周报已生成",
        body=summary, priority="normal", status="unread",
        authorization_basis="authorized_weekly_report_generation",
        payload={"report_id": row.id}, created_at=now, read_at=None, acknowledged_at=None,
    ))
    db.commit()
    return _view(row)
