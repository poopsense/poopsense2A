import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api, ApiError } from "./api";

vi.mock("./api", async () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    api: {
      members: vi.fn(),
      createMember: vi.fn(),
      inbox: vi.fn(),
      trend: vi.fn(),
      sessions: vi.fn(),
      weeklyReports: vi.fn(),
      generateWeeklyReport: vi.fn(),
      rawDataAuthorizations: vi.fn(),
      createRawDataAuthorization: vi.fn(),
      revokeRawDataAuthorization: vi.fn(),
      completeRawDataDeletion: vi.fn(),
      claim: vi.fn(),
      agentChat: vi.fn(),
      deliverWater: vi.fn(),
      pickupWater: vi.fn(),
      robotTask: vi.fn(),
      confirmRobotHandover: vi.fn(),
      stopRobot: vi.fn(),
      devices: vi.fn(),
      grants: vi.fn(),
      createGrant: vi.fn(),
      revokeGrant: vi.fn(),
      agentStatus: vi.fn(),
      agentRun: vi.fn(),
      resumeAgentRun: vi.fn(),
      agentSkills: vi.fn(),
      conversations: vi.fn(),
      conversation: vi.fn(),
      agentActions: vi.fn(),
      agentProfile: vi.fn(),
      updateAgentProfile: vi.fn(),
      agentProfileHistory: vi.fn(),
      notifications: vi.fn(),
      readNotification: vi.fn(),
      acknowledgeNotification: vi.fn(),
      memory: vi.fn(),
      addMemory: vi.fn(),
      updateMemory: vi.fn(),
      healthProfile: vi.fn(),
      updateHealthProfile: vi.fn(),
      rateAgentMessage: vi.fn(),
      pet: vi.fn(),
      checkInPet: vi.fn(),
      updatePet: vi.fn(),
      communityPosts: vi.fn(),
      publishCommunityPost: vi.fn(),
      withdrawCommunityPost: vi.fn(),
      agentConnections: vi.fn(),
      requestAgentConnection: vi.fn(),
      respondAgentConnection: vi.fn(),
      endAgentConnection: vi.fn(),
    },
  };
});

const mocked = vi.mocked(api);
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

beforeEach(() => {
  sessionStorage.clear();
  mocked.members.mockResolvedValue([
    { member_id: "m_001", display_name: "小风", linked_to_current_user: true },
    { member_id: "m_002", display_name: "家人", linked_to_current_user: false },
  ]);
  mocked.createMember.mockResolvedValue({ member_id: "m_003", display_name: "奶奶", linked_to_current_user: false });
  mocked.inbox.mockResolvedValue([
    {
      session_id: "ses_1",
      received_at: "2026-08-24T08:00:00Z",
      candidates: [],
      assignment_version: 1,
    },
  ]);
  mocked.trend.mockResolvedValue({
    household_id: "hh_001",
    member_id: "m_001",
    period_days: 30,
    assigned_sessions: 2,
    valid_sessions: 1,
    valid_sample_coverage: 0.5,
    insufficient_coverage: false,
    frequency_per_week: 0.23,
    consecutive_abnormal: 0,
    dimensions: {
      shape: {
        total: 1,
        categories: { normal: 1 },
        category_ratios: { normal: 1 },
        baseline_category: null,
        baseline_sample_count: 0,
        recent_sample_count: 1,
        baseline_deviation_rate: null,
        baseline_status: "insufficient",
      },
    },
  });
  mocked.sessions.mockResolvedValue([]);
  mocked.weeklyReports.mockResolvedValue([]);
  mocked.generateWeeklyReport.mockResolvedValue({
    report_id: "weekly_1", member_id: "m_001",
    period_start: "2026-08-24", period_end: "2026-08-30",
    status: "insufficient",
    facts: { valid_sessions: 1, coverage: 0.5, frequency_per_week: 1,
      consecutive_abnormal: 0, dimensions: {} },
    summary: "本周可靠样本不足，暂不做趋势判断。继续积累记录后再回看。",
    recommendations: ["保持自然记录，不必为凑数据改变生活习惯"],
    policy_version: "safety-v1", model_version: "policy-engine",
    created_at: "2026-08-29T00:00:00Z",
  });
  mocked.claim.mockResolvedValue({});
  mocked.devices.mockResolvedValue([{ device_id: "dev_001", household_id: "hh_001", active: true,
    status: "online", firmware_version: "0.3.0", model_version: "edge-0.2.0",
    last_seen_at: "2026-08-29T00:00:00Z", privacy_mode: "local_raw_data" }]);
  mocked.rawDataAuthorizations.mockResolvedValue([]);
  mocked.createRawDataAuthorization.mockResolvedValue({
    authorization_id: "rawauth_1", device_id: "dev_001", purpose: "改进传感分类模型",
    data_types: ["odor"], retention_days: 7, status: "active", deletion_status: "not_required",
    upload_count: 0, granted_at: "2026-08-29T00:00:00Z", expires_at: "2026-09-05T00:00:00Z",
    revoked_at: null, deleted_at: null,
  });
  mocked.grants.mockResolvedValue([]);
  mocked.agentStatus.mockResolvedValue({
    provider: "deepseek",
    model: "deepseek-v4-pro",
    configured: true,
    proactive_enabled: true,
    policy_version: "safety-v1",
    worker_enabled: true,
    worker_running: true,
    worker_last_run_at: null,
    worker_last_error: null,
    worker_processed_total: 0,
    skills: ["urgent_care"],
    agents: ["main_agent", "health_doctor"],
  });
  mocked.conversations.mockResolvedValue([]);
  mocked.agentActions.mockResolvedValue([]);
  mocked.agentProfileHistory.mockResolvedValue([]);
  mocked.notifications.mockResolvedValue([]);
  mocked.agentProfile.mockResolvedValue({
    member_id: "m_001", scope: "member", display_name: "小风的 PoopSense",
    tone: "温和直接", relationship_goal: "长期陪伴", proactive_enabled: true,
    daily_non_redline_limit: 1, quiet_start: "22:00", quiet_end: "08:00",
    timezone: "Asia/Shanghai", version: 1, updated_at: "2026-08-29T00:00:00Z",
    explanation_basis: [],
  });
  mocked.memory.mockResolvedValue([]);
  mocked.healthProfile.mockResolvedValue({
    member_id: "m_001", conditions: [], diet_pattern: "", sleep_pattern: "",
    medications: [], goals: [], completeness: 0, updated_at: null,
  });
  mocked.updateHealthProfile.mockImplementation(async (_config, _memberId, profile) => ({
    ...profile, member_id: "m_001", completeness: 1,
    updated_at: "2026-08-28T00:00:00Z",
  }));
  mocked.rateAgentMessage.mockResolvedValue({
    feedback_id: 1, message_id: 2, rating: "helpful", reason: null,
    updated_at: "2026-08-28T00:00:00Z",
  });
  mocked.addMemory.mockResolvedValue({
    memory_id: 1,
    logical_id: "mem_1",
    member_id: "m_001",
    version: 1,
    source_type: "self_report",
    memory_key: "饮食偏好",
    content: "很少吃辣",
    editable: true,
    correction_reason: null,
    created_at: "2026-08-28T00:00:00Z",
  });
  mocked.agentChat.mockResolvedValue({
    conversation_id: "conv_1",
    message: {
      message_id: 2,
      role: "assistant",
      content: "请尽快联系线下医生；严重症状请立即寻求急诊帮助。",
      created_at: "2026-08-27T00:00:00Z",
    },
    decision: "urgent_care",
    allowed_actions: ["recommend_urgent_care"],
    authorization_basis: "household_owner",
    policy_version: "safety-v1",
    model_version: "test-model",
    delegated_agent: "health_doctor",
    skill: "urgent_care",
    run_id: "run_1",
    skill_version: "1.0.0",
  });
  mocked.pickupWater.mockResolvedValue({
    accepted: true, task: "pickup_water", task_id: "pickup_1",
    status: "starting", current_step: "starting", requires_user_action: null,
  });
  mocked.robotTask.mockResolvedValue({
    task_id: "pickup_1", status: "completed",
    progress: 1, current_step: "pickup_completed",
    message: "取水演示完成：水杯已提起，机械臂保持当前位置", requires_user_action: null,
  });
  mocked.confirmRobotHandover.mockResolvedValue({
    task_id: "delivery_1", status: "running", progress: 0.9,
    current_step: "releasing", message: "正在安全松开夹爪", requires_user_action: null,
  });
  mocked.agentRun.mockResolvedValue({
    run_id: "run_1", member_id: "m_001", trigger: "user_message",
    goal: "出现血便怎么办", status: "completed", current_step: 2,
    max_steps: 4, result: {}, error: null,
    created_at: "2026-08-28T00:00:00Z", completed_at: "2026-08-28T00:00:01Z",
    steps: [
      { step_index: 1, agent_name: "main_agent", skill_name: "route_request", skill_version: "1.0.0", status: "succeeded", output_summary: {}, started_at: null, completed_at: null, error: null },
      { step_index: 2, agent_name: "health_doctor", skill_name: "urgent_care", skill_version: "1.0.0", status: "succeeded", output_summary: {}, started_at: null, completed_at: null, error: null },
    ],
    handoffs: [],
  });
  mocked.agentSkills.mockResolvedValue([]);
  mocked.pet.mockResolvedValue({
    member_id: "m_001", name: "小噗", selected_skin: "classic",
    unlocked_skins: ["classic"], mood: "curious", stage: "new_friend",
    message: "先一起积累可靠记录。", streak_days: 0, total_checkins: 0,
    checked_in_today: false, health_basis: "insufficient", profile_version: 1,
  });
  mocked.checkInPet.mockResolvedValue({
    duplicate: false,
    pet: {
      member_id: "m_001", name: "小噗", selected_skin: "classic",
      unlocked_skins: ["classic"], mood: "curious", stage: "new_friend",
      message: "先一起积累可靠记录。", streak_days: 1, total_checkins: 1,
      checked_in_today: true, health_basis: "insufficient", profile_version: 1,
    },
  });
  mocked.updatePet.mockImplementation(async (_config, _memberId, name, selectedSkin): Promise<import("./api").PetSnapshot> => ({
    member_id: "m_001", name, selected_skin: selectedSkin,
    unlocked_skins: ["classic"], mood: "curious", stage: "new_friend",
    message: "先一起积累可靠记录。", streak_days: 0, total_checkins: 0,
    checked_in_today: false, health_basis: "insufficient", profile_version: 2,
  }));
  mocked.communityPosts.mockResolvedValue([]);
  mocked.publishCommunityPost.mockResolvedValue({
    post_id: "post_1", agent_alias: "小风的 PoopSense", topic: "hydration",
    content: "今天记得喝水", status: "active", created_at: "2026-08-29T00:00:00Z",
    can_withdraw: true,
  });
  mocked.withdrawCommunityPost.mockResolvedValue({
    post_id: "post_1", agent_alias: "小风的 PoopSense", topic: "hydration",
    content: "今天记得喝水", status: "withdrawn", created_at: "2026-08-29T00:00:00Z",
    can_withdraw: true,
  });
  mocked.agentConnections.mockResolvedValue([]);
});

describe("PoopSense core UI", () => {
  it("claims a pending session only after a member is selected", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /健康/ })[0]);
    expect(await screen.findByText("有 1 次记录等你确认")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "确认归属" });
    expect(button).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("这是谁的记录？"), "m_001");
    await user.click(button);
    await waitFor(() =>
      expect(mocked.claim).toHaveBeenCalledWith(
        expect.anything(),
        "ses_1",
        "m_001",
        false,
      ),
    );
  });

  it("renders factual category ratios without averaging categories", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /健康/ })[0]);
    expect(await screen.findByLabelText("形状长期变化")).toHaveTextContent("还在认识你的日常");
    expect(screen.getByText("正常")).toBeInTheDocument();
  });

  it("still loads authorized member data when viewer cannot manage the claim inbox", async () => {
    mocked.inbox.mockRejectedValue(new ApiError(403, "HOUSEHOLD_ROLE_DENIED"));
    render(<App />);
    await waitFor(() => expect(mocked.members).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /进入 Agent 医生/ }),
    ).toBeInTheDocument();
  });

  it("opens Agent Doctor and performs safety triage", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: /进入 Agent 医生/ }),
    );
    expect(
      screen.getByRole("heading", { name: "Agent 医生" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "需要警惕什么" }));
    expect(await screen.findByText(/立即寻求急诊帮助/)).toBeInTheDocument();
    expect(mocked.agentChat).toHaveBeenCalledWith(
      expect.anything(),
      "m_001",
      "出现血便怎么办",
      undefined,
    );
    await user.click(screen.getByRole("button", { name: "有帮助" }));
    expect(mocked.rateAgentMessage).toHaveBeenCalledWith(expect.anything(), 2, "helpful");
  });

  it("carries the latest result into Agent Doctor as a one-click task", async () => {
    mocked.agentChat.mockClear();
    mocked.sessions.mockResolvedValue([
      {
        session_id: "ses_latest",
        occurred_at: "2026-08-29T12:30:00Z",
        assignment_version: 1,
        assessment_status: "assessed",
        risk_level: "normal",
        message: "本次信号接近你的个人基线。",
      },
    ]);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "问问这次结果 →" }));
    expect(screen.getByText("从首页带来的任务")).toBeInTheDocument();
    expect(screen.getByText("本次信号接近你的个人基线。")).toBeInTheDocument();
    expect(mocked.agentChat).not.toHaveBeenCalled();

    const explain = screen.getByRole("button", { name: "解释这次结果 →" });
    await user.click(explain);
    await waitFor(() => expect(mocked.agentChat).toHaveBeenCalledTimes(1));
    expect(mocked.agentChat).toHaveBeenCalledWith(
      expect.anything(),
      "m_001",
      expect.stringContaining("本次信号接近你的个人基线"),
      undefined,
    );
  });

  it("maps a reliable hard sensor result to the scattered cartoon", async () => {
    mocked.sessions.mockResolvedValue([
      {
        session_id: "ses_dry",
        occurred_at: "2026-08-29T12:30:00Z",
        assignment_version: 1,
        assessment_status: "assessed",
        risk_level: "normal",
        message: "检测到便便呈一颗颗、偏干硬形态",
        visual_profile: {
          mapping_version: "poop-visual-v1",
          variant: "scattered",
          reliable: true,
          shape: { value: "hard", confidence: 0.91, source: "sensor", model_version: "shape-0.1" },
          color: { value: "brown", confidence: 0.88, source: "sensor", model_version: "color-0.2" },
          odor: { value: "moderate", confidence: 0.84, source: "sensor", model_version: "odor-0.1" },
        },
      },
    ]);

    render(<App />);
    const character = await screen.findByAltText("传感器映射的便便卡通形象：分散颗粒");
    expect(character).toHaveAttribute("src", "/poop-shape-scattered-yellow-v2.png");
    expect(character).toHaveAttribute("data-visual-variant", "scattered");
    expect(screen.getByLabelText("本次传感器视觉映射")).toHaveTextContent("棕色");
  });

  it("plays a new-result moment and then automatically asks Agent Doctor once", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocked.agentChat.mockClear();
    mocked.agentChat.mockResolvedValueOnce({
      conversation_id: "conv_dry",
      message: {
        message_id: 8, role: "assistant",
        content: "这次形态偏干硬，今天可以分次补充水分。需要的话，我可以让机器人送一杯水。",
        created_at: "2026-08-30T00:00:00Z",
      },
      decision: "health_education",
      allowed_actions: ["explain", "ask_follow_up", "offer_water_pickup"],
      authorization_basis: "household_owner", policy_version: "safety-v1",
      model_version: "test-model", delegated_agent: "health_doctor",
      skill: "health_education", run_id: "run_dry", skill_version: "1.0.0",
    });
    mocked.sessions
      .mockResolvedValueOnce([])
      .mockResolvedValue([
        {
          session_id: "ses_from_hardware",
          occurred_at: "2026-08-29T13:00:00Z",
          assignment_version: 1,
          assessment_status: "assessed",
          risk_level: "normal",
          message: "检测到便便呈一颗颗、偏干硬形态",
        },
      ]);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(await screen.findByRole("heading", { name: "收到，这次交给我。" })).toBeInTheDocument();
    expect(mocked.agentChat).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "跳过动画" }));
    await waitFor(() => expect(mocked.agentChat).toHaveBeenCalledTimes(1));
    expect(mocked.agentChat).toHaveBeenCalledWith(
      expect.anything(),
      "m_001",
      expect.stringContaining("检测到便便呈一颗颗、偏干硬形态"),
      undefined,
    );
    expect(await screen.findByText("让机械臂帮你取一杯水？")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "准备取水" }));
    expect(mocked.pickupWater).not.toHaveBeenCalled();
    expect(screen.getByText("请确认水杯已放在标定位置，机械臂周围无人和障碍物。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认开始取水" }));
    await waitFor(() => expect(mocked.pickupWater).toHaveBeenCalledWith(expect.anything(), "m_001"));
  });

  it("saves the structured health profile through the versioned profile API", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /健康/ })[0]);
    const diet = await screen.findByPlaceholderText("例如：常吃辣，蔬菜较少");
    await user.type(diet, "蔬菜较少");
    await user.click(screen.getByRole("button", { name: "保存健康档案" }));
    expect(mocked.updateHealthProfile).toHaveBeenCalledWith(
      expect.anything(), "m_001", expect.objectContaining({ diet_pattern: "蔬菜较少" }),
    );
  });

  it("generates and displays an auditable weekly health report", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /健康/ })[0]);
    await user.click(await screen.findByRole("button", { name: "生成本周周报" }));
    expect(mocked.generateWeeklyReport).toHaveBeenCalledWith(expect.anything(), "m_001");
    expect(await screen.findByText(/本周可靠样本不足/)).toBeInTheDocument();
    expect(screen.getByText("依据 safety-v1 · policy-engine")).toBeInTheDocument();
  });

  it("resumes a paused household skill only after confirmation", async () => {
    const user = userEvent.setup();
    const pausedRun = {
      run_id: "run_1", member_id: "m_001", trigger: "user_message",
      goal: "帮我授权家庭成员查看", status: "paused", current_step: 2,
      max_steps: 4, result: {}, error: null,
      created_at: "2026-08-28T00:00:00Z", completed_at: null,
      steps: [
        { step_index: 1, agent_name: "main_agent", skill_name: "route_request", skill_version: "1.0.0", status: "succeeded", output_summary: {}, started_at: null, completed_at: null, error: null },
        { step_index: 2, agent_name: "household_steward", skill_name: "manage_household", skill_version: "1.0.0", status: "waiting_input", output_summary: {}, started_at: null, completed_at: null, error: null },
      ],
      handoffs: [],
    };
    mocked.agentChat.mockResolvedValueOnce({
      conversation_id: "conv_1", decision: "health_education",
      allowed_actions: ["explain"], authorization_basis: "household_owner",
      policy_version: "safety-v1", skill_version: "1.0.0", run_id: "run_1",
      message: { message_id: 3, role: "assistant", content: "请确认继续，或取消本次任务。", created_at: "2026-08-28T00:00:00Z" },
      delegated_agent: "household_steward", skill: "manage_household",
      model_version: "policy-engine",
    });
    mocked.agentRun.mockResolvedValueOnce(pausedRun);
    mocked.resumeAgentRun.mockResolvedValue({
      run: { ...pausedRun, status: "completed", steps: pausedRun.steps.map((step) => ({ ...step, status: "succeeded" })) },
      message: { message_id: 4, role: "assistant", content: "确认已收到。", created_at: "2026-08-28T00:00:01Z" },
    });
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /进入 Agent 医生/ }));
    await user.type(screen.getByLabelText("描述你的情况"), "帮我授权家庭成员查看");
    await user.click(screen.getByRole("button", { name: "发送 →" }));
    await user.click(await screen.findByRole("button", { name: "确认继续" }));
    expect(mocked.resumeAgentRun).toHaveBeenCalledWith(expect.anything(), "run_1", true);
    expect(await screen.findByText("确认已收到。")).toBeInTheDocument();
  });

  it("keeps pet check-ins separate from health facts and supports a daily check-in", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /广场/ })[0]);
    expect(await screen.findByLabelText("便便宠物和皮肤图鉴")).toBeInTheDocument();
    expect(screen.getByText("可靠样本不足，宠物保持探索状态")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "今天打卡" }));
    expect(mocked.checkInPet).toHaveBeenCalledWith(expect.anything(), "m_001");
    expect(await screen.findByRole("button", { name: "今天已打卡" })).toBeDisabled();
  });

  it("publishes to the Agent community only after explicit per-post consent", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /广场/ })[0]);
    await user.click(await screen.findByRole("button", { name: "让 Agent 发一条 →" }));
    const publish = screen.getByRole("button", { name: "确认发布" });
    await user.type(screen.getByLabelText("公开内容"), "今天记得喝水");
    expect(publish).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(publish);
    expect(mocked.publishCommunityPost).toHaveBeenCalledWith(expect.anything(), "m_001", "hydration", "今天记得喝水");
    expect(await screen.findByText("今天记得喝水")).toBeInTheDocument();
  });

  it("requires separate explicit consent before enabling raw data uploads", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /我的/ })[0]);
    const enable = await screen.findByRole("button", { name: "开启限期上传" });
    expect(enable).toBeDisabled();
    await user.click(screen.getByLabelText(/我已了解用途/));
    await user.click(enable);
    expect(mocked.createRawDataAuthorization).toHaveBeenCalledWith(
      expect.anything(), "dev_001", "改进传感分类模型", ["odor"], 7,
    );
  });

  it("adds a household member through the real member API", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    await user.click(screen.getAllByRole("button", { name: /我的/ })[0]);
    await user.click(await screen.findByRole("button", { name: "＋ 添加家庭成员" }));
    await user.type(screen.getByLabelText("成员姓名"), "奶奶");
    await user.click(screen.getByRole("button", { name: "确认添加" }));
    expect(mocked.createMember).toHaveBeenCalledWith(expect.anything(), "奶奶");
  });

  it("keeps the home focused and progressively discloses secondary health tasks", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /进入 Agent 医生/ });
    expect(screen.queryByText("POOP NEWS")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /进入 Agent 医生/ })).toHaveLength(1);

    await user.click(screen.getAllByRole("button", { name: /健康$/ })[0]);
    expect((await screen.findAllByText("本周健康周报")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("让 Agent 更懂你").length).toBeGreaterThan(0);
    expect(screen.getAllByText("最近记录").length).toBeGreaterThan(0);
  });
});
