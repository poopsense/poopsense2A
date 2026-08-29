import json
import time

import httpx
import pytest

from app.robot import (
    POSE_ORDER, RobotTaskError, RobotTaskService, UnavailableVBotNavigator,
)


OWNER = {"X-Household-Key": "household-secret"}


class FakeNavigator:
    def __init__(self, final_status="completed"):
        self.final_status = final_status
        self.started_routes = []
        self.stopped_tasks = []

    def health(self):
        return {"configured": True, "connected": True, "status": "ok"}

    def start_route(self, route_name):
        self.started_routes.append(route_name)
        return "vbot_task_001"

    def route_status(self, task_id):
        assert task_id == "vbot_task_001"
        return {"task_id": task_id, "status": self.final_status}

    def stop(self, task_id):
        self.stopped_tasks.append(task_id)


def write_plan(path):
    poses = {
        pose: {
            "positions": [float(index)] * 6,
            "gripper": 1.0 if pose == "pickup" else 0.0,
            "duration": 6.0,
            "tag": pose,
        }
        for index, pose in enumerate(POSE_ORDER)
    }
    poses["transport_safe"] = {
        "positions": [0.25] * 6,
        "gripper": 1.0,
        "duration": 6.0,
        "tag": "transport_safe",
    }
    path.write_text(json.dumps({
        "name": "deliver_water",
        "enabled": True,
        "poses": poses,
    }), encoding="utf-8")


def wait_for_status(service, expected, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.runtime_status()["status"]
        if status == expected:
            return service.runtime_status()
        time.sleep(0.01)
    raise AssertionError(f"task did not reach {expected}: {service.runtime_status()}")


def test_hydration_chat_offers_delivery_but_other_chat_does_not(client, monkeypatch):
    import app.main as main_module
    from app.agent import chat

    def fake_agent_chat(db, auth, member_id, message, conversation_id=None):
        return chat(
            db,
            auth,
            member_id,
            message,
            conversation_id,
            model_caller=lambda _: "建议适量补充水分。",
        )

    monkeypatch.setattr(main_module, "agent_chat", fake_agent_chat)
    hydration = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "提醒我多喝水"},
        headers=OWNER,
    )
    assert hydration.status_code == 200
    assert "offer_water_pickup" in hydration.json()["allowed_actions"]

    general = client.post(
        "/api/v1/households/hh_001/agent/chat",
        json={"member_id": "m_001", "message": "今天感觉怎么样"},
        headers=OWNER,
    )
    assert "offer_water_pickup" not in general.json()["allowed_actions"]


def test_delivery_requires_explicit_confirmation(client):
    response = client.post(
        "/api/v1/households/hh_001/robot/tasks/deliver-water",
        json={"member_id": "m_001", "confirmed": False},
        headers=OWNER,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "USER_CONFIRMATION_REQUIRED"


def test_pickup_requires_explicit_confirmation(client):
    response = client.post(
        "/api/v1/households/hh_001/robot/tasks/pickup-water",
        json={"member_id": "m_001", "confirmed": False},
        headers=OWNER,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "USER_CONFIRMATION_REQUIRED"


def test_delivery_rejects_unconfigured_trajectory(client, tmp_path, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "robot_service",
        RobotTaskService("http://robot.test", tmp_path / "unconfigured.json"),
    )
    response = client.post(
        "/api/v1/households/hh_001/robot/tasks/deliver-water",
        json={"member_id": "m_001", "confirmed": True},
        headers=OWNER,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRAJECTORY_NOT_CALIBRATED"


def test_capture_persists_all_six_poses_and_enables_plan(tmp_path, monkeypatch):
    path = tmp_path / "deliver_water.json"
    service = RobotTaskService("http://robot.test", path)

    def fake_request(_client, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            request=request,
            json={
                "connected": True,
                "demo_mode": False,
                "positions": [0.1, 0.2, 0.3, 0.0, -0.1, 0.05],
                "gripper_position": 0.2,
            },
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    for pose in POSE_ORDER:
        service.capture_pose(pose, 6.0)
    status = service.plan_status()
    assert status["enabled"] is True
    assert status["missing_poses"] == []
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert list(saved["poses"]) == list(POSE_ORDER)


def test_capture_rejects_demo_controller(tmp_path, monkeypatch):
    service = RobotTaskService("http://robot.test", tmp_path / "plan.json")

    def fake_request(_client, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            request=request,
            json={"connected": True, "demo_mode": True, "positions": [0.0] * 6},
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    with pytest.raises(RobotTaskError) as caught:
        service.capture_pose("standby", 6.0)
    assert caught.value.code == "ROBOT_NOT_LIVE"


def test_integrated_delivery_waits_for_vbot_then_user_before_release(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    write_plan(path)
    navigator = FakeNavigator()
    service = RobotTaskService(
        "http://robot.test", path, navigator=navigator, handover_timeout_seconds=2.0,
    )
    calls = []
    monkeypatch.setattr(service, "controller_status", lambda: {
        "connected": True, "live": True, "positions": [0.0] * 6,
        "gripper_position": 0.0, "trajectory_running": False,
    })
    monkeypatch.setattr(service, "_move_and_wait", lambda pose: calls.append(("move", pose["tag"])))
    monkeypatch.setattr(service, "_set_gripper", lambda value: calls.append(("gripper", value)))

    started = service.start_delivery("m_001", "water_route")
    waiting = wait_for_status(service, "waiting_user")
    assert waiting["requires_user_action"] == "confirm_handover_ready"
    assert navigator.started_routes == ["water_route"]
    assert calls == [
        ("move", "standby"),
        ("move", "pickup_approach"),
        ("move", "pickup"),
        ("gripper", 1.0),
        ("move", "lift"),
        ("move", "transport_safe"),
        ("move", "handover_approach"),
        ("move", "handover"),
    ]

    service.confirm_handover(started["task_id"], True)
    completed = wait_for_status(service, "completed")
    assert completed["progress"] == 1.0
    assert calls[-1] == ("move", "standby")
    assert ("gripper", 0.0) in calls


def test_pickup_runs_stationary_arm_only_and_holds_cup(tmp_path, monkeypatch):
    path = tmp_path / "pickup_plan.json"
    pickup_poses = {
        pose: {
            "positions": [float(index)] * 6,
            "gripper": 1.0 if pose == "pickup" else 0.0,
            "duration": 6.0,
            "tag": pose,
        }
        for index, pose in enumerate(("standby", "pickup_approach", "pickup", "lift"))
    }
    path.write_text(json.dumps({
        "name": "pickup_water",
        "enabled": False,
        "poses": pickup_poses,
    }), encoding="utf-8")
    service = RobotTaskService(
        "http://robot.test", path, navigator=UnavailableVBotNavigator(),
    )
    calls = []
    monkeypatch.setattr(service, "controller_status", lambda: {
        "connected": True, "live": True, "positions": [0.0] * 6,
        "gripper_position": 0.0, "trajectory_running": False,
    })
    monkeypatch.setattr(service, "_move_and_wait", lambda pose: calls.append(("move", pose["tag"])))
    monkeypatch.setattr(service, "_set_gripper", lambda value: calls.append(("gripper", value)))

    started = service.start_pickup("m_001")
    completed = wait_for_status(service, "completed")

    assert started["task"] == "pickup_water"
    assert completed["current_step"] == "pickup_completed"
    assert completed["requires_user_action"] is None
    assert calls == [
        ("move", "standby"),
        ("move", "pickup_approach"),
        ("move", "pickup"),
        ("gripper", 1.0),
        ("move", "lift"),
    ]


def test_vbot_route_failure_prevents_handover_motion(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    write_plan(path)
    service = RobotTaskService(
        "http://robot.test", path, navigator=FakeNavigator("failed")
    )
    calls = []
    monkeypatch.setattr(service, "controller_status", lambda: {
        "connected": True, "live": True, "positions": [0.0] * 6,
        "gripper_position": 0.0, "trajectory_running": False,
    })
    monkeypatch.setattr(service, "_move_and_wait", lambda pose: calls.append(pose["tag"]))
    monkeypatch.setattr(service, "_set_gripper", lambda value: None)

    service.start_delivery("m_001")
    failed = wait_for_status(service, "failed")
    assert failed["error"] == "VBOT_ROUTE_FAILED"
    assert "handover_approach" not in calls
    assert "handover" not in calls


def test_integrated_delivery_fails_closed_before_arm_moves_without_vbot(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    write_plan(path)
    service = RobotTaskService(
        "http://robot.test", path, navigator=UnavailableVBotNavigator()
    )
    arm_checked = False

    def controller_status():
        nonlocal arm_checked
        arm_checked = True
        return {"connected": True, "live": True, "positions": [0.0] * 6}

    monkeypatch.setattr(service, "controller_status", controller_status)
    with pytest.raises(RobotTaskError) as caught:
        service.start_delivery("m_001")
    assert caught.value.code == "VBOT_NOT_READY"
    assert arm_checked is False


def test_integrated_delivery_requires_dedicated_transport_safe_pose(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({
        "name": "deliver_water",
        "enabled": True,
        "poses": {
            pose: {"positions": [0.0] * 6, "gripper": 0.0, "duration": 6.0}
            for pose in POSE_ORDER
        },
    }), encoding="utf-8")
    service = RobotTaskService("http://robot.test", path, navigator=FakeNavigator())
    arm_checked = False

    def controller_status():
        nonlocal arm_checked
        arm_checked = True
        return {"connected": True, "live": True, "positions": [0.0] * 6}

    monkeypatch.setattr(service, "controller_status", controller_status)
    with pytest.raises(RobotTaskError) as caught:
        service.start_delivery("m_001")
    assert caught.value.code == "TRANSPORT_SAFE_POSE_NOT_CALIBRATED"
    assert arm_checked is False


def test_integrated_delivery_api_persists_result_feedback(client, tmp_path, monkeypatch):
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import AgentAction
    from sqlalchemy import select

    path = tmp_path / "plan.json"
    write_plan(path)
    service = RobotTaskService(
        "http://robot.test", path, navigator=FakeNavigator(), handover_timeout_seconds=2.0,
    )
    monkeypatch.setattr(service, "controller_status", lambda: {
        "connected": True, "live": True, "positions": [0.0] * 6,
        "gripper_position": 0.0, "trajectory_running": False,
    })
    monkeypatch.setattr(service, "_move_and_wait", lambda pose: None)
    monkeypatch.setattr(service, "_set_gripper", lambda value: None)
    service.set_event_sink(main_module.persist_robot_runtime)
    monkeypatch.setattr(main_module, "robot_service", service)

    response = client.post(
        "/api/v1/households/hh_001/robot/tasks/deliver-water",
        json={"member_id": "m_001", "confirmed": True, "route_name": "water_route"},
        headers=OWNER,
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    wait_for_status(service, "waiting_user")
    confirmation = client.post(
        f"/api/v1/households/hh_001/robot/tasks/{task_id}/confirm-handover",
        json={"confirmed": True},
        headers=OWNER,
    )
    assert confirmation.status_code == 200
    wait_for_status(service, "completed")
    status = client.get(
        f"/api/v1/households/hh_001/robot/tasks/{task_id}", headers=OWNER
    )
    assert status.status_code == 200
    assert status.json()["status"] == "completed"

    with SessionLocal() as db:
        action = db.scalar(select(AgentAction).where(
            AgentAction.idempotency_key == f"robot-delivery:{task_id}"
        ))
        assert action is not None
        assert action.status == "succeeded"
        assert action.result["current_step"] == "completed"


def test_pickup_api_persists_audited_stationary_result(client, tmp_path, monkeypatch):
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import AgentAction
    from sqlalchemy import select

    path = tmp_path / "pickup_plan.json"
    pickup_poses = {
        pose: {
            "positions": [float(index)] * 6,
            "gripper": 1.0 if pose == "pickup" else 0.0,
            "duration": 6.0,
            "tag": pose,
        }
        for index, pose in enumerate(("standby", "pickup_approach", "pickup", "lift"))
    }
    path.write_text(json.dumps({
        "name": "pickup_water",
        "enabled": False,
        "poses": pickup_poses,
    }), encoding="utf-8")
    service = RobotTaskService(
        "http://robot.test", path, navigator=UnavailableVBotNavigator(),
    )
    monkeypatch.setattr(service, "controller_status", lambda: {
        "connected": True, "live": True, "positions": [0.0] * 6,
        "gripper_position": 0.0, "trajectory_running": False,
    })
    monkeypatch.setattr(service, "_move_and_wait", lambda pose: None)
    monkeypatch.setattr(service, "_set_gripper", lambda value: None)
    service.set_event_sink(main_module.persist_robot_runtime)
    monkeypatch.setattr(main_module, "robot_service", service)

    response = client.post(
        "/api/v1/households/hh_001/robot/tasks/pickup-water",
        json={"member_id": "m_001", "confirmed": True},
        headers=OWNER,
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    wait_for_status(service, "completed")

    with SessionLocal() as db:
        action = db.scalar(select(AgentAction).where(
            AgentAction.idempotency_key == f"robot-pickup:{task_id}"
        ))
        assert action is not None
        assert action.action_type == "robot_pickup_water"
        assert action.authorization_basis.startswith("explicit_user_confirmation:")
        assert action.status == "succeeded"
        assert action.result["current_step"] == "pickup_completed"
