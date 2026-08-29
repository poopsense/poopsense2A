import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  type AgentAction as AgentActionRecord,
  type AgentConnection,
  type AgentMemory,
  type AgentProfile,
  type AgentProfileRevision,
  type AgentRun,
  type AgentStatus,
  type AppConfig,
  type CommunityPost,
  type Device,
  type Grant,
  type HealthProfile,
  type InboxItem,
  type Member,
  type MemberSession,
  type PetSnapshot,
  type RawDataAuthorization,
  type RobotTask,
  type Trend,
  type TrendDimension,
  type WeeklyHealthReport,
} from "./api";

type View = "home" | "result" | "doctor" | "health" | "social" | "settings";
const DEFAULT_CONFIG: AppConfig = {
  apiBase: "http://127.0.0.1:8000",
  householdId: "hh_001",
  householdKey: "household-secret",
};
const CONFIG_STORAGE_KEY = "poopsense-config-v1";
function loadConfig(): AppConfig {
  try {
    return {
      ...DEFAULT_CONFIG,
      ...JSON.parse(sessionStorage.getItem(CONFIG_STORAGE_KEY) ?? "{}"),
    };
  } catch {
    return DEFAULT_CONFIG;
  }
}
function friendlyError(error: unknown) {
  if (error instanceof ApiError && [401, 403].includes(error.status))
    return "当前账号无权查看这里，请检查家庭身份或授权。";
  if (error instanceof TypeError)
    return "暂时连不上 PoopSense 服务，请确认后端已经启动。";
  if (error instanceof ApiError && error.status === 404)
    return "前后端版本不一致，请重启后端后刷新页面。";
  return "加载失败，请稍后再试。";
}

function memberName(member: Member) {
  const demoNames: Record<string, string> = {
    "Owner profile": "Alex",
    "Second profile": "Sam",
  };
  return (
    demoNames[member.display_name] ??
    member.display_name.replace(/\s+profile$/i, "")
  );
}

export default function App() {
  const [config, setConfig] = useState(loadConfig);
  const [view, setView] = useState<View>("home");
  const [members, setMembers] = useState<Member[]>([]);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [selectedMember, setSelectedMember] = useState("");
  const [trend, setTrend] = useState<Trend | null>(null);
  const [sessions, setSessions] = useState<MemberSession[]>([]);
  const [resultSession, setResultSession] = useState<MemberSession>();
  const [doctorAutoSession, setDoctorAutoSession] = useState<MemberSession>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const viewRef = useRef<View>("home");
  const sessionFeedReady = useRef(false);
  const lastObservedSession = useRef<string | undefined>(undefined);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);
  const refreshCore = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [nextMembers, nextInbox] = await Promise.all([
        api.members(config),
        api
          .inbox(config)
          .catch((caught) =>
            caught instanceof ApiError && caught.status === 403
              ? []
              : Promise.reject(caught),
          ),
      ]);
      setMembers(nextMembers);
      setInbox(nextInbox);
      setSelectedMember(
        (current) => current || nextMembers[0]?.member_id || "",
      );
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }, [config]);
  useEffect(() => {
    void refreshCore();
  }, [refreshCore]);
  useEffect(() => {
    if (!selectedMember) return;
    let active = true;
    sessionFeedReady.current = false;
    lastObservedSession.current = undefined;
    const refreshMemberData = async () => {
      try {
        const [nextTrend, nextSessions] = await Promise.all([
          api.trend(config, selectedMember),
          api.sessions(config, selectedMember),
        ]);
        if (!active) return;
        setTrend(nextTrend);
        setSessions(nextSessions);
        const newest = nextSessions[0];
        if (!sessionFeedReady.current) {
          sessionFeedReady.current = true;
          lastObservedSession.current = newest?.session_id;
          return;
        }
        if (newest && newest.session_id !== lastObservedSession.current) {
          lastObservedSession.current = newest.session_id;
          if (viewRef.current === "home") {
            setResultSession(newest);
            setDoctorAutoSession(undefined);
            setView("result");
          }
        }
      } catch (caught) {
        if (active) setError(friendlyError(caught));
      }
    };
    void refreshMemberData();
    const poll = window.setInterval(() => void refreshMemberData(), 5000);
    return () => {
      active = false;
      window.clearInterval(poll);
    };
  }, [config, selectedMember]);
  async function assign(
    sessionId: string,
    memberId: string,
    correction = false,
  ) {
    setBusy(true);
    setError("");
    try {
      await api.claim(config, sessionId, memberId, correction);
      await refreshCore();
      const [nextTrend, nextSessions] = await Promise.all([
        api.trend(config, selectedMember),
        api.sessions(config, selectedMember),
      ]);
      setTrend(nextTrend);
      setSessions(nextSessions);
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }
  const selected = members.find((item) => item.member_id === selectedMember);
  const selectedName = selected ? memberName(selected) : "你";
  const nav = [
    { id: "home" as const, icon: "⌂", label: "首页" },
    { id: "health" as const, icon: "↗", label: "健康", count: inbox.length },
    { id: "social" as const, icon: "✦", label: "广场" },
    { id: "settings" as const, icon: "◎", label: "我的" },
  ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setView("home")}>
          <span className="brand-mark">✦</span>
          <span>
            <b>POOPSENSE</b>
            <small>SEE. SMELL. SENSE.</small>
          </span>
        </button>
        <nav aria-label="主导航">
          {nav.map((item) => (
            <NavButton
              key={item.id}
              {...item}
              active={view === item.id}
              onClick={() => setView(item.id)}
            />
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="avatar">{selectedName.slice(0, 1)}</span>
          <span>
            <b>{selectedName}</b>
            <small>家庭健康空间</small>
          </span>
        </div>
      </aside>
      <div className="content-shell">
        <header className="topbar">
          <div>
            <b>
              {view === "home"
                ? "TODAY"
                : view === "result"
                  ? "NEW SIGNAL"
                : (
                    {
                      health: "HEALTH",
                      doctor: "AGENT DOCTOR",
                      social: "COMMUNITY",
                      settings: "PROFILE",
                    } as const
                  )[view]}
            </b>
            <small>每一次信号，都值得被温柔读懂</small>
          </div>
          <span className={`service-dot ${error ? "offline" : ""}`}>
            {error ? "连接异常" : "设备在线"}
          </span>
        </header>
        <main className={view === "home" ? "home-main" : undefined}>
          {error && (
            <div className="alert" role="alert">
              <span>!</span>
              {error}
              <button onClick={() => void refreshCore()}>重试</button>
            </div>
          )}
          {view === "home" && (
            <Home
              sessions={sessions}
              inboxCount={inbox.length}
              onDoctor={() => setView("doctor")}
            />
          )}
          {view === "result" && resultSession && (
            <ResultArrival
              session={resultSession}
              onComplete={() => {
                setDoctorAutoSession(resultSession);
                setView("doctor");
              }}
            />
          )}
          {view === "doctor" && (
            <AgentDoctor
              config={config}
              memberId={selectedMember}
              name={selectedName}
              latestSession={sessions[0]}
              autoSession={doctorAutoSession}
              onBack={() => setView("home")}
            />
          )}
          {view === "health" && (
            <Health
              config={config}
              inbox={inbox}
              members={members}
              selected={selectedMember}
              onSelect={setSelectedMember}
              trend={trend}
              sessions={sessions}
              busy={busy}
              onAssign={assign}
            />
          )}
          {view === "social" && <Social config={config} memberId={selectedMember} />}
          {view === "settings" && (
            <Settings
              config={config}
              members={members}
              selectedMember={selectedMember}
              onMembersChanged={() => void refreshCore()}
              onSave={(next) => {
                sessionStorage.setItem(
                  CONFIG_STORAGE_KEY,
                  JSON.stringify(next),
                );
                setConfig(next);
                setView("home");
              }}
            />
          )}
        </main>
      </div>
      <nav className="bottom-nav" aria-label="移动端主导航">
        {nav.map((item) => (
          <NavButton
            key={item.id}
            {...item}
            active={view === item.id}
            onClick={() => setView(item.id)}
          />
        ))}
      </nav>
    </div>
  );
}
function NavButton({
  active,
  label,
  count,
  onClick,
  icon,
}: {
  active: boolean;
  label: string;
  count?: number;
  onClick: () => void;
  icon: string;
}) {
  return (
    <button className={active ? "active" : ""} onClick={onClick}>
      <span className="nav-icon">
        {icon}
        {count ? <i>{count}</i> : null}
      </span>
      <span>{label}</span>
    </button>
  );
}

const POOP_VISUALS = {
  compact: { asset: "/poop-shape-compact-yellow-v2.png", label: "紧实成团" },
  elongated: { asset: "/poop-shape-elongated-yellow-v2.png", label: "顺滑长条" },
  scattered: { asset: "/poop-shape-scattered-yellow-v2.png", label: "分散颗粒" },
  irregular: { asset: "/poop-shape-irregular-yellow-v2.png", label: "不规则形态" },
  uncertain: { asset: "/poopsense-mascot-pop-v1.png", label: "等待可靠判断" },
} as const;

function sessionVisual(session?: MemberSession) {
  const profile = session?.visual_profile;
  const variant = profile?.reliable ? profile.variant : "uncertain";
  return { ...POOP_VISUALS[variant], variant, profile };
}

function Home({
  sessions,
  inboxCount,
  onDoctor,
}: {
  sessions: MemberSession[];
  inboxCount: number;
  onDoctor: () => void;
}) {
  const latest = sessions[0];
  const visual = sessionVisual(latest);
  const state = useMemo(() => {
    if (!latest)
      return {
        tag: "等待新记录",
        title: "今天，也听听身体的话",
        copy: "坐下、感知、分析、洞察——剩下的交给 PoopSense。",
        mark: "READY",
      };
    if (latest.risk_level === "redline")
      return {
        tag: "需要留意",
        title: "有个信号值得认真看",
        copy: "已进入安全流程，请打开完整结果查看下一步。",
        mark: "CHECK",
      };
    if (/无法可靠判断/.test(latest.message))
      return {
        tag: "数据不足",
        title: "这一次还看不清",
        copy: "本次无法可靠判断，PoopSense 不会给出模糊结论。",
        mark: "PAUSE",
      };
    return {
      tag: "节奏平稳",
      title: "很接近你的日常节奏",
      copy: latest.message || "形状、颜色与气味接近你的个人基线。",
      mark: "GOOD",
    };
  }, [latest]);
  return (
    <section className="page home-page">
      <article className="hero-card">
        <div className="hero-copy">
          <div className="status-line">
            <span>{state.tag}</span>
            <time>
              {latest
                ? new Date(latest.occurred_at).toLocaleTimeString("zh-CN", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "随时待命"}
            </time>
          </div>
          <h2>{state.title}</h2>
          <p>{state.copy}</p>
          <div className="hero-actions">
            <button className="comic-button" onClick={onDoctor}>
              {latest ? "问问这次结果 →" : "进入 Agent 医生 →"}
            </button>
          </div>
        </div>
        <div className="hero-art">
          <span className="burst-word">{state.mark}!</span>
          <img
            src={visual.asset}
            alt={`传感器映射的便便卡通形象：${visual.label}`}
            data-visual-variant={visual.variant}
          />
          {visual.profile?.reliable ? (
            <div className="sensor-visual-key" aria-label="本次传感器视觉映射">
              <span><i className="shape" />{visual.label}</span>
              <span><i className="color" />{categoryLabel(visual.profile.color?.value ?? "unknown")}</span>
              <span><i className="odor" />{categoryLabel(visual.profile.odor?.value ?? "unknown")}</span>
            </div>
          ) : null}
        </div>
      </article>
      {inboxCount ? (
        <p className="home-secondary-note">健康页底部有 {inboxCount} 次记录待确认</p>
      ) : null}
    </section>
  );
}

function ResultArrival({
  session,
  onComplete,
}: {
  session: MemberSession;
  onComplete: () => void;
}) {
  const visual = sessionVisual(session);
  useEffect(() => {
    const timer = window.setTimeout(onComplete, 2200);
    return () => window.clearTimeout(timer);
  }, [onComplete]);
  return (
    <section className="result-arrival" aria-live="polite">
      <div className="result-burst" aria-hidden="true">NEW!</div>
      <img
        src={visual.asset}
        alt={`PoopSense 正在读取新的身体信号：${visual.label}`}
        data-visual-variant={visual.variant}
      />
      <div className="result-arrival-copy">
        <small>检测到新的身体信号</small>
        <h1>收到，这次交给我。</h1>
        <p>{session.message}</p>
        <span><i /> Agent 医生正在准备建议…</span>
      </div>
      <button onClick={onComplete}>跳过动画</button>
    </section>
  );
}

function sessionAdvicePrompt(session: MemberSession) {
  const hydrationInstruction = /一颗颗|干硬|偏硬/.test(session.message)
    ? "这是一条偏干硬信号，请给出清楚、克制的补水建议；如果适合，说明可以在用户确认后让机械臂原地取水。"
    : "";
  return `请解释我最近一次记录：时间 ${session.occurred_at}，风险级别 ${session.risk_level}，可靠结论：${session.message}。${hydrationInstruction}请先解释这意味着什么，再告诉我今天最值得做的一件事；不要做医疗诊断。`;
}

function robotErrorMessage(error: unknown) {
  if (!(error instanceof ApiError)) return friendlyError(error);
  const messages: Record<string, string> = {
    PICKUP_TRAJECTORY_NOT_CALIBRATED: "取杯、夹紧和提起动作还没有完成标定，已阻止机械臂启动。",
    ROBOT_UNAVAILABLE: "机械臂上位机没有连接，已安全阻止取水动作。",
    VBOT_NOT_READY: "机器狗路线服务还没连接，已安全阻止机械臂启动。",
    TRANSPORT_SAFE_POSE_NOT_CALIBRATED: "还缺少移动时的安全运输姿态，已阻止机器人启动。",
    TRAJECTORY_NOT_CALIBRATED: "递水动作还没有完成标定，已阻止机器人启动。",
    ROBOT_NOT_LIVE: "机械臂当前不在线，暂时不能取水。",
    TASK_ALREADY_RUNNING: "机械臂正在执行另一项任务。",
  };
  return messages[error.message] ?? "机械臂暂时不能执行取水，请检查设备连接。";
}

type ChatMessage = {
  role: "doctor" | "user";
  text: string;
  messageId?: number;
  feedback?: "helpful" | "not_helpful";
};
function AgentDoctor({
  config,
  memberId,
  name,
  latestSession,
  autoSession,
  onBack,
}: {
  config: AppConfig;
  memberId: string;
  name: string;
  latestSession?: MemberSession;
  autoSession?: MemberSession;
  onBack: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "doctor",
      text: `你好，${name}。我是 PoopSense Agent 医生。我可以结合已认领记录解释身体信号，但不替代医生诊断。`,
    },
  ]);
  const [conversationId, setConversationId] = useState<string>();
  const [historyReady, setHistoryReady] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState("");
  const [delegation, setDelegation] = useState("");
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [availableActions, setAvailableActions] = useState<string[]>([]);
  const [robotTask, setRobotTask] = useState<RobotTask | null>(null);
  const [robotConfirming, setRobotConfirming] = useState(false);
  const [robotBusy, setRobotBusy] = useState(false);
  const [robotMessage, setRobotMessage] = useState("");
  const autoTriggeredSession = useRef<string | undefined>(undefined);
  useEffect(() => {
    let active = true;
    if (!memberId)
      return () => {
        active = false;
      };
    Promise.all([api.agentStatus(config), api.conversations(config, memberId)])
      .then(async ([status, conversations]) => {
        if (!active) return;
        setAgentStatus(status);
        const latest = conversations[0];
        if (!latest) {
          setHistoryReady(true);
          return;
        }
        const history = await api.conversation(config, latest.conversation_id);
        if (!active) return;
        setConversationId(history.conversation_id);
        setMessages(
          history.messages.map((item) => ({
            role: item.role === "assistant" ? "doctor" : "user",
            text: item.content,
            messageId: item.role === "assistant" ? item.message_id : undefined,
          })),
        );
        setHistoryReady(true);
      })
      .catch((caught) => {
        if (active) {
          setChatError(friendlyError(caught));
          setHistoryReady(true);
        }
      });
    return () => {
      active = false;
    };
  }, [config, memberId]);
  async function send(text = draft) {
    const clean = text.trim();
    if (!clean || !memberId || sending) return;
    setMessages((current) => [...current, { role: "user", text: clean }]);
    setDraft("");
    setSending(true);
    setChatError("");
    try {
      const result = await api.agentChat(
        config,
        memberId,
        clean,
        conversationId,
      );
      setConversationId(result.conversation_id);
      setAvailableActions(result.allowed_actions);
      setDelegation(`${agentRoleLabel(result.delegated_agent)} · ${skillLabel(result.skill)}`);
      setAgentRun(await api.agentRun(config, result.run_id));
      setMessages((current) => [
        ...current,
        { role: "doctor", text: result.message.content, messageId: result.message.message_id },
      ]);
    } catch (caught) {
      setChatError(
        caught instanceof ApiError && caught.message === "MODEL_NOT_CONFIGURED"
          ? "模型尚未配置，请在后端设置 POOPSENSE_LLM_API_KEY。"
          : friendlyError(caught),
      );
    } finally {
      setSending(false);
    }
  }
  useEffect(() => {
    if (
      !historyReady ||
      !autoSession ||
      autoTriggeredSession.current === autoSession.session_id
    )
      return;
    autoTriggeredSession.current = autoSession.session_id;
    void send(sessionAdvicePrompt(autoSession));
  }, [autoSession, historyReady]);
  useEffect(() => {
    if (!robotTask?.task_id || ["completed", "failed", "stopped"].includes(robotTask.status)) return;
    const poll = window.setInterval(() => {
      api.robotTask(config, robotTask.task_id)
        .then(setRobotTask)
        .catch((caught) => setRobotMessage(robotErrorMessage(caught)));
    }, 1000);
    return () => window.clearInterval(poll);
  }, [config, robotTask?.task_id, robotTask?.status]);
  async function startWaterPickup() {
    if (robotBusy) return;
    setRobotBusy(true);
    setRobotMessage("");
    try {
      const task = await api.pickupWater(config, memberId);
      setRobotTask(task);
      setRobotConfirming(false);
      setRobotMessage("机械臂已开始取水。请留意周围空间。 ");
    } catch (caught) {
      setRobotMessage(robotErrorMessage(caught));
    } finally {
      setRobotBusy(false);
    }
  }
  async function stopWaterPickup() {
    if (robotBusy) return;
    setRobotBusy(true);
    try {
      await api.stopRobot(config);
      setRobotMessage("已发送停止指令，机械臂正在停止。 ");
      setRobotTask((current) => current ? {
        ...current,
        status: "stopping",
        message: "机械臂正在停止",
      } : current);
    } catch (caught) {
      setRobotMessage(robotErrorMessage(caught));
    } finally {
      setRobotBusy(false);
    }
  }
  async function resolvePausedRun(confirmed: boolean) {
    if (!agentRun || agentRun.status !== "paused" || sending) return;
    setSending(true);
    setChatError("");
    try {
      const result = await api.resumeAgentRun(config, agentRun.run_id, confirmed);
      setAgentRun(result.run);
      setMessages((current) => [
        ...current,
        { role: "doctor", text: result.message.content, messageId: result.message.message_id },
      ]);
    } catch (caught) {
      setChatError(friendlyError(caught));
    } finally {
      setSending(false);
    }
  }
  async function rateMessage(messageId: number, rating: "helpful" | "not_helpful") {
    try {
      await api.rateAgentMessage(config, messageId, rating);
      setMessages((current) => current.map((message) =>
        message.messageId === messageId ? { ...message, feedback: rating } : message));
    } catch (caught) {
      setChatError(friendlyError(caught));
    }
  }
  return (
    <section className="page doctor-page">
      <div className="doctor-head">
        <button onClick={onBack}>← 返回</button>
        <div>
          <h1>Agent 医生</h1>
          <span>
            <i />{" "}
            {agentStatus?.configured
              ? "健康助手在线"
              : "健康助手暂未连接"}
          </span>
          {delegation ? <small className="delegation-status">正在调用 {delegation}</small> : null}
        </div>
      </div>
      <div className="doctor-layout">
        <aside>
          <img src="/poopsense-mascot-pop-v1.png" alt="Agent 医生形象" />
          <b>我能帮你</b>
          <p>
            理解本次记录
            <br />
            查看近期趋势
            <br />
            识别需要就医的信号
          </p>
          <small>健康参考，不作为医疗诊断。</small>
        </aside>
        <article className="chat-panel">
          {latestSession ? (
            <section className="current-result-task" aria-labelledby="current-result-title">
              <div>
                <small>从首页带来的任务</small>
                <b id="current-result-title">理解这次结果</b>
                <p>{latestSession.message}</p>
              </div>
              <button
                disabled={sending}
                onClick={() =>
                  void send(sessionAdvicePrompt(latestSession))
                }
              >
                {sending ? "正在分析…" : "解释这次结果 →"}
              </button>
            </section>
          ) : null}
          {agentRun ? (
            <details className="agent-run-trace">
              <summary>查看本次回答依据与 Agent 协作</summary>
              {agentRun.steps.map((step) => (
                <div key={step.step_index}>
                  <b>{step.step_index}. {agentRoleLabel(step.agent_name)}</b>
                  <span>{skillLabel(step.skill_name)} · {step.status}</span>
                  <small>v{step.skill_version}</small>
                </div>
              ))}
              {agentRun.handoffs.map((handoff) => (
                <div className="agent-handoff-line" key={`${handoff.from_agent}:${handoff.to_agent}:${handoff.skill_name}`}>
                  <b>交接：{agentRoleLabel(handoff.from_agent)} → {agentRoleLabel(handoff.to_agent)}</b>
                  <span>仅传递：{handoff.context_domains.map(contextDomainLabel).join("、")}</span>
                  <small>{skillLabel(handoff.skill_name)} · v{handoff.skill_version}</small>
                </div>
              ))}
              <small>最多 {agentRun.max_steps} 步，任务状态已保存。</small>
              {agentRun.status === "paused" ? (
                <div className="agent-run-actions">
                  <button disabled={sending} onClick={() => void resolvePausedRun(true)}>
                    确认继续
                  </button>
                  <button disabled={sending} onClick={() => void resolvePausedRun(false)}>
                    取消任务
                  </button>
                </div>
              ) : null}
            </details>
          ) : null}
          <div className="quick-prompts">
            <button onClick={() => void send("帮我看看最近趋势")}>
              看看最近趋势
            </button>
            <button onClick={() => void send("最近有点便秘")}>
              便秘怎么办
            </button>
            <button onClick={() => void send("出现血便怎么办")}>
              需要警惕什么
            </button>
            <button onClick={() => void send("请让健康医生和生活教练一起做综合分析")}>
              多专家综合分析
            </button>
          </div>
          {chatError && (
            <p className="chat-error" role="alert">
              {chatError}
            </p>
          )}
          <div className="messages" aria-live="polite">
            {messages.map((message, index) => (
              <div key={index} className={`message ${message.role}`}>
                <b>{message.role === "doctor" ? "Agent 医生" : name}</b>
                <p>{message.text}</p>
                {message.role === "doctor" && message.messageId ? (
                  <div className="message-feedback" aria-label="评价这条建议">
                    <button aria-pressed={message.feedback === "helpful"} onClick={() => void rateMessage(message.messageId!, "helpful")}>有帮助</button>
                    <button aria-pressed={message.feedback === "not_helpful"} onClick={() => void rateMessage(message.messageId!, "not_helpful")}>没帮助</button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
          {availableActions.some((action) => ["offer_water_pickup", "offer_water_delivery"].includes(action)) ? (
            <section className="robot-offer" aria-live="polite">
              <div className="robot-offer-icon" aria-hidden="true">🦾</div>
              <div>
                <small>Agent 建议 · 机械臂取水</small>
                <b>{robotTask
                  ? robotTask.status === "completed" ? "水杯已提起" : "机械臂正在取水"
                  : "让机械臂帮你取一杯水？"}</b>
                <p>
                  {robotTask
                    ? `${robotTask.message ?? robotMessage ?? "任务进行中"}${typeof robotTask.progress === "number" ? ` · ${Math.round(robotTask.progress * 100)}%` : ""}`
                    : robotMessage || "只执行取杯、夹紧和提起；不移动、不递水、不松爪。"}
                </p>
              </div>
              {!robotTask && !robotConfirming ? (
                <button onClick={() => setRobotConfirming(true)}>准备取水</button>
              ) : null}
              {!robotTask && robotConfirming ? (
                <div className="robot-confirm-actions">
                  <p>请确认水杯已放在标定位置，机械臂周围无人和障碍物。</p>
                  <button disabled={robotBusy} onClick={() => void startWaterPickup()}>
                    {robotBusy ? "检查设备中…" : "确认开始取水"}
                  </button>
                  <button disabled={robotBusy} onClick={() => setRobotConfirming(false)}>取消</button>
                </div>
              ) : null}
              {robotTask && ["starting", "running", "stopping"].includes(robotTask.status) ? (
                <button className="robot-stop-button" disabled={robotBusy || robotTask.status === "stopping"} onClick={() => void stopWaterPickup()}>
                  {robotTask.status === "stopping" ? "正在停止…" : "停止机械臂"}
                </button>
              ) : null}
            </section>
          ) : null}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <label className="sr-only" htmlFor="doctor-message">
              描述你的情况
            </label>
            <textarea
              id="doctor-message"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="例如：最近两天有点偏硬，需要注意什么？"
            />
            <button disabled={!draft.trim() || sending}>
              {sending ? "思考中…" : "发送 →"}
            </button>
          </form>
        </article>
      </div>
    </section>
  );
}
function Health({
  config,
  inbox,
  members,
  selected,
  onSelect,
  trend,
  sessions,
  busy,
  onAssign,
}: {
  config: AppConfig;
  inbox: InboxItem[];
  members: Member[];
  selected: string;
  onSelect: (v: string) => void;
  trend: Trend | null;
  sessions: MemberSession[];
  busy: boolean;
  onAssign: (s: string, m: string, c?: boolean) => void;
}) {
  return (
    <section className="page">
      <div className="member-filter">
        <select value={selected} onChange={(e) => onSelect(e.target.value)}>
          {members.map((member) => (
            <option key={member.member_id} value={member.member_id}>
              {memberName(member)}
            </option>
          ))}
        </select>
      </div>
      {trend?.insufficient_coverage && (
        <div className="coverage-note">
          <b>样本覆盖还不够</b>
          <span>
            有效覆盖 {Math.round(trend.valid_sample_coverage * 100)}
            %，暂不做趋势判断，只展示事实。
          </span>
        </div>
      )}
      <div className="metrics">
        <Metric
          label="每周频率"
          value={`${trend?.frequency_per_week ?? 0}`}
          unit=" 次"
        />
        <Metric
          label="连续异常"
          value={`${trend?.consecutive_abnormal ?? 0}`}
          unit=" 次"
        />
      </div>
      <TrendMap trend={trend} />
      <details className="progressive-panel">
        <summary><b>本周健康周报</b><span>把可靠记录整理成一页结论</span></summary>
        <WeeklyReportPanel config={config} memberId={selected} />
      </details>
      <details className="progressive-panel">
        <summary><b>让 Agent 更懂你</b><span>健康档案与可修改记忆</span></summary>
        <HealthProfilePanel config={config} memberId={selected} />
        <MemoryPanel config={config} memberId={selected} />
      </details>
      <details className="progressive-panel">
        <summary><b>最近记录</b><span>{sessions.length} 次已归属记录</span></summary>
        <article className="history">
        {!sessions.length && <p className="muted">还没有已认领记录。</p>}
        {sessions.slice(0, 2).map((item) => (
          <div className="history-row" key={item.session_id}>
            <span className={`risk ${item.risk_level}`}>
              {item.risk_level === "redline" ? "!" : "✓"}
            </span>
            <span>
              <b>{new Date(item.occurred_at).toLocaleDateString("zh-CN")}</b>
              <small>{item.message}</small>
            </span>
            <Correction
              session={item}
              members={members}
              current={selected}
              onCorrect={onAssign}
            />
          </div>
        ))}
        {sessions.length > 2 && (
          <details className="history-more">
            <summary>查看更早的 {sessions.length - 2} 条记录</summary>
            {sessions.slice(2).map((item) => (
              <div className="history-row" key={item.session_id}>
                <span className={`risk ${item.risk_level}`}>
                  {item.risk_level === "redline" ? "!" : "✓"}
                </span>
                <span>
                  <b>
                    {new Date(item.occurred_at).toLocaleDateString("zh-CN")}
                  </b>
                  <small>{item.message}</small>
                </span>
                <Correction
                  session={item}
                  members={members}
                  current={selected}
                  onCorrect={onAssign}
                />
              </div>
            ))}
          </details>
        )}
        </article>
      </details>
      <InboxPanel
        inbox={inbox}
        members={members}
        busy={busy}
        onAssign={onAssign}
      />
    </section>
  );
}

function WeeklyReportPanel({ config, memberId }: { config: AppConfig; memberId: string }) {
  const [reports, setReports] = useState<WeeklyHealthReport[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setError("");
    api.weeklyReports(config, memberId)
      .then((result) => { if (active) setReports(result); })
      .catch((caught) => { if (active) setError(friendlyError(caught)); });
    return () => { active = false; };
  }, [config, memberId]);

  async function generateReport() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const report = await api.generateWeeklyReport(config, memberId);
      setReports((current) => [report, ...current.filter((item) => item.report_id !== report.report_id)]);
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }

  const latest = reports[0];
  return (
    <article className="weekly-report-panel" aria-label="健康周报">
      <div className="weekly-report-head">
        <div className="card-title"><span>WEEKLY</span><h2>健康周报</h2></div>
        <button type="button" onClick={generateReport} disabled={busy}>
          {busy ? "生成中…" : latest ? "刷新本周周报" : "生成本周周报"}
        </button>
      </div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {!latest ? <p className="muted">还没有周报。生成后会把可靠事实、建议与 Agent 解释保存在一起。</p> : (
        <div className="weekly-report-body">
          <div>
            <small>{latest.period_start} — {latest.period_end}</small>
            <strong>{latest.status === "ready" ? "本周洞察" : "样本积累中"}</strong>
            <p>{latest.summary}</p>
          </div>
          <div className="weekly-facts" aria-label="周报事实">
            <span><b>{latest.facts.valid_sessions}</b>可靠记录</span>
            <span><b>{Math.round(latest.facts.coverage * 100)}%</b>有效覆盖</span>
            <span><b>{latest.facts.consecutive_abnormal}</b>连续异常</span>
          </div>
          <ul>{latest.recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
          <small>依据 {latest.policy_version} · {latest.model_version}</small>
        </div>
      )}
    </article>
  );
}

const EMPTY_HEALTH_PROFILE: HealthProfile = {
  member_id: "", conditions: [], diet_pattern: "", sleep_pattern: "",
  medications: [], goals: [], completeness: 0, updated_at: null,
};

function splitList(value: string) {
  return value.split(/[，,、]/).map((item) => item.trim()).filter(Boolean);
}

function HealthProfilePanel({ config, memberId }: { config: AppConfig; memberId: string }) {
  const [profile, setProfile] = useState<HealthProfile>(EMPTY_HEALTH_PROFILE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api.healthProfile(config, memberId)
      .then((result) => { if (active) setProfile(result); })
      .catch((caught) => { if (active) setError(friendlyError(caught)); });
    return () => { active = false; };
  }, [config, memberId]);
  async function save() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setProfile(await api.updateHealthProfile(config, memberId, profile));
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="health-profile-panel">
      <div className="card-title"><span>PROFILE</span><h2>让 Agent 更懂你</h2></div>
      <p className="muted">自报档案完成 {Math.round(profile.completeness * 100)}% · 每次修改都会保留版本。</p>
      <div className="health-profile-grid">
        <label>已有状况<input value={profile.conditions.join("、")} onChange={(event) => setProfile({ ...profile, conditions: splitList(event.target.value) })} placeholder="例如：肠易激、无" /></label>
        <label>饮食习惯<input value={profile.diet_pattern} onChange={(event) => setProfile({ ...profile, diet_pattern: event.target.value })} placeholder="例如：常吃辣，蔬菜较少" /></label>
        <label>作息情况<input value={profile.sleep_pattern} onChange={(event) => setProfile({ ...profile, sleep_pattern: event.target.value })} placeholder="例如：00:30 入睡" /></label>
        <label>正在使用的药物<input value={profile.medications.join("、")} onChange={(event) => setProfile({ ...profile, medications: splitList(event.target.value) })} placeholder="没有可留空" /></label>
        <label>健康目标<input value={profile.goals.join("、")} onChange={(event) => setProfile({ ...profile, goals: splitList(event.target.value) })} placeholder="例如：规律排便、多喝水" /></label>
      </div>
      <button disabled={busy} onClick={() => void save()}>{busy ? "保存中…" : "保存健康档案"}</button>
      {error ? <p className="chat-error" role="alert">{error}</p> : null}
    </article>
  );
}

function MemoryPanel({
  config,
  memberId,
}: {
  config: AppConfig;
  memberId: string;
}) {
  const [memory, setMemory] = useState<AgentMemory[]>([]);
  const [keyDraft, setKeyDraft] = useState("");
  const [contentDraft, setContentDraft] = useState("");
  const [editing, setEditing] = useState<string>();
  const [editDraft, setEditDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    if (!memberId) return;
    setMemory(await api.memory(config, memberId));
  }, [config, memberId]);
  useEffect(() => {
    void refresh().catch((caught) => setError(friendlyError(caught)));
  }, [refresh]);
  async function add() {
    if (!keyDraft.trim() || !contentDraft.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.addMemory(
        config,
        memberId,
        keyDraft.trim(),
        contentDraft.trim(),
      );
      setKeyDraft("");
      setContentDraft("");
      await refresh();
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }
  async function save(item: AgentMemory) {
    if (!editDraft.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.updateMemory(
        config,
        memberId,
        item.logical_id,
        editDraft.trim(),
        item.source_type === "system_inference"
          ? "用户纠正系统推断"
          : undefined,
      );
      setEditing(undefined);
      await refresh();
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="memory-panel">
      <div className="card-title">
        <span>MEMORY</span>
        <h2>Agent 记忆</h2>
      </div>
      <p className="muted">
        自报信息可修改，系统推断可纠正，传感事实不可覆盖。
      </p>
      <div className="memory-list">
        {memory.map((item) => (
          <div className="memory-row" key={item.logical_id}>
            <span className={`memory-source ${item.source_type}`}>
              {memorySourceLabel(item.source_type)}
            </span>
            <div>
              <b>{item.memory_key}</b>
              {editing === item.logical_id ? (
                <textarea
                  value={editDraft}
                  onChange={(event) => setEditDraft(event.target.value)}
                />
              ) : (
                <p>{item.content}</p>
              )}
              <small>
                v{item.version} ·{" "}
                {new Date(item.created_at).toLocaleDateString("zh-CN")}
              </small>
            </div>
            {item.editable ? (
              editing === item.logical_id ? (
                <button onClick={() => void save(item)} disabled={busy}>
                  保存
                </button>
              ) : (
                <button
                  onClick={() => {
                    setEditing(item.logical_id);
                    setEditDraft(item.content);
                  }}
                >
                  修改
                </button>
              )
            ) : (
              <em>事实锁定</em>
            )}
          </div>
        ))}
        {!memory.length && (
          <p className="muted">还没有记忆，可以先告诉 Agent 一件重要的事。</p>
        )}
      </div>
      <div className="memory-add">
        <input
          aria-label="记忆名称"
          value={keyDraft}
          onChange={(event) => setKeyDraft(event.target.value)}
          placeholder="例如：饮食偏好"
        />
        <input
          aria-label="记忆内容"
          value={contentDraft}
          onChange={(event) => setContentDraft(event.target.value)}
          placeholder="例如：平时很少吃辣"
        />
        <button
          onClick={() => void add()}
          disabled={busy || !keyDraft.trim() || !contentDraft.trim()}
        >
          ＋ 添加自报
        </button>
      </div>
      {error && (
        <p className="chat-error" role="alert">
          {error}
        </p>
      )}
    </article>
  );
}
function memorySourceLabel(value: AgentMemory["source_type"]) {
  return {
    self_report: "用户自报",
    sensor_fact: "传感事实",
    system_inference: "系统推断",
  }[value];
}
function InboxPanel({
  inbox,
  members,
  busy,
  onAssign,
}: {
  inbox: InboxItem[];
  members: Member[];
  busy: boolean;
  onAssign: (s: string, m: string) => void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  return (
    <article className="inbox-panel">
      <div>
        <span className="inbox-count">{inbox.length}</span>
        <div>
          <p className="kicker">家庭待认领箱</p>
          <h2>
            {inbox.length
              ? `有 ${inbox.length} 次记录等你确认`
              : "今天的记录都归位了"}
          </h2>
          <p>认领前不会进入个人趋势，也不会生成定向提醒。</p>
        </div>
      </div>
      {inbox.map((item) => (
        <div className="claim-row" key={item.session_id}>
          <span>
            {new Date(item.received_at).toLocaleString("zh-CN", {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
          <select
            aria-label="这是谁的记录？"
            value={choices[item.session_id] ?? ""}
            onChange={(e) =>
              setChoices({ ...choices, [item.session_id]: e.target.value })
            }
          >
            <option value="">这是谁的记录？</option>
            {members.map((member) => (
              <option key={member.member_id} value={member.member_id}>
                {memberName(member)}
              </option>
            ))}
          </select>
          <button
            disabled={busy || !choices[item.session_id]}
            onClick={() => onAssign(item.session_id, choices[item.session_id])}
          >
            确认归属
          </button>
        </div>
      ))}
    </article>
  );
}
const PET_SKINS: { id: PetSnapshot["selected_skin"]; label: string }[] = [
  { id: "classic", label: "经典奶油" },
  { id: "blue_wave", label: "蓝色波浪" },
  { id: "pop_star", label: "波普明星" },
];

function Social({ config, memberId }: { config: AppConfig; memberId: string }) {
  const [notice, setNotice] = useState("");
  const [pet, setPet] = useState<PetSnapshot | null>(null);
  const [petName, setPetName] = useState("");
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [connections, setConnections] = useState<AgentConnection[]>([]);
  const [composeOpen, setComposeOpen] = useState(false);
  const [topic, setTopic] = useState<CommunityPost["topic"]>("hydration");
  const [postContent, setPostContent] = useState("");
  const [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    if (!memberId) return () => { active = false; };
    Promise.allSettled([api.pet(config, memberId), api.communityPosts(config), api.agentConnections(config, memberId)])
      .then(([petResult, postResults, connectionResults]) => {
        if (!active) return;
        if (petResult.status === "fulfilled") { setPet(petResult.value); setPetName(petResult.value.name); }
        if (postResults.status === "fulfilled") setPosts(postResults.value);
        if (connectionResults.status === "fulfilled") setConnections(connectionResults.value);
        const failed = [petResult, postResults, connectionResults].find((result) => result.status === "rejected");
        if (failed?.status === "rejected") setNotice(friendlyError(failed.reason));
      });
    return () => { active = false; };
  }, [config, memberId]);
  async function checkIn() {
    if (!memberId || busy) return;
    setBusy(true);
    try {
      const result = await api.checkInPet(config, memberId);
      setPet(result.pet);
      setNotice(result.duplicate ? "今天已经打过卡啦。" : "打卡成功，宠物成长值已记录。");
    } catch (caught) {
      setNotice(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }
  async function savePet(selectedSkin = pet?.selected_skin) {
    if (!memberId || !pet || !selectedSkin || !petName.trim() || busy) return;
    setBusy(true);
    try {
      const updated = await api.updatePet(config, memberId, petName.trim(), selectedSkin);
      setPet(updated);
      setPetName(updated.name);
      setNotice("宠物档案已保存。");
    } catch (caught) {
      setNotice(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  }
  async function publishPost() {
    if (!memberId || !consented || postContent.trim().length < 2 || busy) return;
    setBusy(true);
    try {
      const created = await api.publishCommunityPost(config, memberId, topic, postContent.trim());
      setPosts((current) => [created, ...current]);
      setPostContent(""); setConsented(false); setComposeOpen(false);
      setNotice("已由你的 Agent 发布，可随时撤回。");
    } catch (caught) { setNotice(friendlyError(caught)); }
    finally { setBusy(false); }
  }
  async function withdrawPost(postId: string) {
    if (busy) return;
    setBusy(true);
    try {
      await api.withdrawCommunityPost(config, postId);
      setPosts((current) => current.filter((post) => post.post_id !== postId));
      setNotice("内容已撤回，社区不再展示。");
    } catch (caught) { setNotice(friendlyError(caught)); }
    finally { setBusy(false); }
  }
  async function requestConnection(postId: string) {
    if (busy) return; setBusy(true);
    try { const item = await api.requestAgentConnection(config, memberId, postId); setConnections((current) => [item, ...current]); setNotice("邀请已发送，等待对方明确同意。"); }
    catch (caught) { setNotice(friendlyError(caught)); } finally { setBusy(false); }
  }
  async function respondConnection(connectionId: string, accept: boolean) {
    if (busy) return; setBusy(true);
    try { const item = await api.respondAgentConnection(config, memberId, connectionId, accept); setConnections((current) => current.map((entry) => entry.connection_id === item.connection_id ? item : entry)); }
    catch (caught) { setNotice(friendlyError(caught)); } finally { setBusy(false); }
  }
  async function endConnection(connectionId: string) {
    if (busy) return; setBusy(true);
    try { const item = await api.endAgentConnection(config, memberId, connectionId); setConnections((current) => current.map((entry) => entry.connection_id === item.connection_id ? item : entry)); }
    catch (caught) { setNotice(friendlyError(caught)); } finally { setBusy(false); }
  }
  return (
    <section className="page social-page">
      <div className="social-collage">
        <article className="social-poster">
          <span>ANP COMMUNITY</span>
          <h2>
            让你的 Agent
            <br />
            认识新朋友
          </h2>
          <p>由用户授权 Agent 参与主题交流，不公开原始健康记录。</p>
          <button
            onClick={() => setComposeOpen((open) => !open)}
          >
            {composeOpen ? "收起发布框" : "让 Agent 发一条 →"}
          </button>
        </article>
        <article className="social-note">
          <b>健康交流</b>
          <p>
            饮食经验
            <br />
            生活习惯
            <br />
            匿名问答
          </p>
          <button
            onClick={() => { setTopic("diet"); setComposeOpen(true); setNotice("请只填写你愿意公开交流的文字。"); }}
          >
            去交流 →
          </button>
        </article>
        <article className={`social-doodle pet-card ${pet?.selected_skin ?? "classic"}`} aria-label="便便宠物和皮肤图鉴">
          <b>便便宠物</b>
          {pet ? (
            <>
              <img src="/poopsense-mascot-pop-v1.png" alt={`${pet.name}，${petMoodLabel(pet.mood)}`} />
              <input aria-label="宠物名字" value={petName} onChange={(event) => setPetName(event.target.value)} />
              <span>{petMoodLabel(pet.mood)} · {petStageLabel(pet.stage)} · 连续 {pet.streak_days} 天</span>
              <p>{pet.message}</p>
              <button disabled={busy || pet.checked_in_today} onClick={() => void checkIn()}>
                {pet.checked_in_today ? "今天已打卡" : "今天打卡"}
              </button>
              <div className="pet-skins" aria-label="宠物皮肤">
                {PET_SKINS.map((skin) => {
                  const unlocked = pet.unlocked_skins.includes(skin.id);
                  return <button key={skin.id} disabled={busy || !unlocked} aria-pressed={pet.selected_skin === skin.id} onClick={() => void savePet(skin.id)}>{unlocked ? skin.label : `🔒 ${skin.label}`}</button>;
                })}
              </div>
              <button disabled={busy || !petName.trim()} onClick={() => void savePet()}>保存名字</button>
              <small>{pet.health_basis === "insufficient" ? "可靠样本不足，宠物保持探索状态" : "状态来自已放行的可靠健康摘要"}</small>
            </>
          ) : <span>正在叫醒你的宠物…</span>}
        </article>
      </div>
      {composeOpen ? (
        <section className="community-compose" aria-label="发布到 Agent 社区">
          <h2>由 Agent 代你发布</h2>
          <select aria-label="社区主题" value={topic} onChange={(event) => setTopic(event.target.value as CommunityPost["topic"])}>
            <option value="hydration">喝水</option><option value="diet">饮食</option>
            <option value="routine">生活规律</option><option value="encouragement">互相鼓励</option>
          </select>
          <textarea aria-label="公开内容" maxLength={280} value={postContent} onChange={(event) => setPostContent(event.target.value)} placeholder="只写你愿意公开的话，不会自动带入健康记录" />
          <label><input type="checkbox" checked={consented} onChange={(event) => setConsented(event.target.checked)} /> 我确认公开这段文字；不包含原始观测和家庭身份</label>
          <button disabled={busy || !consented || postContent.trim().length < 2} onClick={() => void publishPost()}>确认发布</button>
        </section>
      ) : null}
      <details className="progressive-panel social-progressive">
        <summary><b>Agent 社区动态</b><span>{posts.length} 条公开内容</span></summary>
        <section className="community-feed" aria-label="Agent 社区动态">
        {posts.length ? posts.map((post) => (
          <article key={post.post_id}>
            <b>{post.agent_alias}</b><small>{communityTopicLabel(post.topic)}</small>
            <p>{post.content}</p>
            {post.can_withdraw ? <button disabled={busy} onClick={() => void withdrawPost(post.post_id)}>撤回</button> : null}
            {!post.can_withdraw ? <button disabled={busy} onClick={() => void requestConnection(post.post_id)}>让 Agent 认识一下</button> : null}
          </article>
        )) : <p>还没有动态。第一条也必须由你明确确认后才会出现。</p>}
        </section>
      </details>
      <details className="progressive-panel social-progressive">
        <summary><b>我的 Agent 连接</b><span>{connections.length} 个连接</span></summary>
        <section className="community-feed" aria-label="Agent 连接">
        {connections.length ? connections.map((item) => <article key={item.connection_id}>
          <b>{item.other_agent_alias}</b><small>{agentConnectionLabel(item)}</small>
          <p>连接不共享健康记录；双方都可以随时断开。</p>
          {item.can_respond ? <div><button onClick={() => void respondConnection(item.connection_id, true)}>接受</button><button onClick={() => void respondConnection(item.connection_id, false)}>拒绝</button></div> : null}
          {item.can_end ? <button onClick={() => void endConnection(item.connection_id)}>断开</button> : null}
        </article>) : <p>还没有连接。认识邀请必须由双方分别确认。</p>}
        </section>
      </details>
      {notice && (
        <div className="social-toast" role="status">
          {notice}
          <button onClick={() => setNotice("")}>×</button>
        </div>
      )}
    </section>
  );
}

function petMoodLabel(value: PetSnapshot["mood"]) {
  return { curious: "好奇观察中", cheerful: "精神很好", concerned: "有点担心你" }[value];
}

function petStageLabel(value: PetSnapshot["stage"]) {
  return { new_friend: "新朋友", companion: "陪伴期", grown_up: "成熟期" }[value];
}
function communityTopicLabel(value: CommunityPost["topic"]) {
  return { hydration: "喝水", diet: "饮食", routine: "生活规律", encouragement: "互相鼓励" }[value];
}
function agentConnectionLabel(item: AgentConnection) {
  if (item.status === "connected") return "已连接";
  if (item.status === "rejected") return "已拒绝";
  if (item.status === "ended") return "已断开";
  return item.direction === "inbound" ? "等你确认" : "等待对方确认";
}
function Correction({
  session,
  members,
  current,
  onCorrect,
}: {
  session: MemberSession;
  members: Member[];
  current: string;
  onCorrect: (s: string, m: string, c?: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  if (!open)
    return (
      <button className="text-button" onClick={() => setOpen(true)}>
        纠正归属
      </button>
    );
  return (
    <div className="correction">
      <select value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="">改为…</option>
        {members
          .filter((m) => m.member_id !== current)
          .map((m) => (
            <option key={m.member_id} value={m.member_id}>
              {memberName(m)}
            </option>
          ))}
      </select>
      <button
        disabled={!target}
        onClick={() => {
          onCorrect(session.session_id, target, true);
          setOpen(false);
        }}
      >
        确认
      </button>
    </div>
  );
}
function Metric({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit: string;
}) {
  return (
    <article>
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{unit}</span>
    </article>
  );
}

const TREND_AXES = [
  { key: "shape", label: "形状", symbol: "●" },
  { key: "color", label: "颜色", symbol: "◐" },
  { key: "odor", label: "气味", symbol: "≈" },
];

function trendDeviation(data?: TrendDimension) {
  if (!data || data.baseline_status === "insufficient") return 0;
  return Math.max(0, Math.min(1, data.baseline_deviation_rate ?? 0));
}

function trendStateLabel(data?: TrendDimension) {
  if (!data || data.baseline_status === "insufficient") return "还在认识你的日常";
  if (data.baseline_status === "within_baseline") return "和平常差不多";
  return "最近变化比较明显";
}

function categoryColor(dimension: string, category: string, index: number) {
  const colors: Record<string, Record<string, string>> = {
    shape: { normal: "#c9f5e6", hard: "#ff087f", loose: "#0964e8" },
    color: { brown: "#9b5b34", yellow: "#ffdc18", green: "#64c466", black: "#242424" },
    odor: { mild: "#c9f5e6", moderate: "#ffdc18", strong: "#ff087f" },
  };
  return colors[dimension]?.[category] ?? ["#0964e8", "#ff087f", "#ffdc18", "#c9f5e6"][index % 4];
}

function TrendMap({ trend }: { trend: Trend | null }) {
  const dimensions = trend?.dimensions ?? {};

  return (
    <article className="trend-map" aria-label={`近 ${trend?.period_days ?? 30} 天的长期变化`}>
      {TREND_AXES.map((axis) => {
        const data = dimensions[axis.key];
        const ratios = Object.entries(data?.category_ratios ?? {});
        const deviation = trendDeviation(data);
        const recentPosition = data?.baseline_status === "insufficient" ? 50 : 12 + deviation * 76;
        return (
          <section className={`trend-lane ${axis.key}`} key={axis.key} aria-label={`${axis.label}长期变化`}>
            <div className="trend-lane-icon" aria-hidden="true">{axis.symbol}</div>
            <div className="trend-lane-main">
              <header>
                <b>{axis.label}</b>
                <span className={data?.baseline_status ?? "insufficient"}>{trendStateLabel(data)}</span>
              </header>
              <div className="trend-track" aria-hidden="true">
                <i style={{ width: `${recentPosition}%` }} />
                <em style={{ left: `${recentPosition}%` }} />
                <small>日常</small><small>最近</small>
              </div>
              <div className="trend-legend">
                {ratios.length ? ratios.map(([category, ratio], index) => (
                  <span key={category}>
                    <i style={{ background: categoryColor(axis.key, category, index) }} />
                    {categoryLabel(category)} <b>{Math.round(ratio * 100)}%</b>
                  </span>
                )) : <span>可靠记录积累中</span>}
              </div>
            </div>
          </section>
        );
      })}
    </article>
  );
}

function categoryLabel(value: string) {
  return (
    (
      {
        normal: "正常",
        hard: "偏硬",
        loose: "偏稀",
        brown: "棕色",
        moderate: "中等",
        mild: "轻微",
        strong: "明显",
        yellow: "黄色",
        green: "绿色",
        black: "黑色",
        unknown: "待判断",
      } as Record<string, string>
    )[value] ?? value
  );
}
function agentActionLabel(value: string) {
  return (
    (
      {
        agent_chat_response: "医生回复",
        redline_notification: "红线通知",
        llm_send_check_in: "主动关心",
        llm_no_action: "保持安静",
        llm_redline_notification: "红线调度",
      } as Record<string, string>
    )[value] ?? value
  );
}

function agentRoleLabel(value: string) {
  return ({
    main_agent: "主 Agent",
    health_doctor: "健康医生",
    life_coach: "生活教练",
    household_steward: "家庭管家",
  } as Record<string, string>)[value] ?? value;
}

function contextDomainLabel(value: string) {
  return ({
    trend: "趋势摘要",
    recent_assessments: "近期可靠评估",
    visible_memory: "已授权记忆",
    self_report_memory: "用户自报记忆",
    household_scope: "家庭空间信息",
  } as Record<string, string>)[value] ?? value;
}

function skillLabel(value: string) {
  return ({
    route_request: "理解并委派",
    explain_record: "解释记录",
    summarize_trend: "总结趋势",
    health_education: "健康解释",
    lifestyle_coaching: "生活方式教练",
    urgent_care: "红线安全处理",
    send_check_in: "主动关怀",
    manage_household: "家庭事务",
  } as Record<string, string>)[value] ?? value;
}
function agentActionStatus(value: string) {
  return (
    (
      {
        succeeded: "已完成",
        pending: "待执行",
        processing: "执行中",
        failed: "失败",
        cancelled_by_revocation: "授权撤回",
        cancelled_by_assignment_correction: "归属已纠正",
      } as Record<string, string>
    )[value] ?? value
  );
}
function Settings({
  config,
  members,
  selectedMember,
  onSave,
  onMembersChanged,
}: {
  config: AppConfig;
  members: Member[];
  selectedMember: string;
  onSave: (c: AppConfig) => void;
  onMembersChanged: () => void;
}) {
  const [draft, setDraft] = useState(config);
  const [devices, setDevices] = useState<Device[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [agentActions, setAgentActions] = useState<AgentActionRecord[]>([]);
  const [agentProfile, setAgentProfile] = useState<AgentProfile | null>(null);
  const [profileHistory, setProfileHistory] = useState<AgentProfileRevision[]>([]);
  const [rawAuthorizations, setRawAuthorizations] = useState<RawDataAuthorization[]>([]);
  const [rawConsent, setRawConsent] = useState(false);
  const [rawTypes, setRawTypes] = useState<string[]>(["odor"]);
  const [rawPurpose, setRawPurpose] = useState("改进传感分类模型");
  const [rawRetentionDays, setRawRetentionDays] = useState(7);
  const [newMemberName, setNewMemberName] = useState("");
  const [addingMember, setAddingMember] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [deviceOpen, setDeviceOpen] = useState(false);
  const activeGrant = grants.find(
    (item) => item.status === "active" && item.viewer_user_id === "u_viewer",
  );
  const grantOn = Boolean(activeGrant);
  useEffect(() => {
    let active = true;
    Promise.all([
      api.devices(config),
      selectedMember ? api.grants(config, selectedMember) : Promise.resolve([]),
      api.agentStatus(config),
      api.agentActions(config),
      selectedMember ? api.agentProfile(config, selectedMember) : Promise.resolve(null),
      selectedMember ? api.agentProfileHistory(config, selectedMember) : Promise.resolve([]),
      api.rawDataAuthorizations(config).catch((caught) => caught instanceof ApiError && caught.status === 404 ? [] : Promise.reject(caught)),
    ])
      .then(([nextDevices, nextGrants, nextAgentStatus, nextAgentActions, nextAgentProfile, nextHistory, nextRawAuthorizations]) => {
        if (active) {
          setDevices(nextDevices);
          setGrants(nextGrants);
          setAgentStatus(nextAgentStatus);
          setAgentActions(nextAgentActions);
          setAgentProfile(nextAgentProfile);
          setProfileHistory(nextHistory);
          setRawAuthorizations(nextRawAuthorizations);
        }
      })
      .catch((caught) => {
        if (active) setSettingsError(friendlyError(caught));
      });
    return () => {
      active = false;
    };
  }, [config, selectedMember]);
  const device = devices[0];
  async function toggleGrant() {
    if (!selectedMember || settingsBusy) return;
    setSettingsBusy(true);
    setSettingsError("");
    try {
      if (activeGrant) await api.revokeGrant(config, activeGrant.grant_id);
      else await api.createGrant(config, selectedMember, "u_viewer");
      setGrants(await api.grants(config, selectedMember));
    } catch (caught) {
      setSettingsError(friendlyError(caught));
    } finally {
      setSettingsBusy(false);
    }
  }
  async function saveAgentProfile() {
    if (!agentProfile || !selectedMember || settingsBusy) return;
    setSettingsBusy(true);
    setSettingsError("");
    try {
      const updated = await api.updateAgentProfile(config, selectedMember, agentProfile);
      setAgentProfile(updated);
      setProfileHistory(await api.agentProfileHistory(config, selectedMember));
    } catch (caught) {
      setSettingsError(friendlyError(caught));
    } finally {
      setSettingsBusy(false);
    }
  }
  async function createRawAuthorization() {
    if (!device || !rawConsent || !rawTypes.length || settingsBusy) return;
    setSettingsBusy(true); setSettingsError("");
    try {
      await api.createRawDataAuthorization(config, device.device_id, rawPurpose, rawTypes, rawRetentionDays);
      setRawAuthorizations(await api.rawDataAuthorizations(config));
      setRawConsent(false);
    } catch (caught) { setSettingsError(friendlyError(caught)); }
    finally { setSettingsBusy(false); }
  }
  async function addMember() {
    const name = newMemberName.trim();
    if (!name || settingsBusy) return;
    setSettingsBusy(true); setSettingsError("");
    try {
      await api.createMember(config, name);
      setNewMemberName(""); setAddingMember(false); onMembersChanged();
    } catch (caught) { setSettingsError(friendlyError(caught)); }
    finally { setSettingsBusy(false); }
  }
  async function revokeRawAuthorization(authorizationId: string) {
    if (settingsBusy) return;
    setSettingsBusy(true); setSettingsError("");
    try {
      await api.revokeRawDataAuthorization(config, authorizationId);
      setRawAuthorizations(await api.rawDataAuthorizations(config));
    } catch (caught) { setSettingsError(friendlyError(caught)); }
    finally { setSettingsBusy(false); }
  }
  async function completeRawDeletion(authorizationId: string) {
    if (settingsBusy) return;
    setSettingsBusy(true); setSettingsError("");
    try {
      await api.completeRawDataDeletion(config, authorizationId);
      setRawAuthorizations(await api.rawDataAuthorizations(config));
    } catch (caught) { setSettingsError(friendlyError(caught)); }
    finally { setSettingsBusy(false); }
  }
  return (
    <section className="page settings">
      <div className="profile-grid">
        <article className="device-card">
          <span className="sticker">DEVICE</span>
          <div className="device-visual">
            <img
              src="/poopsense-device-pop-v2.png"
              alt="PoopSense 智能马桶座圈"
            />
          </div>
          <div>
            <h2>浴室 PoopSense</h2>
            <p>
              <i /> {device?.status === "online" ? "在线" : "未连接"} ·{" "}
              {device?.last_seen_at ? "已同步" : "暂无数据"}
            </p>
            <small>
              固件 {device?.firmware_version ?? "未知"} · 本地原始数据保护开启
            </small>
            {deviceOpen && (
              <p className="device-details">
                设备 ID：{device?.device_id ?? "暂无设备"}
                <br />
                模型：{device?.model_version ?? "未知"}
                <br />
                最近同步：
                {device?.last_seen_at
                  ? new Date(device.last_seen_at).toLocaleString("zh-CN")
                  : "暂无"}
              </p>
            )}
          </div>
          <button onClick={() => setDeviceOpen((value) => !value)}>
            {deviceOpen ? "收起详情 ↑" : "设备详情 →"}
          </button>
        </article>
        <article className="manage-card">
          <span className="sticker">FAMILY</span>
          <h2>家庭成员</h2>
          {members.map((member) => (
            <div className="member-line" key={member.member_id}>
              <span className="avatar">{memberName(member).slice(0, 1)}</span>
              <span>
                <b>{memberName(member)}</b>
                <small>
                  {member.linked_to_current_user ? "我的档案" : "家庭成员"}
                </small>
              </span>
              <em>{member.linked_to_current_user ? "本人" : "已加入"}</em>
            </div>
          ))}
          {addingMember ? (
            <div className="add-member-form">
              <label>成员姓名<input autoFocus value={newMemberName} onChange={(event) => setNewMemberName(event.target.value)} /></label>
              <button disabled={settingsBusy || !newMemberName.trim()} onClick={() => void addMember()}>确认添加</button>
              <button disabled={settingsBusy} onClick={() => { setAddingMember(false); setNewMemberName(""); }}>取消</button>
            </div>
          ) : <button onClick={() => setAddingMember(true)}>＋ 添加家庭成员</button>}
        </article>
        <article className="manage-card">
          <span className="sticker">PRIVACY</span>
          <h2>查看与红线通知</h2>
          <div className="permission-line">
            <span>
              <b>Sam {grantOn ? "可查看" : "不可查看"} Alex 的趋势</b>
              <small>
                {grantOn
                  ? "包含可靠识别红线的同步通知"
                  : "读取和后续通知均已停止"}
              </small>
            </span>
            <button
              onClick={() => void toggleGrant()}
              disabled={settingsBusy}
              className={`toggle ${grantOn ? "active" : ""}`}
              aria-label={`家庭查看授权已${grantOn ? "开启" : "关闭"}`}
            />
          </div>
          <p className="privacy-note">关闭后，读取权限和后续通知会立即停止。</p>
          {settingsError && (
            <p className="chat-error" role="alert">
              {settingsError}
            </p>
          )}
          <details>
            <summary>管理授权记录</summary>
            {grants.map((grant) => (
              <p key={grant.grant_id}>
                v{grant.version} · {grant.status} ·{" "}
                {new Date(grant.granted_at).toLocaleDateString("zh-CN")}
              </p>
            ))}
          </details>
        </article>
        <article className="manage-card raw-data-card">
          <span className="sticker">RAW DATA</span>
          <h2>原始数据专项授权</h2>
          <p className="privacy-note">默认仅保存在设备本地。此授权不影响基础健康功能，也不包含家庭查看权限。</p>
          {rawAuthorizations.length ? rawAuthorizations.map((item) => (
            <div className="raw-authorization-line" key={item.authorization_id}>
              <span>
                <b>{item.purpose}</b>
                <small>{item.data_types.join("、")} · 保留 {item.retention_days} 天 · 已登记 {item.upload_count} 个对象</small>
                <small>状态：{item.status === "active" ? "上传许可中" : item.status === "expired" ? "已到期" : "已撤回"} · 删除：{item.deletion_status === "pending" ? "等待删除" : item.deletion_status === "completed" ? "已完成" : "无需删除"}</small>
              </span>
              {item.status === "active" ? <button disabled={settingsBusy} onClick={() => void revokeRawAuthorization(item.authorization_id)}>撤回并停止上传</button> : null}
              {item.deletion_status === "pending" ? <button disabled={settingsBusy} onClick={() => void completeRawDeletion(item.authorization_id)}>删除云端副本</button> : null}
            </div>
          )) : <p>当前没有原始数据上传授权。</p>}
          {!rawAuthorizations.some((item) => item.status === "active") ? (
            <div className="raw-consent-form">
              <label>上传用途<input value={rawPurpose} onChange={(event) => setRawPurpose(event.target.value)} /></label>
              <label>保留期限
                <select value={rawRetentionDays} onChange={(event) => setRawRetentionDays(Number(event.target.value))}>
                  <option value={7}>7 天</option><option value={14}>14 天</option><option value={30}>30 天</option>
                </select>
              </label>
              <fieldset><legend>允许的数据类型</legend>
                {[{ id: "odor", label: "气味" }, { id: "spectral", label: "光谱" }, { id: "thermal", label: "热成像" }, { id: "presence", label: "在场状态" }].map((option) => (
                  <label key={option.id}><input type="checkbox" checked={rawTypes.includes(option.id)} onChange={(event) => setRawTypes((current) => event.target.checked ? [...current, option.id] : current.filter((item) => item !== option.id))} />{option.label}</label>
                ))}
              </fieldset>
              <label className="raw-explicit-consent"><input type="checkbox" checked={rawConsent} onChange={(event) => setRawConsent(event.target.checked)} />我已了解用途、类型和期限，并单独同意限期上传</label>
              <button disabled={settingsBusy || !device || !rawConsent || !rawTypes.length || rawPurpose.trim().length < 4} onClick={() => void createRawAuthorization()}>开启限期上传</button>
            </div>
          ) : null}
        </article>
        <article className="manage-card agent-activity-card">
          <span className="sticker">AGENT</span>
          <h2>Agent 活动</h2>
          <p className="privacy-note">
            {agentStatus?.configured
              ? `${agentStatus.model} 已连接`
              : "模型未连接"}{" "}
            ·{" "}
            {agentStatus?.proactive_enabled ? "主动调度开启" : "主动调度未运行"}
          </p>
          {agentActions.length ? (
            agentActions.slice(0, 5).map((action) => (
              <div className="agent-action-line" key={action.action_id}>
                <span>
                  <b>{agentActionLabel(action.action_type)}</b>
                  <small>
                    {new Date(action.created_at).toLocaleString("zh-CN")}
                  </small>
                </span>
                <em>{agentActionStatus(action.status)}</em>
              </div>
            ))
          ) : (
            <p>还没有 Agent 行动记录。</p>
          )}
        </article>
        {agentProfile ? (
          <article className="manage-card agent-soul-card">
            <span className="sticker">伙伴</span>
            <h2>你的健康伙伴</h2>
            <label>
              怎么称呼它
              <input value={agentProfile.display_name} onChange={(event) => setAgentProfile({ ...agentProfile, display_name: event.target.value })} />
            </label>
            <label>
              希望它怎么和你说话
              <input value={agentProfile.tone} onChange={(event) => setAgentProfile({ ...agentProfile, tone: event.target.value })} />
            </label>
            <label>
              希望它长期帮你什么
              <input value={agentProfile.relationship_goal} onChange={(event) => setAgentProfile({ ...agentProfile, relationship_goal: event.target.value })} />
            </label>
            <div className="permission-line">
              <span><b>允许主动提醒</b><small>每天最多 1 次；严重风险提醒仍会及时出现</small></span>
              <button className={`toggle ${agentProfile.proactive_enabled ? "active" : ""}`} aria-label={`主动关怀已${agentProfile.proactive_enabled ? "开启" : "关闭"}`} onClick={() => setAgentProfile({ ...agentProfile, proactive_enabled: !agentProfile.proactive_enabled })} />
            </div>
            <div className="quiet-hours">
              <label>从几点开始安静<input type="time" value={agentProfile.quiet_start} onChange={(event) => setAgentProfile({ ...agentProfile, quiet_start: event.target.value })} /></label>
              <label>几点恢复提醒<input type="time" value={agentProfile.quiet_end} onChange={(event) => setAgentProfile({ ...agentProfile, quiet_end: event.target.value })} /></label>
            </div>
            <button disabled={settingsBusy} onClick={() => void saveAgentProfile()}>保存伙伴设置</button>
            <details>
              <summary>它为什么这样回应 · 修改记录</summary>
              {agentProfile.explanation_basis.map((basis) => <p key={basis}>{basis}</p>)}
              {profileHistory.map((revision) => (
                <p key={revision.version}>
                  v{revision.version} · {revision.snapshot.display_name} · {revision.snapshot.soul.tone ?? "默认语气"} · {new Date(revision.created_at).toLocaleString("zh-CN")}
                </p>
              ))}
            </details>
          </article>
        ) : null}
      </div>
      <details className="advanced-settings">
        <summary>开发连接设置</summary>
        <div className="form-card">
          <label>
            API 地址
            <input
              value={draft.apiBase}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  apiBase: e.target.value.replace(/\/$/, ""),
                })
              }
            />
          </label>
          <label>
            家庭 ID
            <input
              value={draft.householdId}
              onChange={(e) =>
                setDraft({ ...draft, householdId: e.target.value })
              }
            />
          </label>
          <label>
            家庭访问密钥
            <input
              type="password"
              value={draft.householdKey}
              onChange={(e) =>
                setDraft({ ...draft, householdKey: e.target.value })
              }
            />
          </label>
          <button className="comic-button wide" onClick={() => onSave(draft)}>
            保存并重新连接
          </button>
        </div>
      </details>
    </section>
  );
}
