from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class DeviceBinding(Base):
    __tablename__ = "device_bindings"

    device_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    household_id: Mapped[str] = mapped_column(String(100), index=True)
    api_key_hash: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserAccount(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class HouseholdMembership(Base):
    __tablename__ = "household_memberships"
    __table_args__ = (UniqueConstraint("household_id", "user_id", name="uq_household_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ApiCredential(Base):
    __tablename__ = "api_credentials"

    api_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class HouseholdMember(Base):
    __tablename__ = "household_members"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    linked_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FamilyGrant(Base):
    __tablename__ = "family_grants"
    __table_args__ = (
        UniqueConstraint("household_id", "subject_member_id", "viewer_user_id", "version",
                         name="uq_grant_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    viewer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    can_view: Mapped[bool] = mapped_column(Boolean, default=True)
    redline_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("device_id", "external_session_id", name="uq_device_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_session_id: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(20))
    correlation_id: Mapped[str] = mapped_column(String(100), index=True)
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    household_id: Mapped[str] = mapped_column(String(100), index=True)
    firmware_version: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(100))
    sequence_number: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int] = mapped_column(Integer)
    clock_status: Mapped[str] = mapped_column(String(30))
    clock_offset_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    presence_state: Mapped[str] = mapped_column(String(30))
    collection_state: Mapped[str] = mapped_column(String(30))
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[dict[str, Any]] = mapped_column(JSON)
    member_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("session_id", "dimension", name="uq_session_dimension"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(30))
    value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(30))
    model_version: Mapped[str] = mapped_column(String(100))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MemberAssignment(Base):
    __tablename__ = "member_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    assignment_status: Mapped[str] = mapped_column(String(30), index=True)
    member_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    claim_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40))
    reliable: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(30))
    policy_version: Mapped[str] = mapped_column(String(50))
    reasons: Mapped[list[str]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    subject_member_id: Mapped[str | None] = mapped_column(ForeignKey("household_members.id"), nullable=True)
    grant_id: Mapped[int | None] = mapped_column(ForeignKey("family_grants.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(40), index=True)
    recipient_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    authorization_basis: Mapped[str | None] = mapped_column(String(200), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(100), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    authorization_basis: Mapped[str] = mapped_column(String(200))
    policy_version: Mapped[str] = mapped_column(String(50))
    message_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentFeedback(Base):
    __tablename__ = "agent_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "created_by_user_id", name="uq_agent_feedback_message_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("agent_messages.id"), index=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentMemoryEntry(Base):
    __tablename__ = "agent_memory_entries"
    __table_args__ = (
        UniqueConstraint("logical_id", "version", name="uq_agent_memory_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    logical_id: Mapped[str] = mapped_column(String(100), index=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(30), index=True)
    memory_key: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    authored_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentProfile(Base):
    __tablename__ = "agent_profiles"
    __table_args__ = (
        UniqueConstraint("household_id", "subject_member_id", name="uq_agent_profile_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    # null identifies the household's shared steward; a member id identifies a private soul.
    subject_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("household_members.id"), nullable=True, index=True
    )
    display_name: Mapped[str] = mapped_column(String(100), default="PoopSense")
    soul: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    proactive_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_non_redline_limit: Mapped[int] = mapped_column(Integer, default=1)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="08:00")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Shanghai")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentProfileRevision(Base):
    __tablename__ = "agent_profile_revisions"
    __table_args__ = (UniqueConstraint("profile_id", "version", name="uq_agent_profile_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("agent_profiles.id"), index=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("household_members.id"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    change_reason: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("household_members.id"), nullable=True, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_conversations.id"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(40))
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    max_steps: Mapped[int] = mapped_column(Integer, default=4)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(50))
    authorization_basis: Mapped[str] = mapped_column(String(200))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_index", name="uq_agent_run_step"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    agent_name: Mapped[str] = mapped_column(String(60))
    skill_name: Mapped[str] = mapped_column(String(100))
    skill_version: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), index=True)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    authorization_basis: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentHandoff(Base):
    __tablename__ = "agent_handoffs"
    __table_args__ = (
        UniqueConstraint("run_id", "from_step_index", "to_step_index", name="uq_agent_handoff_steps"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    from_step_index: Mapped[int] = mapped_column(Integer)
    to_step_index: Mapped[int] = mapped_column(Integer)
    from_agent: Mapped[str] = mapped_column(String(60))
    to_agent: Mapped[str] = mapped_column(String(60))
    skill_name: Mapped[str] = mapped_column(String(100))
    skill_version: Mapped[str] = mapped_column(String(30))
    context_domains: Mapped[list[str]] = mapped_column(JSON)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    authorization_basis: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserNotification(Base):
    __tablename__ = "user_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subject_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("household_members.id"), nullable=True, index=True
    )
    agent_action_id: Mapped[int] = mapped_column(ForeignKey("agent_actions.id"), unique=True)
    notification_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="unread", index=True)
    authorization_basis: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PetProfile(Base):
    __tablename__ = "pet_profiles"
    __table_args__ = (UniqueConstraint("household_id", "subject_member_id", name="uq_pet_profile_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    name: Mapped[str] = mapped_column(String(50), default="小噗")
    selected_skin: Mapped[str] = mapped_column(String(30), default="classic")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PetCheckin(Base):
    __tablename__ = "pet_checkins"
    __table_args__ = (
        UniqueConstraint("household_id", "subject_member_id", "checkin_date", name="uq_pet_daily_checkin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    checkin_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(30), default="user_visit")
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommunityPost(Base):
    __tablename__ = "community_posts"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    author_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    agent_alias: Mapped[str] = mapped_column(String(100))
    topic: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str] = mapped_column(Text)
    consent_version: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentConnection(Base):
    __tablename__ = "agent_connections"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    initiator_household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    initiator_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    target_household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    target_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    initiator_alias: Mapped[str] = mapped_column(String(100))
    target_alias: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), index=True)
    consent_version: Mapped[str] = mapped_column(String(30))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    responded_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WeeklyHealthReport(Base):
    __tablename__ = "weekly_health_reports"
    __table_args__ = (UniqueConstraint("household_id", "subject_member_id", "period_start", name="uq_weekly_report_period"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    subject_member_id: Mapped[str] = mapped_column(ForeignKey("household_members.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), index=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    recommendations: Mapped[list[str]] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[str] = mapped_column(String(100))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RawDataAuthorization(Base):
    __tablename__ = "raw_data_authorizations"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("device_bindings.device_id"), index=True)
    purpose: Mapped[str] = mapped_column(String(300))
    data_types: Mapped[list[str]] = mapped_column(JSON)
    retention_days: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    deletion_status: Mapped[str] = mapped_column(String(30), index=True)
    granted_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RawDataUpload(Base):
    __tablename__ = "raw_data_uploads"
    __table_args__ = (UniqueConstraint("device_id", "object_key", name="uq_raw_upload_object"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    authorization_id: Mapped[str] = mapped_column(ForeignKey("raw_data_authorizations.id"), index=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("device_bindings.device_id"), index=True)
    object_key: Mapped[str] = mapped_column(String(200))
    data_type: Mapped[str] = mapped_column(String(40))
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
