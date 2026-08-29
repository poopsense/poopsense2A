from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObservationInput(BaseModel):
    value: str | None
    confidence: float | None = Field(default=None, ge=0, le=1)
    missing_reason: str | None = None
    source: Literal["sensor", "manual", "adapter"]
    model_version: str
    change_pct: float | None = None

    @model_validator(mode="after")
    def missing_value_requires_reason(self):
        if self.value is None and not self.missing_reason:
            raise ValueError("missing_reason is required when value is null")
        return self


class QualityInput(BaseModel):
    overall_confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class MemberCandidateInput(BaseModel):
    member_ref: str
    confidence: float = Field(ge=0, le=1)


class DeviceSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    session_id: str
    correlation_id: str
    device_id: str
    household_id: str
    firmware_version: str
    model_version: str
    sequence_number: int = Field(ge=0)
    source: Literal["device"]
    timestamp: datetime
    end_timestamp: datetime
    duration_s: int = Field(ge=0)
    clock_status: Literal["synced", "unsynced", "unknown"]
    clock_offset_ms: int | None = None
    presence_state: Literal["present", "absent", "unknown"]
    collection_state: Literal["completed", "partial", "failed"]
    observations: dict[str, ObservationInput]
    temperature_c: float | None = None
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    quality: QualityInput
    member_candidates: list[MemberCandidateInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.schema_version.split(".", 1)[0] != "1":
            raise ValueError("unsupported schema major version")
        if self.end_timestamp < self.timestamp:
            raise ValueError("end_timestamp must not precede timestamp")
        measured = int((self.end_timestamp - self.timestamp).total_seconds())
        if abs(measured - self.duration_s) > 5:
            raise ValueError("duration_s conflicts with timestamps")
        return self


class SessionReceipt(BaseModel):
    session_id: str
    correlation_id: str
    received_at: datetime
    assignment_status: str
    assessment_status: str
    message: str
    duplicate: bool


class InboxItem(BaseModel):
    session_id: str
    received_at: datetime
    candidates: list[dict[str, Any]]
    assignment_version: int


class ClaimInput(BaseModel):
    member_id: str
    claim_method: Literal["user_claim", "admin_claim", "correction"] = "user_claim"


class ClaimResult(BaseModel):
    session_id: str
    member_id: str
    assignment_status: str
    version: int


class AssessmentResult(BaseModel):
    session_id: str
    version: int
    status: str
    reliable: bool
    risk_level: str
    message: str
    policy_version: str
    reasons: list[str]


class TrendDimension(BaseModel):
    total: int
    categories: dict[str, int]
    category_ratios: dict[str, float]
    baseline_category: str | None = None
    baseline_sample_count: int = 0
    recent_sample_count: int = 0
    baseline_deviation_rate: float | None = None
    baseline_status: Literal["insufficient", "within_baseline", "deviated"] = "insufficient"


class MemberTrend(BaseModel):
    household_id: str
    member_id: str
    period_days: int
    assigned_sessions: int
    valid_sessions: int
    valid_sample_coverage: float
    insufficient_coverage: bool
    frequency_per_week: float
    consecutive_abnormal: int
    dimensions: dict[str, TrendDimension]


class GrantInput(BaseModel):
    viewer_user_id: str
    can_view: bool = True
    redline_notifications: bool = True


class GrantResult(BaseModel):
    grant_id: int
    household_id: str
    subject_member_id: str
    viewer_user_id: str
    version: int
    status: str
    can_view: bool
    redline_notifications: bool


class RevokeResult(BaseModel):
    grant_id: int
    status: str
    cancelled_actions: int


class DeviceResult(BaseModel):
    device_id: str
    household_id: str
    active: bool
    status: str
    firmware_version: str | None
    model_version: str | None
    last_seen_at: datetime | None
    privacy_mode: str = "local_raw_data"


class GrantListItem(GrantResult):
    granted_at: datetime
    revoked_at: datetime | None = None


class AgentChatInput(BaseModel):
    member_id: str
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class AgentMessageResult(BaseModel):
    message_id: int
    role: str
    content: str
    created_at: datetime


class AgentChatResult(BaseModel):
    conversation_id: str
    message: AgentMessageResult
    decision: str
    allowed_actions: list[str]
    authorization_basis: str
    policy_version: str
    model_version: str
    delegated_agent: str
    skill: str
    run_id: str
    skill_version: str


class RobotPoseCaptureInput(BaseModel):
    duration: float = Field(default=6.0, ge=3.0, le=30.0)


class RobotDeliveryInput(BaseModel):
    member_id: str
    confirmed: bool
    route_name: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    )


class RobotHandoverConfirmationInput(BaseModel):
    confirmed: bool


class RobotPlanResult(BaseModel):
    name: str
    enabled: bool
    calibrated_poses: list[str]
    missing_poses: list[str]


class RobotTaskResult(BaseModel):
    accepted: bool
    task: str
    task_id: str
    status: str
    current_step: str | None = None
    requires_user_action: str | None = None


class AgentStepResult(BaseModel):
    step_index: int
    agent_name: str
    skill_name: str
    skill_version: str
    status: str
    output_summary: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None


class AgentHandoffResult(BaseModel):
    from_agent: str
    to_agent: str
    skill_name: str
    skill_version: str
    context_domains: list[str]
    status: str
    authorization_basis: str
    created_at: datetime
    accepted_at: datetime | None


class AgentRunResult(BaseModel):
    run_id: str
    member_id: str | None
    trigger: str
    goal: str
    status: str
    current_step: int
    max_steps: int
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    steps: list[AgentStepResult]
    handoffs: list[AgentHandoffResult]


class SkillContractResult(BaseModel):
    name: str
    version: str
    agent: str
    risk: str
    allowed_roles: list[str]
    context_domains: list[str]
    proactive_allowed: bool
    confirmation_required: bool
    input_schema: dict[str, str]
    output_schema: dict[str, str]


class AgentResumeInput(BaseModel):
    confirmed: bool


class AgentResumeResult(BaseModel):
    run: AgentRunResult
    message: AgentMessageResult


class AgentConversationResult(BaseModel):
    conversation_id: str
    member_id: str
    messages: list[AgentMessageResult]


class AgentConversationSummary(BaseModel):
    conversation_id: str
    member_id: str
    updated_at: datetime


class AgentStatusResult(BaseModel):
    provider: str
    model: str
    configured: bool
    proactive_enabled: bool
    policy_version: str
    worker_enabled: bool
    worker_running: bool
    worker_last_run_at: datetime | None
    worker_last_error: str | None
    worker_processed_total: int
    skills: list[str]
    agents: list[str]


class AgentProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    tone: str = Field(default="温柔、直接、不说教", max_length=200)
    relationship_goal: str = Field(default="长期理解身体节奏", max_length=500)
    proactive_enabled: bool = True
    quiet_start: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="Asia/Shanghai", max_length=60)


class AgentProfileResult(AgentProfileUpdate):
    member_id: str | None
    scope: str
    daily_non_redline_limit: int
    version: int
    updated_at: datetime
    explanation_basis: list[str]


class AgentProfileRevisionResult(BaseModel):
    version: int
    snapshot: dict[str, Any]
    changed_by_user_id: str | None
    change_reason: str
    created_at: datetime


class AgentActionResult(BaseModel):
    action_id: int
    action_type: str
    status: str
    member_id: str | None
    authorization_basis: str | None
    model_version: str | None
    result: dict[str, Any]
    created_at: datetime
    processed_at: datetime | None


class NotificationResult(BaseModel):
    notification_id: int
    notification_type: str
    title: str
    body: str
    priority: str
    status: str
    member_id: str | None
    authorization_basis: str
    created_at: datetime
    read_at: datetime | None
    acknowledged_at: datetime | None


class MemoryCreateInput(BaseModel):
    memory_key: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)


class MemoryUpdateInput(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    correction_reason: str | None = Field(default=None, max_length=500)


class MemoryResult(BaseModel):
    memory_id: int
    logical_id: str
    member_id: str
    version: int
    source_type: str
    memory_key: str
    content: str
    editable: bool
    correction_reason: str | None
    created_at: datetime


class HealthProfileInput(BaseModel):
    conditions: list[str] = Field(default_factory=list, max_length=20)
    diet_pattern: str = Field(default="", max_length=500)
    sleep_pattern: str = Field(default="", max_length=500)
    medications: list[str] = Field(default_factory=list, max_length=30)
    goals: list[str] = Field(default_factory=list, max_length=20)


class HealthProfileResult(HealthProfileInput):
    member_id: str
    completeness: float
    updated_at: datetime | None


class AgentFeedbackInput(BaseModel):
    rating: Literal["helpful", "not_helpful"]
    reason: str | None = Field(default=None, max_length=500)


class AgentFeedbackResult(BaseModel):
    feedback_id: int
    message_id: int
    rating: str
    reason: str | None
    updated_at: datetime


class PetProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    selected_skin: Literal["classic", "blue_wave", "pop_star"]


class PetSnapshotResult(BaseModel):
    member_id: str
    name: str
    selected_skin: str
    unlocked_skins: list[str]
    mood: Literal["curious", "cheerful", "concerned"]
    stage: Literal["new_friend", "companion", "grown_up"]
    message: str
    streak_days: int
    total_checkins: int
    checked_in_today: bool
    health_basis: Literal["insufficient", "reliable_summary"]
    profile_version: int


class PetCheckinResult(BaseModel):
    duplicate: bool
    pet: PetSnapshotResult


class CommunityPostInput(BaseModel):
    member_id: str
    topic: Literal["hydration", "diet", "routine", "encouragement"]
    content: str = Field(min_length=2, max_length=280)
    explicit_consent: Literal[True]


class CommunityPostResult(BaseModel):
    post_id: str
    agent_alias: str
    topic: str
    content: str
    status: Literal["active", "withdrawn"]
    created_at: datetime
    can_withdraw: bool = False


class AgentConnectionCreateInput(BaseModel):
    initiator_member_id: str
    target_post_id: str
    explicit_consent: Literal[True]


class AgentConnectionRespondInput(BaseModel):
    member_id: str
    accept: bool


class AgentConnectionResult(BaseModel):
    connection_id: str
    member_id: str
    other_agent_alias: str
    direction: Literal["outbound", "inbound"]
    status: Literal["pending", "connected", "rejected", "ended"]
    created_at: datetime
    can_respond: bool
    can_end: bool


class WeeklyHealthReportResult(BaseModel):
    report_id: str
    member_id: str
    period_start: date
    period_end: date
    status: Literal["insufficient", "ready"]
    facts: dict
    summary: str
    recommendations: list[str]
    policy_version: str
    model_version: str
    created_at: datetime


class RawDataAuthorizationInput(BaseModel):
    device_id: str
    purpose: str = Field(min_length=4, max_length=300)
    data_types: list[Literal["spectral", "thermal", "odor", "presence"]] = Field(min_length=1)
    retention_days: int = Field(ge=1, le=30)
    explicit_consent: Literal[True]


class RawDataAuthorizationResult(BaseModel):
    authorization_id: str
    device_id: str
    purpose: str
    data_types: list[str]
    retention_days: int
    status: Literal["active", "revoked", "expired"]
    deletion_status: Literal["not_required", "pending", "completed"]
    upload_count: int
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    deleted_at: datetime | None


class RawDataUploadInput(BaseModel):
    authorization_id: str
    household_id: str
    device_id: str
    object_key: str = Field(min_length=1, max_length=200)
    data_type: Literal["spectral", "thermal", "odor", "presence"]
    byte_size: int = Field(gt=0, le=100_000_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RawDataUploadResult(BaseModel):
    upload_id: str
    status: Literal["stored", "deleted"]
    duplicate: bool


class HouseholdMemberResult(BaseModel):
    member_id: str
    display_name: str
    linked_to_current_user: bool


class HouseholdMemberCreateInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)


class PoopVisualDimension(BaseModel):
    value: str
    confidence: float
    source: str
    model_version: str


class PoopVisualProfile(BaseModel):
    mapping_version: Literal["poop-visual-v1"] = "poop-visual-v1"
    variant: Literal["compact", "elongated", "scattered", "irregular", "uncertain"]
    reliable: bool
    shape: PoopVisualDimension | None = None
    color: PoopVisualDimension | None = None
    odor: PoopVisualDimension | None = None


class MemberSessionResult(BaseModel):
    session_id: str
    occurred_at: datetime
    assignment_version: int
    assessment_status: str
    risk_level: str
    message: str
    visual_profile: PoopVisualProfile
