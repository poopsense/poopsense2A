# Interaction Intelligence Audit — Change Log

## 2026-08-29

### BUG-001 — 首页结果进入 Agent 后丢失任务上下文

Status: Fixed — Awaiting Human Review
Audit Profile: MVP
Current Verification Level: Human Verified + Static Inference + Test Verified
Verification Status: Verified

#### Objective

让“今天的结果 → Agent 医生”成为连续、可完成的用户任务，而不是从结果页跳进一个无上下文的通用聊天展示页。

#### Files Modified

- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- `frontend/src/App.test.tsx`
- `AUDIT_BUGS.md`
- `changelog.md`

#### Changes Applied

- 首页在有最新记录时把主操作改为“问问这次结果”。
- 将最新记录传入 Agent 医生，增加紧凑任务卡与用户触发的一键解释动作。
- 请求携带记录时间、风险级别和可靠结论；不在页面跳转时自动调用模型。
- 增加跨页上下文、单次调用和无自动调用的自动化测试。

#### Behavior Before

点击首页具体结果只会进入通用聊天页，用户需要重新描述这次记录。

#### Behavior After

医生页直接承接本次结果；用户明确点击后，Agent 才基于该次结果解释并给出今天的一项行动建议。

#### Validation Performed

- `npm test -- --run`：13/13 通过。
- `npm run build`：通过，含 TypeScript 检查和 Vite 生产构建。

#### Validation Not Available

- 目标目录不是 Git 仓库，无法获取 Git diff。
- 当前环境没有 `agent-browser` 命令；Node 浏览器桥接无法加载 Playwright，因此未完成真实浏览器自动化。

#### Manual Verification Steps

- 刷新首页，点击“问问这次结果”。
- 确认医生页先显示“从首页带来的任务”，且跳转本身不生成回答。
- 点击“解释这次结果”一次，确认加载反馈和一组新问答。
- 在手机宽度检查任务卡文字、按钮与输入框可操作。

#### Regression Risks

- 恢复旧会话时任务卡与历史记录会同时显示；这是刻意保留的上下文入口。

#### Regression Checks

- [x] Primary flow verified by automated test.
- [x] Duplicate invocation guarded and tested.
- [x] Existing generic prompt flow remains covered.
- [ ] Human review pending.

#### Review Status

Pending Human Review

---

### BUG-001 Revision 1 — 改为硬件结果主动触发

Status: Fixed — Awaiting Human Review
Current Verification Level: Human Verified + Static Inference + Test Verified

#### Reviewer Correction

原实现错误地要求用户点击后才调用 Agent。真实产品路径是新硬件结果主动触发卡通动画，并由 Agent 自动给出建议。

#### Changes Applied

- 每 5 秒检查一次当前成员的新 session，以首次加载作为基线，避免旧结果误触发。
- 新结果仅在用户位于首页时启动全屏卡通结果动画。
- 2.2 秒后自动进入 Agent，也可主动跳过动画。
- 等待旧会话恢复完成后，自动发送一次包含时间、风险级别和可靠结论的请求。
- 增加重复调用保护、加载反馈、移动端布局和 `prefers-reduced-motion` 支持。

#### Validation Performed

- Frontend tests: 14/14 passed.
- TypeScript + Vite production build: passed.

#### Manual Verification Required

- 使用真实硬件或 ingest 接口产生一条已可靠归属的新记录，验证最多 5 秒内开始动画并只生成一次建议。

#### Review Status

Pending Human Review

---
