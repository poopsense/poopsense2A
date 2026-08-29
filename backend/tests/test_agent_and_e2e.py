from copy import deepcopy

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AgentAction, AgentConversation, AgentFeedback, AgentMessage, AgentRun, AgentStep, FamilyGrant
from app.worker import run_until_empty


DEVICE = {"X-Device-Key": "dev-secret"}
OWNER = {"X-Household-Key": "household-secret"}
VIEWER = {"X-Household-Key": "viewer-secret"}


def upload(client, base, session_id, *, color="brown"):
    payload = deepcopy(base)
    payload["session_id"] = session_id
    payload["correlation_id"] = f"cor_{session_id}"
    payload["observations"]["color"]["value"] = color
    return client.post("/api/v1/device-sessions", json=payload, headers=DEVICE)


def test_comprehensive_review_calls_two_experts_and_persists_arbiter(client, monkeypatch):
    import app.main as main_module
    from app.agent import chat

    calls = []
    def fake_agent_chat(db, auth, member_id, message, conversation_id=None):
        return chat(db, auth, member_id, message, conversation_id,
                    model_caller=lambda messages: calls.append(messages[0]["content"]) or f"专家意见{len(calls)}")
    monkeypatch.setattr(main_module, "agent_chat", fake_agent_chat)
    response = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "请让健康医生和生活教练一起做综合分析"},
        headers=OWNER,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["skill"] == "comprehensive_review"
    assert len(calls) == 2
    assert "健康医生复核" in body["message"]["content"]
    run = client.get(
        f"/api/v1/households/hh_001/agent/runs/{body['run_id']}", headers=OWNER,
    ).json()
    assert [step["agent_name"] for step in run["steps"]] == [
        "main_agent", "health_doctor", "life_coach", "safety_arbiter",
    ]
    assert run["handoffs"][-1]["context_domains"] == ["policy_decision", "expert_summaries"]


def test_agent_chat_persists_messages_authorization_and_audit(client, monkeypatch):
    import app.main as main_module
    from app.agent import chat

    def fake_agent_chat(db, auth, member_id, message, conversation_id=None):
        return chat(db, auth, member_id, message, conversation_id,
                    model_caller=lambda _: "这是经过安全规则放行后的模型解释。")

    monkeypatch.setattr(main_module, "agent_chat", fake_agent_chat)
    response = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "帮我看看最近趋势"},
        headers=OWNER,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "explain_trend"
    assert body["delegated_agent"] == "health_doctor"
    assert body["skill"] == "summarize_trend"
    assert body["run_id"].startswith("run_")
    run_response = client.get(
        f"/api/v1/households/hh_001/agent/runs/{body['run_id']}", headers=OWNER,
    )
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"
    assert [step["agent_name"] for step in run_response.json()["steps"]] == [
        "main_agent", "health_doctor",
    ]
    assert run_response.json()["steps"][1]["skill_version"] == "1.0.0"
    assert run_response.json()["handoffs"][0]["from_agent"] == "main_agent"
    assert run_response.json()["handoffs"][0]["to_agent"] == "health_doctor"
    assert "recent_assessments" in run_response.json()["handoffs"][0]["context_domains"]
    assert body["authorization_basis"] == "household_owner"
    history = client.get(
        f"/api/v1/households/hh_001/agent/conversations/{body['conversation_id']}",
        headers=OWNER,
    )
    assert [item["role"] for item in history.json()["messages"]] == ["user", "assistant"]
    conversations = client.get(
        "/api/v1/households/hh_001/agent/conversations?member_id=m_001", headers=OWNER,
    )
    assert conversations.json()[0]["conversation_id"] == body["conversation_id"]
    actions = client.get("/api/v1/households/hh_001/agent/actions", headers=OWNER)
    assert actions.json()[0]["action_type"] == "agent_chat_response"
    with SessionLocal() as db:
        assert db.scalar(select(AgentConversation)) is not None
        assert len(db.scalars(select(AgentMessage)).all()) == 2
        assert db.scalar(select(AgentRun)).max_steps == 4
        assert len(db.scalars(select(AgentStep)).all()) == 2
        audit = db.scalar(select(AgentAction).where(AgentAction.action_type == "agent_chat_response"))
        assert audit.status == "succeeded"
        assert audit.input_summary["allowed_actions"] == ["read_authorized_trend", "explain"]


def test_agent_feedback_is_upserted_and_used_as_next_turn_preference(client, monkeypatch):
    import app.main as main_module
    from app.agent import chat

    captured: list[str] = []
    def fake_agent_chat(db, auth, member_id, message, conversation_id=None):
        return chat(db, auth, member_id, message, conversation_id,
                    model_caller=lambda messages: captured.append(messages[0]["content"]) or "安全解释")
    monkeypatch.setattr(main_module, "agent_chat", fake_agent_chat)
    first = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "帮我看看最近趋势"}, headers=OWNER,
    ).json()
    message_id = first["message"]["message_id"]
    url = f"/api/v1/households/hh_001/agent/messages/{message_id}/feedback"
    assert client.put(url, json={"rating": "not_helpful", "reason": "解释太长"}, headers=OWNER).status_code == 200
    changed = client.put(url, json={"rating": "helpful", "reason": "现在更简洁"}, headers=OWNER)
    assert changed.json()["rating"] == "helpful"
    client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "再解释一次"}, headers=OWNER,
    )
    assert '"helpful_count": 1' in captured[-1]
    assert "现在更简洁" in captured[-1]
    with SessionLocal() as db:
        assert len(db.scalars(select(AgentFeedback)).all()) == 1


def test_complete_claim_correction_revoke_and_redline_flow(client, normal_payload):
    grant = client.post(
        "/api/v1/households/hh_001/members/m_001/grants",
        json={"viewer_user_id": "u_viewer", "can_view": True, "redline_notifications": True},
        headers=OWNER,
    ).json()
    assert upload(client, normal_payload, "e2e_redline", color="red").status_code == 202
    inbox = client.get("/api/v1/households/hh_001/claim-inbox", headers=OWNER).json()
    assert inbox[0]["session_id"] == "e2e_redline"
    assert client.post(
        "/api/v1/households/hh_001/sessions/e2e_redline/claim",
        json={"member_id": "m_001", "claim_method": "user_claim"}, headers=OWNER,
    ).status_code == 200
    corrected = client.post(
        "/api/v1/households/hh_001/sessions/e2e_redline/claim",
        json={"member_id": "m_002", "claim_method": "correction"}, headers=OWNER,
    )
    assert corrected.json()["version"] == 3
    revoked = client.delete(
        f"/api/v1/households/hh_001/grants/{grant['grant_id']}", headers=OWNER,
    )
    assert revoked.status_code == 200
    assert client.get(
        "/api/v1/households/hh_001/members/m_001/trends", headers=VIEWER,
    ).status_code == 403
    with SessionLocal() as db:
        run_until_empty(db)
        old_actions = db.scalars(select(AgentAction).where(
            AgentAction.action_type == "redline_notification"
        )).all()
        assert all(item.status.startswith("cancelled_by_") for item in old_actions)
        active_grant = db.get(FamilyGrant, grant["grant_id"])
        assert active_grant.status == "revoked"


def test_device_and_grant_settings_endpoints(client):
    devices = client.get("/api/v1/households/hh_001/devices", headers=OWNER)
    assert devices.status_code == 200
    assert devices.json()[0]["device_id"] == "dev_001"
    created = client.post(
        "/api/v1/households/hh_001/members/m_001/grants",
        json={"viewer_user_id": "u_viewer"}, headers=OWNER,
    )
    history = client.get(
        "/api/v1/households/hh_001/members/m_001/grants", headers=OWNER,
    )
    assert history.status_code == 200
    assert history.json()[0]["grant_id"] == created.json()["grant_id"]
    status = client.get("/api/v1/households/hh_001/agent/status", headers=OWNER)
    assert status.status_code == 200
    assert status.json()["model"] == "deepseek-v4-pro"
    assert "household_steward" in status.json()["agents"]
    assert "manage_household" in status.json()["skills"]


def test_member_soul_is_independent_and_controls_proactive_contact(client):
    alex = client.get(
        "/api/v1/households/hh_001/agent/profiles/m_001", headers=OWNER,
    )
    steward = client.get(
        "/api/v1/households/hh_001/agent/profiles/household", headers=OWNER,
    )
    assert alex.json()["scope"] == "member"
    assert steward.json()["scope"] == "household"
    updated = client.put(
        "/api/v1/households/hh_001/agent/profiles/m_001",
        json={
            "display_name": "小噗", "tone": "温柔但直接",
            "relationship_goal": "陪 Alex 理解长期节奏",
            "proactive_enabled": False, "quiet_start": "21:30",
            "quiet_end": "08:30", "timezone": "Asia/Shanghai",
        }, headers=OWNER,
    )
    assert updated.status_code == 200
    assert len(updated.json()["explanation_basis"]) == 3
    history = client.get(
        "/api/v1/households/hh_001/agent/profiles/m_001/history", headers=OWNER,
    )
    assert history.status_code == 200
    assert [item["version"] for item in history.json()] == [2, 1]
    assert history.json()[0]["snapshot"]["display_name"] == "小噗"
    assert history.json()[1]["snapshot"]["display_name"] == "PoopSense"
    assert updated.json()["display_name"] == "小噗"
    assert updated.json()["proactive_enabled"] is False
    assert updated.json()["daily_non_redline_limit"] == 1


def test_coordinator_delegates_with_partitioned_context(client, monkeypatch):
    import app.main as main_module
    from app.agent import chat

    captured = {}

    def fake_agent_chat(db, auth, member_id, message, conversation_id=None):
        def caller(messages):
            captured["system"] = messages[0]["content"]
            return "我会协助处理家庭空间事务。"
        return chat(db, auth, member_id, message, conversation_id, model_caller=caller)

    monkeypatch.setattr(main_module, "agent_chat", fake_agent_chat)
    response = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "帮我看看家庭成员授权"}, headers=OWNER,
    )
    assert response.json()["delegated_agent"] == "household_steward"
    assert response.json()["skill"] == "manage_household"
    assert "household_scope" in captured["system"]
    assert "visible_memory" not in captured["system"]
    assert '"trend"' not in captured["system"]


def test_skill_catalog_and_role_permission_are_enforced(client):
    catalog = client.get(
        "/api/v1/households/hh_001/agent/skills", headers=OWNER,
    )
    assert catalog.status_code == 200
    household_skill = next(item for item in catalog.json() if item["name"] == "manage_household")
    assert household_skill["version"] == "1.0.0"
    assert household_skill["allowed_roles"] == ["owner", "caregiver"]
    assert household_skill["confirmation_required"] is True

    client.post(
        "/api/v1/households/hh_001/members/m_001/grants",
        json={"viewer_user_id": "u_viewer"}, headers=OWNER,
    )
    denied = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "帮我管理家庭授权"}, headers=VIEWER,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "SKILL_PERMISSION_DENIED"


def test_household_skill_pauses_resumes_and_rejects_duplicate_resume(client, monkeypatch):
    import app.main as main_module
    from app.agent import resume_paused_chat

    paused = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "帮我授权家庭成员查看"}, headers=OWNER,
    )
    assert paused.status_code == 200
    assert paused.json()["model_version"] == "policy-engine"
    run_id = paused.json()["run_id"]
    trace = client.get(
        f"/api/v1/households/hh_001/agent/runs/{run_id}", headers=OWNER,
    ).json()
    assert trace["status"] == "paused"
    assert trace["steps"][-1]["status"] == "waiting_input"

    def fake_resume(db, auth, target_run_id, confirmed):
        return resume_paused_chat(
            db, auth, target_run_id, confirmed,
            model_caller=lambda _: "确认已收到。请选择目标成员和授权范围。",
        )

    monkeypatch.setattr(main_module, "resume_paused_chat", fake_resume)
    resumed = client.post(
        f"/api/v1/households/hh_001/agent/runs/{run_id}/resume",
        json={"confirmed": True}, headers=OWNER,
    )
    assert resumed.status_code == 200
    assert resumed.json()["run"]["status"] == "completed"
    assert resumed.json()["run"]["steps"][-1]["status"] == "succeeded"
    duplicate = client.post(
        f"/api/v1/households/hh_001/agent/runs/{run_id}/resume",
        json={"confirmed": True}, headers=OWNER,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "RUN_NOT_WAITING_INPUT"

    cancelled = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "撤回授权"}, headers=OWNER,
    ).json()
    cancelled_result = client.post(
        f"/api/v1/households/hh_001/agent/runs/{cancelled['run_id']}/resume",
        json={"confirmed": False}, headers=OWNER,
    )
    assert cancelled_result.json()["run"]["status"] == "cancelled"


def test_llm_orchestrator_cannot_escape_rule_action_whitelist(client, normal_payload):
    from app.agent import orchestrate_session
    from app.models import SessionRecord

    upload(client, normal_payload, "e2e_orchestrate")
    client.post(
        "/api/v1/households/hh_001/sessions/e2e_orchestrate/claim",
        json={"member_id": "m_001"}, headers=OWNER,
    )
    with SessionLocal() as db:
        record = db.scalar(select(SessionRecord).where(
            SessionRecord.external_session_id == "e2e_orchestrate"
        ))
        action = orchestrate_session(
            db, record.id,
            model_caller=lambda _: '{"action":"send_check_in","reason":"近期可温和关心","message":"今天感觉怎么样？"}',
        )
        assert action.status in {"pending", "succeeded"}
        assert action.recipient_id == "u_owner"
        try:
            orchestrate_session(
                db, record.id,
                model_caller=lambda _: '{"action":"share_publicly","reason":"x","message":"x"}',
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 502
        else:
            raise AssertionError("out-of-policy model action must be rejected")

    upload(client, normal_payload, "e2e_orchestrate_second")
    client.post(
        "/api/v1/households/hh_001/sessions/e2e_orchestrate_second/claim",
        json={"member_id": "m_001"}, headers=OWNER,
    )
    with SessionLocal() as db:
        second = db.scalar(select(SessionRecord).where(
            SessionRecord.external_session_id == "e2e_orchestrate_second"
        ))
        limited = orchestrate_session(
            db, second.id,
            model_caller=lambda _: '{"action":"send_check_in","reason":"再次关心","message":"还好吗？"}',
        )
        assert limited.action_type == "llm_no_action"
        assert limited.result["reason"] in {
            "daily_proactive_limit_reached", "member_quiet_hours",
        }
