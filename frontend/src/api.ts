export type AppConfig = {
  apiBase: string;
  householdId: string;
  householdKey: string;
};
export type Member = {
  member_id: string;
  display_name: string;
  linked_to_current_user: boolean;
};
export type InboxItem = {
  session_id: string;
  received_at: string;
  candidates: { member_ref: string; confidence: number }[];
  assignment_version: number;
};
export type MemberSession = {
  session_id: string;
  occurred_at: string;
  assignment_version: number;
  assessment_status: string;
  risk_level: string;
  message: string;
  visual_profile?: PoopVisualProfile | null;
};
export type PoopVisualDimension = {
  value: string;
  confidence: number;
  source: string;
  model_version: string;
};
export type PoopVisualProfile = {
  mapping_version: "poop-visual-v1";
  variant: "compact" | "elongated" | "scattered" | "irregular" | "uncertain";
  reliable: boolean;
  shape: PoopVisualDimension | null;
  color: PoopVisualDimension | null;
  odor: PoopVisualDimension | null;
};
export type TrendDimension = {
  total: number;
  categories: Record<string, number>;
  category_ratios: Record<string, number>;
  baseline_category: string | null;
  baseline_sample_count: number;
  recent_sample_count: number;
  baseline_deviation_rate: number | null;
  baseline_status: "insufficient" | "within_baseline" | "deviated";
};
export type Trend = {
  household_id: string;
  member_id: string;
  period_days: number;
  assigned_sessions: number;
  valid_sessions: number;
  valid_sample_coverage: number;
  insufficient_coverage: boolean;
  frequency_per_week: number;
  consecutive_abnormal: number;
  dimensions: Record<string, TrendDimension>;
};
export type Device = {
  device_id: string;
  household_id: string;
  active: boolean;
  status: string;
  firmware_version: string | null;
  model_version: string | null;
  last_seen_at: string | null;
  privacy_mode: string;
};
export type Grant = {
  grant_id: number;
  household_id: string;
  subject_member_id: string;
  viewer_user_id: string;
  version: number;
  status: string;
  can_view: boolean;
  redline_notifications: boolean;
  granted_at: string;
  revoked_at: string | null;
};
export type AgentMessage = {
  message_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};
export type HealthProfile = {
  member_id: string;
  conditions: string[];
  diet_pattern: string;
  sleep_pattern: string;
  medications: string[];
  goals: string[];
  completeness: number;
  updated_at: string | null;
};
export type AgentFeedback = {
  feedback_id: number;
  message_id: number;
  rating: "helpful" | "not_helpful";
  reason: string | null;
  updated_at: string;
};
export type PetSnapshot = {
  member_id: string;
  name: string;
  selected_skin: "classic" | "blue_wave" | "pop_star";
  unlocked_skins: ("classic" | "blue_wave" | "pop_star")[];
  mood: "curious" | "cheerful" | "concerned";
  stage: "new_friend" | "companion" | "grown_up";
  message: string;
  streak_days: number;
  total_checkins: number;
  checked_in_today: boolean;
  health_basis: "insufficient" | "reliable_summary";
  profile_version: number;
};
export type CommunityPost = {
  post_id: string;
  agent_alias: string;
  topic: "hydration" | "diet" | "routine" | "encouragement";
  content: string;
  status: "active" | "withdrawn";
  created_at: string;
  can_withdraw: boolean;
};
export type AgentConnection = {
  connection_id: string;
  member_id: string;
  other_agent_alias: string;
  direction: "outbound" | "inbound";
  status: "pending" | "connected" | "rejected" | "ended";
  created_at: string;
  can_respond: boolean;
  can_end: boolean;
};
export type AgentChat = {
  conversation_id: string;
  message: AgentMessage;
  decision: string;
  allowed_actions: string[];
  authorization_basis: string;
  policy_version: string;
  model_version: string;
  delegated_agent: string;
  skill: string;
  run_id: string;
  skill_version: string;
};
export type RobotTask = {
  accepted?: boolean;
  task?: string;
  task_id: string;
  member_id?: string | null;
  status: string;
  progress?: number;
  current_step: string | null;
  message?: string | null;
  error?: string | null;
  requires_user_action: string | null;
};
export type AgentStep = {
  step_index: number;
  agent_name: string;
  skill_name: string;
  skill_version: string;
  status: string;
  output_summary: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
};
export type SkillContract = {
  name: string;
  version: string;
  agent: string;
  risk: string;
  allowed_roles: string[];
  context_domains: string[];
  proactive_allowed: boolean;
  confirmation_required: boolean;
  input_schema: Record<string, string>;
  output_schema: Record<string, string>;
};
export type AgentResume = {
  run: AgentRun;
  message: AgentMessage;
};
export type AgentRun = {
  run_id: string;
  member_id: string | null;
  trigger: string;
  goal: string;
  status: string;
  current_step: number;
  max_steps: number;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  steps: AgentStep[];
  handoffs: AgentHandoff[];
};
export type AgentHandoff = {
  from_agent: string;
  to_agent: string;
  skill_name: string;
  skill_version: string;
  context_domains: string[];
  status: string;
  authorization_basis: string;
  created_at: string;
  accepted_at: string | null;
};
export type AgentStatus = {
  provider: string;
  model: string;
  configured: boolean;
  proactive_enabled: boolean;
  policy_version: string;
  worker_enabled: boolean;
  worker_running: boolean;
  worker_last_run_at: string | null;
  worker_last_error: string | null;
  worker_processed_total: number;
  skills: string[];
  agents: string[];
};
export type AgentProfile = {
  member_id: string | null;
  scope: "member" | "household";
  display_name: string;
  tone: string;
  relationship_goal: string;
  proactive_enabled: boolean;
  daily_non_redline_limit: number;
  quiet_start: string;
  quiet_end: string;
  timezone: string;
  version: number;
  updated_at: string;
  explanation_basis: string[];
};
export type AgentProfileRevision = {
  version: number;
  snapshot: {
    display_name: string;
    soul: { tone?: string; relationship_goal?: string };
    proactive_enabled: boolean;
    daily_non_redline_limit: number;
    quiet_start: string;
    quiet_end: string;
    timezone: string;
  };
  changed_by_user_id: string | null;
  change_reason: string;
  created_at: string;
};
export type Notification = {
  notification_id: number;
  notification_type: string;
  title: string;
  body: string;
  priority: string;
  status: string;
  member_id: string | null;
  authorization_basis: string;
  created_at: string;
  read_at: string | null;
  acknowledged_at: string | null;
};
export type ConversationSummary = {
  conversation_id: string;
  member_id: string;
  updated_at: string;
};
export type Conversation = {
  conversation_id: string;
  member_id: string;
  messages: AgentMessage[];
};
export type AgentAction = {
  action_id: number;
  action_type: string;
  status: string;
  member_id: string | null;
  authorization_basis: string | null;
  model_version: string | null;
  result: Record<string, unknown>;
  created_at: string;
  processed_at: string | null;
};
export type AgentMemory = {
  memory_id: number;
  logical_id: string;
  member_id: string;
  version: number;
  source_type: "self_report" | "sensor_fact" | "system_inference";
  memory_key: string;
  content: string;
  editable: boolean;
  correction_reason: string | null;
  created_at: string;
};
export type WeeklyHealthReport = {
  report_id: string;
  member_id: string;
  period_start: string;
  period_end: string;
  status: "insufficient" | "ready";
  facts: {
    valid_sessions: number;
    coverage: number;
    frequency_per_week: number;
    consecutive_abnormal: number;
    dimensions: Record<string, TrendDimension>;
  };
  summary: string;
  recommendations: string[];
  policy_version: string;
  model_version: string;
  created_at: string;
};
export type RawDataAuthorization = {
  authorization_id: string;
  device_id: string;
  purpose: string;
  data_types: string[];
  retention_days: number;
  status: "active" | "revoked" | "expired";
  deletion_status: "not_required" | "pending" | "completed";
  upload_count: number;
  granted_at: string;
  expires_at: string;
  revoked_at: string | null;
  deleted_at: string | null;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  config: AppConfig,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${config.apiBase}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Household-Key": config.householdKey,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const code = body?.detail?.code ?? `HTTP_${response.status}`;
    throw new ApiError(response.status, code);
  }
  return response.json();
}

export const api = {
  members: (c: AppConfig) =>
    request<Member[]>(c, `/api/v1/households/${c.householdId}/members`),
  createMember: (c: AppConfig, displayName: string) =>
    request<Member>(c, `/api/v1/households/${c.householdId}/members`, {
      method: "POST", body: JSON.stringify({ display_name: displayName }),
    }),
  inbox: (c: AppConfig) =>
    request<InboxItem[]>(c, `/api/v1/households/${c.householdId}/claim-inbox`),
  trend: (c: AppConfig, memberId: string) =>
    request<Trend>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/trends?days=30`,
    ),
  sessions: (c: AppConfig, memberId: string) =>
    request<MemberSession[]>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/sessions`,
    ),
  weeklyReports: (c: AppConfig, memberId: string) =>
    request<WeeklyHealthReport[]>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/weekly-reports`,
    ),
  generateWeeklyReport: (c: AppConfig, memberId: string) =>
    request<WeeklyHealthReport>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/weekly-reports`,
      { method: "POST" },
    ),
  rawDataAuthorizations: (c: AppConfig) =>
    request<RawDataAuthorization[]>(c, `/api/v1/households/${c.householdId}/raw-data-authorizations`),
  createRawDataAuthorization: (
    c: AppConfig, deviceId: string, purpose: string, dataTypes: string[], retentionDays: number,
  ) => request<RawDataAuthorization>(c, `/api/v1/households/${c.householdId}/raw-data-authorizations`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, purpose, data_types: dataTypes,
      retention_days: retentionDays, explicit_consent: true }),
  }),
  revokeRawDataAuthorization: (c: AppConfig, authorizationId: string) =>
    request<RawDataAuthorization>(c, `/api/v1/households/${c.householdId}/raw-data-authorizations/${authorizationId}`, { method: "DELETE" }),
  completeRawDataDeletion: (c: AppConfig, authorizationId: string) =>
    request<RawDataAuthorization>(c, `/api/v1/households/${c.householdId}/raw-data-authorizations/${authorizationId}/complete-deletion`, { method: "POST" }),
  claim: (
    c: AppConfig,
    sessionId: string,
    memberId: string,
    correction = false,
  ) =>
    request(
      c,
      `/api/v1/households/${c.householdId}/sessions/${sessionId}/claim`,
      {
        method: "POST",
        body: JSON.stringify({
          member_id: memberId,
          claim_method: correction ? "correction" : "user_claim",
        }),
      },
    ),
  devices: (c: AppConfig) =>
    request<Device[]>(c, `/api/v1/households/${c.householdId}/devices`),
  grants: (c: AppConfig, memberId: string) =>
    request<Grant[]>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/grants`,
    ),
  createGrant: (c: AppConfig, memberId: string, viewerUserId: string) =>
    request<Grant>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/grants`,
      {
        method: "POST",
        body: JSON.stringify({
          viewer_user_id: viewerUserId,
          can_view: true,
          redline_notifications: true,
        }),
      },
    ),
  revokeGrant: (c: AppConfig, grantId: number) =>
    request<{ grant_id: number; status: string; cancelled_actions: number }>(
      c,
      `/api/v1/households/${c.householdId}/grants/${grantId}`,
      { method: "DELETE" },
    ),
  agentChat: (
    c: AppConfig,
    memberId: string,
    message: string,
    conversationId?: string,
  ) =>
    request<AgentChat>(c, `/api/v1/households/${c.householdId}/agent/chat`, {
      method: "POST",
      body: JSON.stringify({
        member_id: memberId,
        message,
        conversation_id: conversationId ?? null,
      }),
    }),
  stopRobot: (c: AppConfig) =>
    request<{ stopped: boolean }>(
      c,
      `/api/v1/households/${c.householdId}/robot/tasks/stop`,
      { method: "POST" },
    ),
  deliverWater: (c: AppConfig, memberId: string) =>
    request<RobotTask>(
      c,
      `/api/v1/households/${c.householdId}/robot/tasks/deliver-water`,
      {
        method: "POST",
        body: JSON.stringify({ member_id: memberId, confirmed: true }),
      },
    ),
  pickupWater: (c: AppConfig, memberId: string) =>
    request<RobotTask>(
      c,
      `/api/v1/households/${c.householdId}/robot/tasks/pickup-water`,
      {
        method: "POST",
        body: JSON.stringify({ member_id: memberId, confirmed: true }),
      },
    ),
  robotTask: (c: AppConfig, taskId: string) =>
    request<RobotTask>(
      c,
      `/api/v1/households/${c.householdId}/robot/tasks/${taskId}`,
    ),
  confirmRobotHandover: (c: AppConfig, taskId: string) =>
    request<RobotTask>(
      c,
      `/api/v1/households/${c.householdId}/robot/tasks/${taskId}/confirm-handover`,
      { method: "POST", body: JSON.stringify({ confirmed: true }) },
    ),
  agentStatus: (c: AppConfig) =>
    request<AgentStatus>(c, `/api/v1/households/${c.householdId}/agent/status`),
  agentRun: (c: AppConfig, runId: string) =>
    request<AgentRun>(
      c,
      `/api/v1/households/${c.householdId}/agent/runs/${runId}`,
    ),
  resumeAgentRun: (c: AppConfig, runId: string, confirmed: boolean) =>
    request<AgentResume>(
      c,
      `/api/v1/households/${c.householdId}/agent/runs/${runId}/resume`,
      { method: "POST", body: JSON.stringify({ confirmed }) },
    ),
  agentSkills: (c: AppConfig) =>
    request<SkillContract[]>(
      c,
      `/api/v1/households/${c.householdId}/agent/skills`,
    ),
  conversations: (c: AppConfig, memberId: string) =>
    request<ConversationSummary[]>(
      c,
      `/api/v1/households/${c.householdId}/agent/conversations?member_id=${encodeURIComponent(memberId)}`,
    ),
  conversation: (c: AppConfig, conversationId: string) =>
    request<Conversation>(
      c,
      `/api/v1/households/${c.householdId}/agent/conversations/${conversationId}`,
    ),
  healthProfile: (c: AppConfig, memberId: string) =>
    request<HealthProfile>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/health-profile`,
    ),
  updateHealthProfile: (c: AppConfig, memberId: string, profile: HealthProfile) =>
    request<HealthProfile>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/health-profile`,
      {
        method: "PUT",
        body: JSON.stringify({
          conditions: profile.conditions,
          diet_pattern: profile.diet_pattern,
          sleep_pattern: profile.sleep_pattern,
          medications: profile.medications,
          goals: profile.goals,
        }),
      },
    ),
  rateAgentMessage: (
    c: AppConfig,
    messageId: number,
    rating: "helpful" | "not_helpful",
    reason?: string,
  ) => request<AgentFeedback>(
    c,
    `/api/v1/households/${c.householdId}/agent/messages/${messageId}/feedback`,
    { method: "PUT", body: JSON.stringify({ rating, reason: reason ?? null }) },
  ),
  pet: (c: AppConfig, memberId: string) =>
    request<PetSnapshot>(c, `/api/v1/households/${c.householdId}/members/${memberId}/pet`),
  checkInPet: (c: AppConfig, memberId: string) =>
    request<{ duplicate: boolean; pet: PetSnapshot }>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/pet/check-in`,
      { method: "POST" },
    ),
  updatePet: (c: AppConfig, memberId: string, name: string, selectedSkin: PetSnapshot["selected_skin"]) =>
    request<PetSnapshot>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/pet`,
      { method: "PUT", body: JSON.stringify({ name, selected_skin: selectedSkin }) },
    ),
  communityPosts: (c: AppConfig) =>
    request<CommunityPost[]>(c, `/api/v1/households/${c.householdId}/community/posts`),
  publishCommunityPost: (c: AppConfig, memberId: string, topic: CommunityPost["topic"], content: string) =>
    request<CommunityPost>(c, `/api/v1/households/${c.householdId}/community/posts`, {
      method: "POST",
      body: JSON.stringify({ member_id: memberId, topic, content, explicit_consent: true }),
    }),
  withdrawCommunityPost: (c: AppConfig, postId: string) =>
    request<CommunityPost>(c, `/api/v1/households/${c.householdId}/community/posts/${postId}/withdraw`, { method: "POST" }),
  agentConnections: (c: AppConfig, memberId: string) =>
    request<AgentConnection[]>(c, `/api/v1/households/${c.householdId}/members/${memberId}/agent-connections`),
  requestAgentConnection: (c: AppConfig, memberId: string, postId: string) =>
    request<AgentConnection>(c, `/api/v1/households/${c.householdId}/agent-connections`, {
      method: "POST", body: JSON.stringify({ initiator_member_id: memberId, target_post_id: postId, explicit_consent: true }),
    }),
  respondAgentConnection: (c: AppConfig, memberId: string, connectionId: string, accept: boolean) =>
    request<AgentConnection>(c, `/api/v1/households/${c.householdId}/agent-connections/${connectionId}/respond`, {
      method: "POST", body: JSON.stringify({ member_id: memberId, accept }),
    }),
  endAgentConnection: (c: AppConfig, memberId: string, connectionId: string) =>
    request<AgentConnection>(c, `/api/v1/households/${c.householdId}/agent-connections/${connectionId}/end?member_id=${encodeURIComponent(memberId)}`, { method: "POST" }),
  agentActions: (c: AppConfig) =>
    request<AgentAction[]>(
      c,
      `/api/v1/households/${c.householdId}/agent/actions?limit=20`,
    ),
  agentProfile: (c: AppConfig, scopeId: string) =>
    request<AgentProfile>(
      c,
      `/api/v1/households/${c.householdId}/agent/profiles/${scopeId}`,
    ),
  agentProfileHistory: (c: AppConfig, scopeId: string) =>
    request<AgentProfileRevision[]>(
      c,
      `/api/v1/households/${c.householdId}/agent/profiles/${scopeId}/history`,
    ),
  updateAgentProfile: (c: AppConfig, scopeId: string, profile: AgentProfile) =>
    request<AgentProfile>(
      c,
      `/api/v1/households/${c.householdId}/agent/profiles/${scopeId}`,
      {
        method: "PUT",
        body: JSON.stringify({
          display_name: profile.display_name,
          tone: profile.tone,
          relationship_goal: profile.relationship_goal,
          proactive_enabled: profile.proactive_enabled,
          quiet_start: profile.quiet_start,
          quiet_end: profile.quiet_end,
          timezone: profile.timezone,
        }),
      },
    ),
  notifications: (c: AppConfig) =>
    request<Notification[]>(c, `/api/v1/households/${c.householdId}/notifications`),
  readNotification: (c: AppConfig, notificationId: number) =>
    request<Notification>(
      c,
      `/api/v1/households/${c.householdId}/notifications/${notificationId}/read`,
      { method: "POST" },
    ),
  acknowledgeNotification: (c: AppConfig, notificationId: number) =>
    request<Notification>(
      c,
      `/api/v1/households/${c.householdId}/notifications/${notificationId}/acknowledge`,
      { method: "POST" },
    ),
  memory: (c: AppConfig, memberId: string, history = false) =>
    request<AgentMemory[]>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/memory?include_history=${history}`,
    ),
  addMemory: (
    c: AppConfig,
    memberId: string,
    memoryKey: string,
    content: string,
  ) =>
    request<AgentMemory>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/memory`,
      {
        method: "POST",
        body: JSON.stringify({ memory_key: memoryKey, content }),
      },
    ),
  updateMemory: (
    c: AppConfig,
    memberId: string,
    logicalId: string,
    content: string,
    correctionReason?: string,
  ) =>
    request<AgentMemory>(
      c,
      `/api/v1/households/${c.householdId}/members/${memberId}/memory/${logicalId}`,
      {
        method: "PUT",
        body: JSON.stringify({
          content,
          correction_reason: correctionReason ?? null,
        }),
      },
    ),
};
