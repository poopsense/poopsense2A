# PoopSense Backend（第一阶段）

当前实现的是“可靠数据链路 → 成员认领”的可运行骨架。设备事实不会被用户纠正覆盖；成员认领以新版本追加，Outbox 与业务数据在同一数据库事务中写入。

## LLM 调度配置

Agent 医生通过 OpenAI-compatible `chat/completions` 接口调用真实模型。启动前设置：

本地开发推荐使用持久化配置。复制示例文件后，只在 `.env.local` 中填写一枚新密钥；
该文件已被 Git 忽略，FastAPI 启动时会自动读取，且不会覆盖系统已经设置的环境变量：

```powershell
Copy-Item .env.local.example .env.local
notepad .env.local
```

也可以仅为当前 PowerShell 会话设置环境变量：

```powershell
$env:POOPSENSE_LLM_API_KEY="你的密钥"
$env:POOPSENSE_LLM_BASE_URL="https://api.deepseek.com"
$env:POOPSENSE_LLM_MODEL="deepseek-v4-pro"
$env:POOPSENSE_LLM_PROACTIVE_ENABLED="true"
```

没有密钥时，认领、授权和规则安全流程仍可运行，但 Agent 对话明确返回
`MODEL_NOT_CONFIGURED`，不会用假答案冒充真实模型。规则先确定风险走廊和允许动作，
模型只能读取当前调用者已获授权成员的最小趋势/评估上下文。
主动调度只有在密钥和 `POOPSENSE_LLM_PROACTIVE_ENABLED=true` 同时存在时，才会在
成员确认后写入 outbox；模型只能从规则给出的动作白名单选择，选择结果再次校验后才形成行动。

本地开发默认随 FastAPI 启动内置 outbox worker，每秒消费一个有限批次，因此无需再手动执行
worker 命令即可完成主动闭环。`agent/status` 会返回 worker 是否运行、最后一次轮询、最近错误和
累计处理数。生产环境应设置 `POOPSENSE_INLINE_WORKER_ENABLED=false`，并将 worker 作为独立进程部署。

当前默认供应商为 DeepSeek，模型为官方 API 标识 `deepseek-v4-pro`，主动调度默认开启。
密钥也可以通过 `DEEPSEEK_API_KEY` 提供。密钥不得写进仓库、前端代码或浏览器存储。

## Agent-native 结构

- 每位成员有独立 `agent_profile`（Soul、主动开关、静默时段），家庭另有公共 `household_steward`。
- 主 Agent 按注册 Skill 委派给 `health_doctor`、`life_coach` 或 `household_steward`，接口返回实际委派角色与 Skill，前端明确展示。
- 非红线 `send_check_in` 默认每 24 小时最多一次；成员关闭主动关怀或处于静默时段时会安全降级为 `no_action`。
- 红线安全处理不受普通关怀频控影响，仍由确定性规则和发送前授权复核控制。

## 持久化 Agent Loop

每次 Agent 对话都会创建 `agent_runs`，并至少写入两个 `agent_steps`：主 Agent 的
`route_request` 与专业 Agent 的 Skill 执行。Run 保存目标、触发来源、授权依据、当前步骤、
最大 4 步、完成结果或失败原因。前端可通过
`GET /api/v1/households/{household_id}/agent/runs/{run_id}` 查看实际执行轨迹。
当前版本支持完成、失败、暂停、等待输入、恢复与用户取消终态。家庭授权、撤回、成员增删和归属纠正等高影响意图会先进入 `waiting_input`，只有原任务仍处于 paused、调用者重新通过授权检查且明确确认后才能恢复；重复恢复返回冲突，不会二次执行。

主 Agent 向专业 Agent 委派时同时写入 `agent_handoffs`，固化来源/目标 Agent、Skill 版本、
实际允许传递的上下文域、授权依据和接受状态。运行查询会返回 handoff，前端明确展示本次交接及最小上下文范围。

## 站内通知与 Soul 历史

- worker 的安全动作现在写入 `user_notifications`，支持未读、已读、已确认状态，并以 `agent_action_id` 保证一次行动只产生一条站内通知。
- 通知列表和状态变更每次都重新检查接收人及当前授权；家庭查看授权撤回后，既有相关通知也不再对查看者可见。
- `agent_profile_revisions` 保存 Soul 每一版完整快照和修改人。前端展示版本记录及“为什么这样回应”的配置依据；Soul 始终不能覆盖传感事实。
- 当前只实现站内通知；浏览器 Push、短信和邮件仍未接入。

## 结构化自报、个人基线与反馈闭环

- `GET/PUT /members/{member_id}/health-profile` 管理病史、饮食、作息、用药和目标；底层继续使用 `self_report` 版本化记忆，查看授权不等于编辑授权。
- 趋势按类别建立个人基线。每维至少需要 3 个历史可靠样本；不足时返回 `baseline_status=insufficient`，不会伪造趋势。
- `PUT /agent/messages/{message_id}/feedback` 支持有帮助/没帮助的幂等更新。反馈汇总进入下一轮 `feedback_preferences`，只允许适配表达方式，不能改变风险、权限或原始事实。
- 正式登录页面仍未开发，当前继续使用开发身份凭证。

## Skill 能力包

Skill 不再只是字符串。`app/skills.py` 为每项能力声明版本、执行 Agent、风险等级、允许角色、
上下文域、是否允许主动调用，以及输入/输出 Schema。Coordinator 在调用模型前验证角色和输入，
模型返回后验证输出；失败会进入 Run/Step 失败终态。每个 Step 保存实际 Skill 版本，能力目录可通过
`GET /api/v1/households/{household_id}/agent/skills` 查询，前端“我的”页同步展示。

## 本地运行

比赛演示建议从项目根目录启动，脚本会检查端口、数据库、Agent worker、成员数据和前端；
`-TestModel` 会额外产生一条真实 DeepSeek 测试对话：

```powershell
.\start_demo.ps1 -TestModel
```

`GET /ready` 提供不泄露密钥的就绪状态，只有数据库可访问时才返回成功，并显示模型、主动调度和 worker 是否已经就绪。

当前工作区已经准备好标准 Windows CPython 环境，可直接运行：

```powershell
cd backend
.\.venv-win\Scripts\python.exe -m pytest
.\.venv-win\Scripts\python.exe -m uvicorn app.main:app --reload
```

在另一台机器首次安装时：

```powershell
cd backend
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000/docs` 查看接口。开发环境自动创建演示绑定：

- `device_id`: `dev_001`
- `household_id`: `hh_001`
- 请求头 `X-Device-Key`: `dev-secret`
- 家庭接口请求头 `X-Household-Key`: `household-secret`
- 演示查看者请求头 `X-Household-Key`: `viewer-secret`（授权前不能读取成员趋势）

生产环境应设置：

```powershell
$env:POOPSENSE_DATABASE_URL = "postgresql+psycopg://user:password@localhost/poopsense"
$env:POOPSENSE_BOOTSTRAP_DEMO_DEVICE = "false"
$env:POOPSENSE_AUTO_CREATE_SCHEMA = "false"
python -m pip install -e ".[postgres]"
alembic upgrade head
```

## 已实现接口

- `POST /api/v1/device-sessions`：版本校验、设备绑定校验、幂等接收、五类事实链起点和 Outbox。
- `GET /api/v1/households/{household_id}/claim-inbox`：经过家庭认证的待认领箱。
- `POST /api/v1/households/{household_id}/sessions/{session_id}/claim`：认领和纠正，保留归属版本历史。
- `POST /api/v1/households/{household_id}/sessions/{session_id}/reassess`：按当前确定性策略追加评估版本。
- `GET /api/v1/households/{household_id}/members/{member_id}/trends`：只统计已认领、可靠样本，返回类别占比、频率、连续异常和有效覆盖率。
- `POST /api/v1/households/{household_id}/members/{member_id}/grants`：家庭所有者授予查看与红线同步通知权限。
- `DELETE /api/v1/households/{household_id}/grants/{grant_id}`：立即撤回读取与通知权限，并取消未发送任务。

独立 Outbox worker（生产部署或人工排障）：

```powershell
.\.venv-win\Scripts\python.exe -m app.worker --limit 100
# 人工重放死信；沿用原事件和幂等键
.\.venv-win\Scripts\python.exe -m app.worker --replay-id 123 --limit 100
```

worker 使用 `pending → processing → succeeded` 状态机。失败按指数退避进入 `retry`，达到有限次数后进入 `dead_letter`；进程崩溃遗留的 `processing` 任务会在租约过期后被回收。

红线通知任务在真正发送时再次读取最新授权。即使撤回与 worker 出队并发，过期授权也不能通过发送前检查。当前 `delivery: in_app` 会形成可读、可确认的站内通知；邮件、短信和浏览器 Push 供应商尚未连接。

## 架构影响（通俗版）

- PostgreSQL 是事实账本；SQLite 只用于零依赖本地开发和测试。
- 硬件阈值没有写死在业务结论中。可靠性阈值通过 `POOPSENSE_RELIABLE_CONFIDENCE_THRESHOLD` 配置。
- `received_at` 由服务器生成，设备时间不可信时仍能排查上报顺序。
- 重复上报不会重复建档；同一设备和会话 ID 如果内容变化，会明确返回冲突。
- 未认领数据不会自动绑定候选成员，也就不会进入个人趋势或定向通知。
- 趋势不对颜色或形状求平均，只计算类别数量/占比、频率、连续异常和有效样本覆盖率。
- 成员会话接口返回版本化 `visual_profile`。形态角色只由可靠传感事实确定：`hard→scattered`、`normal→elongated`、`loose→irregular`，并兼容硬件直接输出的 `compact/elongated/scattered/irregular`。评估不可靠或值未定义时固定返回 `uncertain`，且不泄露低置信度维度值。

## 测试

```powershell
python -m pytest
```

## 机械臂与 VBot 统一递水 Tool

当前比赛演示默认走更短、更可控的取水链路：

`偏干硬结果 → 卡通动画 → Agent 分析与补水建议 → 用户二次确认 → 待机位 → 取杯接近位 → 取杯位 → 夹紧 → 提起并保持`。

- `POST /api/v1/households/{household_id}/robot/tasks/pickup-water`：显式确认后启动原地取水；不调用 VBot、不移动、不进入递水位、不松爪。
- `GET /api/v1/households/{household_id}/robot/tasks/{task_id}`：读取阶段、进度和失败原因。
- `POST /api/v1/households/{household_id}/robot/tasks/stop`：运行中请求停止机械臂。

本地模拟一次“便便一颗颗、偏干硬”的完整软件流程：先让浏览器停留在首页，再运行：

```powershell
.\.venv-runtime\Scripts\python.exe scripts\simulate_dry_flow.py
```

脚本只上报并认领一条模拟传感结果，不会启动真实机械臂。机械臂仍须在 Agent 页面依次点击“准备取水”和“确认开始取水”。

以下完整移动递水链路保留为后续扩展，不是当前演示入口：

完整递水任务使用确定性状态机执行：

`用户确认 → 机械臂取杯/提起 → 安全运输位 → VBot 命名路线 → 到站 → 机械臂递水 → 用户接杯确认 → 松爪 → 待机位`。

- `POST /api/v1/households/{household_id}/robot/tasks/deliver-water`：显式确认后启动完整任务。
- `GET /api/v1/households/{household_id}/robot/tasks/{task_id}`：读取阶段、进度、失败原因和待用户动作。
- `POST /api/v1/households/{household_id}/robot/tasks/{task_id}/confirm-handover`：用户扶稳水杯后确认，确认前夹爪不会松开。
- `POST /api/v1/households/{household_id}/robot/tasks/stop`：同时请求停止机械臂和 VBot。

任务结果写入 `agent_actions`，可用于审计和软件端结果反馈。VBot 未配置、离线、路线失败或超时都会阻止后续递水动作。VBot HTTP/ROS 2 桥接契约和现场接入步骤见 [VBOT_BRIDGE.md](./VBOT_BRIDGE.md)。

数据库迁移验证：

```powershell
alembic upgrade head
alembic check
```

早期本地库若由 `Base.metadata.create_all()` 直接创建且没有 `alembic_version`，不要直接执行 `alembic upgrade head`，也不要删除开发数据。应先备份并做一次“现有表结构与目标迁移一致性”检查，再由维护者执行 Alembic baseline/stamp；全新数据库可直接升级至 head。

## 便便宠物 API

- `GET /api/v1/households/{household_id}/members/{member_id}/pet`：读取宠物、成长、皮肤和只读健康摘要状态。
- `POST .../pet/check-in`：每日幂等打卡，仅成员本人或家庭管理角色可执行。
- `PUT .../pet`：改名/换肤；未解锁皮肤返回 `PET_SKIN_LOCKED`。

宠物数据与健康事实分表。家庭查看者持有效成员授权时可以读取宠物，但不能打卡或编辑。

## ANP 社区 API

- `GET /api/v1/households/{household_id}/community/posts`：列出 active 动态，只返回公开字段。
- `POST .../community/posts`：发布用户手写内容，`explicit_consent` 必须为 `true`。
- `POST .../community/posts/{post_id}/withdraw`：作者或所属家庭 owner 撤回。

家庭查看授权不授予代发权。服务端不会从趋势、记忆或传感事实自动生成社区正文；发布和撤回都会记录 Agent Action 审计。

## 多专家综合分析

Agent 对话包含“综合分析 / 第二意见 / 多专家”等意图时启用 `comprehensive_review`：主 Agent → 健康医生 → 生活教练 → `safety_arbiter`。生活教练只接收趋势与自报记忆；安全仲裁为确定性代码，不调用模型。红线分诊优先于该路由。

## L1 Agent 匹配 API

- `POST /agent-connections`：通过 active 社区帖子发起邀请，要求显式同意。
- `GET /members/{member_id}/agent-connections`：读取该成员的邀请与连接。
- `POST /agent-connections/{id}/respond`：目标方接受或拒绝。
- `POST /agent-connections/{id}/end`：任一连接方断开或撤回 pending 邀请。

连接只包含 Agent 别名和状态，不承载健康记录或家庭身份。L2 推荐和 L3 自主社交未启用。

## 每周健康周报 API

- `GET /members/{member_id}/weekly-reports`：读取最近 12 份授权范围内的周报。
- `POST /members/{member_id}/weekly-reports`：生成当前自然周周报；同一成员同一周幂等。

周报先执行可靠性门控。覆盖不足或可靠记录少于 3 条时不形成趋势判断；可靠时可由配置的模型解释已冻结事实，模型不可用则回退确定性摘要。生成操作同步记录 Agent Action 与站内通知。数据库迁移头为 `f04a82b1d963`。

## 原始数据专项授权 API

- `GET/POST /households/{household_id}/raw-data-authorizations`：查询或显式创建限期授权。
- `DELETE .../raw-data-authorizations/{id}`：撤回授权并立即阻止新上传。
- `POST .../{id}/complete-deletion`：执行并记录云端对象删除完成。
- `POST /api/v1/raw-data-uploads`：设备密钥保护的对象上传登记与范围复核。

当前后端不接收或保存原始字节，只保存外部对象引用、类型、大小、SHA-256 和删除状态；接入真实对象存储时应由同一删除状态机驱动供应商删除。迁移头为 `a76c20d9e451`。
