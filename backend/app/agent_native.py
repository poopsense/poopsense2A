from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentProfile, AgentProfileRevision
from .skills import SKILL_CONTRACTS


SKILLS = SKILL_CONTRACTS


def profile_snapshot(profile: AgentProfile) -> dict:
    return {
        "display_name": profile.display_name,
        "soul": profile.soul,
        "proactive_enabled": profile.proactive_enabled,
        "daily_non_redline_limit": profile.daily_non_redline_limit,
        "quiet_start": profile.quiet_start,
        "quiet_end": profile.quiet_end,
        "timezone": profile.timezone,
    }

AGENT_SPECS = {
    "health_doctor": {
        "purpose": "解释已授权健康信号并执行安全分诊沟通",
        "context_domains": ["trend", "recent_assessments", "visible_memory"],
    },
    "life_coach": {
        "purpose": "围绕饮水、饮食、运动和习惯提供非诊断建议",
        "context_domains": ["trend", "self_report_memory"],
    },
    "household_steward": {
        "purpose": "处理成员、认领、授权和家庭空间事务",
        "context_domains": ["household_scope"],
    },
}


def get_or_create_profile(db: Session, household_id: str, member_id: str | None) -> AgentProfile:
    profile = db.scalar(select(AgentProfile).where(
        AgentProfile.household_id == household_id,
        AgentProfile.subject_member_id == member_id,
    ))
    if profile:
        return profile
    profile = AgentProfile(
        household_id=household_id, subject_member_id=member_id,
        display_name="PoopSense" if member_id else "家庭管家",
        soul={"tone": "温柔、直接、不说教", "relationship_goal": "长期理解身体节奏"},
        proactive_enabled=True, daily_non_redline_limit=1,
        quiet_start="22:00", quiet_end="08:00", timezone="Asia/Shanghai",
        version=1, updated_at=datetime.now(timezone.utc),
    )
    db.add(profile)
    db.flush()
    db.add(AgentProfileRevision(
        profile_id=profile.id, household_id=household_id, subject_member_id=member_id,
        version=profile.version, snapshot=profile_snapshot(profile), changed_by_user_id=None,
        change_reason="profile_created", created_at=profile.updated_at,
    ))
    db.commit()
    db.refresh(profile)
    return profile


def route_skill(message: str, decision: str) -> tuple[str, str]:
    if any(word in message for word in ("家庭", "成员", "授权", "认领")):
        return "household_steward", "manage_household"
    if decision == "urgent_care":
        return "health_doctor", "urgent_care"
    if any(word in message for word in ("综合分析", "一起分析", "第二意见", "多专家")):
        return "health_doctor", "comprehensive_review"
    if decision == "explain_trend":
        return "health_doctor", "summarize_trend"
    if any(word in message for word in ("饮水", "喝水", "饮食", "吃饭", "运动", "习惯")):
        return "life_coach", "lifestyle_coaching"
    return "health_doctor", "health_education"


def in_quiet_hours(profile: AgentProfile, now: datetime | None = None) -> bool:
    try:
        zone = ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError:
        zone = timezone(timedelta(hours=8)) if profile.timezone == "Asia/Shanghai" else timezone.utc
    local = (now or datetime.now(timezone.utc)).astimezone(zone).time()
    start = time.fromisoformat(profile.quiet_start)
    end = time.fromisoformat(profile.quiet_end)
    return start <= local < end if start < end else local >= start or local < end
