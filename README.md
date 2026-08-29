# PoopSense (便知) — See. Smell. Sense.

**A no-camera, toilet-mounted ambient health agent that reads your body's signals without you lifting a finger.**

> 不用拍照，也能读懂每一次身体信号。装在家庭马桶上的环境健康智能体：被动感知、主动关心每个家庭成员。

PoopSense is an **Agentic Device** — not another health app you have to open. It sits on the toilet, passively senses, and *comes to you*: *"Sam had 3 loose stools this week and is drinking less water — want to take a look?"*

The distinction between "you go find it" and "it comes find you" is the core of the project and of its "agent-native" design.

---

## What this repository contains

| Path | What it is |
| --- | --- |
| [`backend/`](backend/) | FastAPI + SQLAlchemy + Alembic backend: the reliable data pipeline, family authorization model, deterministic rule engine, and the agent loop. |
| [`frontend/`](frontend/) | React + TypeScript + Vite PWA: the user-facing web app. |
| [`docs/`](docs/) | Chinese technical documentation — project overview, software architecture, PRD, and hardware data contract. |
| [`start_demo.ps1`](start_demo.ps1) / [`check_demo.ps1`](check_demo.ps1) | One-click demo launcher and read-only smoke test (Windows PowerShell). |

> The hardware firmware/SDK for the Panthera robot arm is a **third-party** project by [HighTorque-Robotics](https://github.com/HighTorque-Robotics) and is intentionally not vendored here.

---

## Architecture in one paragraph

Four sensors on the device (**pressure + APDS9960** for member presence, **MLX90640** thermal for shape, **AS7341** spectral for color, **BME688** gas for odor — **no visible-light camera**) produce raw observations. The backend turns them into *reliable, versioned facts*. A **deterministic safety layer** decides risk, permissions, recipients, frequency, and which actions are allowed; an **LLM (DeepSeek)** is only allowed to read the caller's minimal authorized context and organize language *inside* that boundary — never to decide risk or permissions on its own. Raw sensor data stays on-device by default and is uploaded only under a scoped, revocable, expiring authorization.

Key design principles, all enforced in code:

- **Sensing facts are immutable** — user corrections and self-reports append new versions; they never overwrite observations.
- **Reliability gating** — missing or low-confidence input returns *"cannot reliably judge this time"* instead of a weak conclusion.
- **Family sharing is per-member, per-authorization** — a viewer's access is checked on every read and revoked immediately on withdrawal.
- **Auditable agent loop** — every conversation writes `agent_runs` / `agent_steps` / `agent_actions`, with policy and model versions pinned.

The full rationale is in [`docs/总纲.md`](docs/总纲.md) and [`docs/软件端技术梳理（前端·后端·Agent·数据）.md`](docs/软件端技术梳理（前端·后端·Agent·数据）.md).

---

## Quick start

### Backend (FastAPI)

```bash
cd backend
# uses uv (see pyproject.toml); a venv works too
uv sync
cp .env.local.example .env.local   # then fill in a real DeepSeek key
uv run uvicorn app.main:app --reload --port 8000
```

No key is required to exercise claiming, authorization, and the rule-safety flows; Agent chat returns `MODEL_NOT_CONFIGURED` instead of faking answers.

### Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

### One-click demo (Windows)

```powershell
.\start_demo.ps1 -TestModel     # starts healthy services, runs a full smoke test
.\check_demo.ps1                # read-only health check (no model call)
```

See [`docs/演示运行说明.md`](docs/演示运行说明.md) for the full walkthrough.

---

## Tests

Backend (`pytest`, in `backend/tests/`) and frontend (`vitest`, `src/App.test.tsx`) both ship end-to-end coverage for the closed loop: upload → pending-claim → claim → correct → revoke authorization → a red-line action must not be sent after revocation.

```bash
cd backend && uv run pytest
cd frontend && npm test
```

---

## License

[MIT](LICENSE). The project's own code is licensed under MIT; the Panthera robot SDK it optionally talks to is a separate third-party project with its own license.

---

## 中文说明

**PoopSense（便知）** —— 装在家庭马桶上、不用摄像头（无可见光）就能被动读懂身体信号的环境健康智能体。核心闭环：传感器可靠数据 → 家庭待认领 → 成员认领 → 规则建议与趋势 → 主动通知与家庭授权 → 可见可改记忆。软件由 FastAPI 后端 + React PWA 前端组成，Agent 的"主动性"来自确定性规则引擎的护栏 + LLM 只负责在放行范围内组织语言。

项目文档见 [`docs/总纲.md`](docs/总纲.md)（先看这一页）。**注意：仓库内不含任何密钥，`backend/.env.local` 已通过 `.gitignore` 排除，请自行复制 `.env.local.example` 填入你自己的密钥。**
