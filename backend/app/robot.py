from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx


POSE_ORDER = (
    "standby",
    "pickup_approach",
    "pickup",
    "lift",
    "handover_approach",
    "handover",
)
CAPTURE_POSES = POSE_ORDER + ("transport_safe",)
ACTIVE_TASK_STATUSES = {"starting", "running", "waiting_user", "stopping"}


class RobotTaskError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class VBotNavigator(Protocol):
    def health(self) -> dict[str, Any]: ...

    def start_route(self, route_name: str) -> str: ...

    def route_status(self, task_id: str) -> dict[str, Any]: ...

    def stop(self, task_id: str | None) -> None: ...


class UnavailableVBotNavigator:
    """Fail closed until the VBot bridge is explicitly configured."""

    def health(self) -> dict[str, Any]:
        return {"configured": False, "connected": False, "status": "not_configured"}

    def start_route(self, route_name: str) -> str:
        del route_name
        raise RobotTaskError("VBOT_NOT_CONFIGURED", "VBot 路线接口尚未配置")

    def route_status(self, task_id: str) -> dict[str, Any]:
        del task_id
        raise RobotTaskError("VBOT_NOT_CONFIGURED", "VBot 路线接口尚未配置")

    def stop(self, task_id: str | None) -> None:
        del task_id


class VBotHttpNavigator:
    """HTTP adapter for a small bridge running beside the VBot ROS 2 graph.

    The bridge exposes named routes only. PoopSense never sends arbitrary body
    velocity commands, so an Agent cannot invent unvalidated motion.
    """

    def __init__(self, base_url: str, timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            with httpx.Client(trust_env=False, timeout=self.timeout_seconds) as client:
                response = client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("VBot bridge returned a non-object response")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            raise RobotTaskError("VBOT_UNAVAILABLE", "VBot 路线服务不可用") from exc

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/health")
        connected = bool(payload.get("connected", payload.get("status") == "ok"))
        return {
            "configured": True,
            "connected": connected,
            "status": payload.get("status", "unknown"),
            "details": payload,
        }

    def start_route(self, route_name: str) -> str:
        payload = self._request(
            "POST",
            f"/api/routes/{route_name}/start",
            json={"source": "poopsense", "require_arrival_feedback": True},
        )
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RobotTaskError("VBOT_INVALID_RESPONSE", "VBot 未返回路线任务编号")
        return task_id

    def route_status(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/tasks/{task_id}")

    def stop(self, task_id: str | None) -> None:
        if task_id:
            self._request("POST", f"/api/tasks/{task_id}/stop", json={})


@dataclass
class RobotRuntime:
    task_id: str | None = None
    member_id: str | None = None
    route_name: str | None = None
    route_task_id: str | None = None
    status: str = "idle"
    progress: float = 0.0
    current_step: str | None = None
    error: str | None = None
    message: str | None = None
    requires_user_action: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)


class RobotTaskService:
    """Safety boundary and deterministic workflow for water delivery."""

    def __init__(
        self,
        base_url: str,
        trajectory_path: Path,
        timeout_seconds: float = 5.0,
        *,
        navigator: VBotNavigator | None = None,
        route_name: str = "poopsense_water_delivery",
        route_timeout_seconds: float = 180.0,
        handover_timeout_seconds: float = 60.0,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.trajectory_path = trajectory_path
        self.timeout_seconds = timeout_seconds
        self.navigator = navigator or UnavailableVBotNavigator()
        self.route_name = route_name
        self.route_timeout_seconds = route_timeout_seconds
        self.handover_timeout_seconds = handover_timeout_seconds
        self.runtime = RobotRuntime()
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._handover_event = threading.Event()
        self._event_sink = event_sink

    def set_event_sink(self, event_sink: Callable[[dict[str, Any]], None]) -> None:
        self._event_sink = event_sink

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _notify(self) -> None:
        if self._event_sink:
            try:
                self._event_sink(self.runtime_status())
            except Exception:
                # Audit persistence must not change a physical safety decision.
                pass

    def _set_stage(
        self,
        step: str,
        progress: float,
        message: str,
        *,
        status: str = "running",
        requires_user_action: str | None = None,
    ) -> None:
        with self._state_lock:
            self.runtime.status = status
            self.runtime.current_step = step
            self.runtime.progress = min(max(progress, 0.0), 1.0)
            self.runtime.message = message
            self.runtime.requires_user_action = requires_user_action
            self.runtime.history.append(
                {"step": step, "status": status, "message": message, "at": self._now()}
            )
        self._notify()

    def _raise_if_stopped(self) -> None:
        if self._stop_event.is_set():
            raise RobotTaskError("TASK_STOPPED", "递水任务已停止")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            with httpx.Client(trust_env=False, timeout=self.timeout_seconds) as client:
                response = client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RobotTaskError("ROBOT_UNAVAILABLE", "机械臂上位机不可用") from exc

    def controller_status(self) -> dict[str, Any]:
        state = self._request("GET", "/api/status")
        return {
            "connected": bool(state.get("connected")),
            "live": not bool(state.get("demo_mode", True)),
            "positions": list(state.get("positions") or []),
            "gripper_position": state.get("gripper_position"),
            "trajectory_running": bool(state.get("trajectory_running", False)),
        }

    def navigator_status(self) -> dict[str, Any]:
        try:
            return self.navigator.health()
        except RobotTaskError as exc:
            return {
                "configured": True,
                "connected": False,
                "status": "unavailable",
                "error": exc.code,
            }

    def load_plan(self) -> dict[str, Any]:
        if not self.trajectory_path.exists():
            return {"name": "deliver_water", "enabled": False, "poses": {}}
        return json.loads(self.trajectory_path.read_text(encoding="utf-8"))

    def save_plan(self, plan: dict[str, Any]) -> None:
        self.trajectory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.trajectory_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temp_path.replace(self.trajectory_path)

    def plan_status(self) -> dict[str, Any]:
        plan = self.load_plan()
        poses = plan.get("poses", {})
        missing = [name for name in POSE_ORDER if name not in poses]
        return {
            "name": "deliver_water",
            "enabled": bool(plan.get("enabled")) and not missing,
            "calibrated_poses": [name for name in CAPTURE_POSES if name in poses],
            "missing_poses": missing,
            "transport_safe_ready": "transport_safe" in poses,
        }

    def capture_pose(self, pose_name: str, duration: float) -> dict[str, Any]:
        if pose_name not in CAPTURE_POSES:
            raise RobotTaskError("INVALID_POSE", "未知的递水关键姿态")
        if duration < 3.0 or duration > 30.0:
            raise RobotTaskError("INVALID_DURATION", "单段时间必须在3到30秒之间")
        state = self.controller_status()
        if not state["connected"] or not state["live"]:
            raise RobotTaskError("ROBOT_NOT_LIVE", "机械臂未处于真实连接模式")
        if len(state["positions"]) != 6:
            raise RobotTaskError("INVALID_ROBOT_STATE", "未读取到6个机械臂关节位置")
        plan = self.load_plan()
        poses = plan.setdefault("poses", {})
        poses[pose_name] = {
            "positions": state["positions"],
            "gripper": state["gripper_position"],
            "duration": duration,
        }
        plan["name"] = "deliver_water"
        plan["enabled"] = all(name in poses for name in POSE_ORDER)
        self.save_plan(plan)
        return self.plan_status()

    def _move_and_wait(self, pose: dict[str, Any], velocity: float = 0.03) -> None:
        self._raise_if_stopped()
        target = list(pose["positions"])
        duration = float(pose.get("duration", 6.0))
        before = self.controller_status()
        current_before = list(before.get("positions") or [])
        max_delta = (
            max(abs(a - b) for a, b in zip(current_before, target))
            if len(current_before) == len(target)
            else 0.0
        )
        self._request("POST", "/api/move", json={"positions": target, "velocity": velocity})
        travel_timeout = max_delta / max(velocity, 0.01) + 8.0
        deadline = time.monotonic() + max(duration + 5.0, travel_timeout, 8.0)
        while time.monotonic() < deadline:
            self._raise_if_stopped()
            state = self.controller_status()
            current = state["positions"]
            if len(current) == 6 and max(abs(a - b) for a, b in zip(current, target)) <= 0.035:
                return
            time.sleep(0.25)
        raise RobotTaskError("MOVE_TIMEOUT", "机械臂未在规定时间到达目标位置")

    def _set_gripper(self, position: float, velocity: float = 0.03) -> None:
        self._raise_if_stopped()
        before = self.controller_status()
        current = before.get("gripper_position")
        self._request("POST", "/api/move", json={"gripper": position, "velocity": velocity})
        distance = abs(float(current) - position) if current is not None else 0.0
        deadline = time.monotonic() + max(distance / max(velocity, 0.01) + 5.0, 8.0)
        while time.monotonic() < deadline:
            self._raise_if_stopped()
            state = self.controller_status()
            actual = state.get("gripper_position")
            if actual is not None and abs(float(actual) - position) <= 0.05:
                return
            time.sleep(0.25)
        raise RobotTaskError("GRIPPER_TIMEOUT", "夹爪未在规定时间到达目标位置")

    def _navigate_and_wait(self, route_name: str) -> None:
        self._raise_if_stopped()
        route_task_id = self.navigator.start_route(route_name)
        with self._state_lock:
            self.runtime.route_task_id = route_task_id
        self._notify()
        deadline = time.monotonic() + self.route_timeout_seconds
        while time.monotonic() < deadline:
            self._raise_if_stopped()
            status = self.navigator.route_status(route_task_id)
            route_status = str(status.get("status", "unknown")).lower()
            if route_status in {"arrived", "completed", "succeeded", "success"}:
                return
            if route_status in {"failed", "error", "cancelled", "canceled", "stopped"}:
                raise RobotTaskError("VBOT_ROUTE_FAILED", "VBot 未能到达递水点")
            time.sleep(0.5)
        raise RobotTaskError("VBOT_ROUTE_TIMEOUT", "VBot 路线执行超时")

    def _wait_for_handover_confirmation(self) -> None:
        deadline = time.monotonic() + self.handover_timeout_seconds
        while time.monotonic() < deadline:
            self._raise_if_stopped()
            if self._handover_event.wait(timeout=0.25):
                self._raise_if_stopped()
                return
        raise RobotTaskError("HANDOVER_CONFIRMATION_TIMEOUT", "等待用户接杯确认超时")

    def _execute_delivery(self, task_id: str, plan: dict[str, Any], route_name: str) -> None:
        del task_id
        poses = plan["poses"]
        transport_safe = poses["transport_safe"]
        total_steps = 16

        def stage(index: int, name: str, message: str) -> None:
            self._set_stage(name, index / total_steps, message)

        try:
            stage(1, "moving_to_standby", "机械臂正在进入待机位")
            self._move_and_wait(poses["standby"])
            stage(2, "moving_to_pickup_approach", "机械臂正在接近水杯")
            self._move_and_wait(poses["pickup_approach"])
            stage(3, "moving_to_pickup", "机械臂正在进入取水位")
            self._move_and_wait(poses["pickup"])
            stage(4, "closing_gripper", "夹爪正在夹紧水杯")
            self._set_gripper(float(poses["pickup"].get("gripper", 0.0)))
            stage(5, "lifting_cup", "机械臂正在提起水杯")
            self._move_and_wait(poses["lift"])
            stage(6, "moving_to_transport_safe", "机械臂正在进入安全运输位")
            self._move_and_wait(transport_safe)
            stage(7, "navigating_vbot", "VBot 正在执行已录制的递水路线")
            self._navigate_and_wait(route_name)
            stage(8, "vbot_arrived", "VBot 已到达递水点")
            stage(9, "moving_to_handover_approach", "机械臂正在接近递水位置")
            self._move_and_wait(poses["handover_approach"])
            stage(10, "moving_to_handover", "机械臂已到达递水位置")
            self._move_and_wait(poses["handover"])
            self._set_stage(
                "waiting_user_ready",
                11 / total_steps,
                "请确认已经扶稳水杯，确认后夹爪才会松开",
                status="waiting_user",
                requires_user_action="confirm_handover_ready",
            )
            self._wait_for_handover_confirmation()
            stage(12, "releasing_cup", "用户已确认，夹爪正在松开水杯")
            self._set_gripper(float(poses["standby"].get("gripper", 0.0)))
            stage(13, "retreating_from_user", "机械臂正在离开递水位置")
            self._move_and_wait(poses["handover_approach"])
            stage(14, "returning_transport_safe", "机械臂正在返回安全运输位")
            self._move_and_wait(transport_safe)
            stage(15, "returning_pickup_approach", "机械臂正在安全回收")
            self._move_and_wait(poses["pickup_approach"])
            stage(16, "returning_to_standby", "机械臂正在返回待机位")
            self._move_and_wait(poses["standby"])
            with self._state_lock:
                self.runtime.status = "completed"
                self.runtime.progress = 1.0
                self.runtime.current_step = "completed"
                self.runtime.message = "递水任务已完成"
                self.runtime.requires_user_action = None
                self.runtime.completed_at = self._now()
                self.runtime.history.append(
                    {"step": "completed", "status": "completed", "message": "递水任务已完成", "at": self.runtime.completed_at}
                )
            self._notify()
        except RobotTaskError as exc:
            with self._state_lock:
                stopped = exc.code == "TASK_STOPPED"
                self.runtime.status = "stopped" if stopped else "failed"
                self.runtime.error = None if stopped else exc.code
                self.runtime.message = "递水任务已停止" if stopped else str(exc)
                self.runtime.requires_user_action = None
                self.runtime.completed_at = self._now()
                self.runtime.history.append(
                    {
                        "step": self.runtime.current_step,
                        "status": self.runtime.status,
                        "message": self.runtime.message,
                        "error": self.runtime.error,
                        "at": self.runtime.completed_at,
                    }
                )
            self._notify()
        except Exception:
            with self._state_lock:
                self.runtime.status = "failed"
                self.runtime.error = "UNEXPECTED_ROBOT_ERROR"
                self.runtime.message = "递水任务发生未预期错误"
                self.runtime.requires_user_action = None
                self.runtime.completed_at = self._now()
            self._notify()

    def _execute_pickup(self, task_id: str, plan: dict[str, Any]) -> None:
        """Run only the stationary arm pickup sequence used by the short demo.

        The cup remains gripped at the calibrated lift pose. This workflow never
        calls the VBot navigator, transport-safe pose, handover poses, or release.
        """
        del task_id
        poses = plan["poses"]

        def stage(index: int, name: str, message: str) -> None:
            self._set_stage(name, index / 5, message)

        try:
            stage(1, "moving_to_standby", "机械臂正在进入待机位")
            self._move_and_wait(poses["standby"])
            stage(2, "moving_to_pickup_approach", "机械臂正在接近水杯")
            self._move_and_wait(poses["pickup_approach"])
            stage(3, "moving_to_pickup", "机械臂正在进入取水位")
            self._move_and_wait(poses["pickup"])
            stage(4, "closing_gripper", "夹爪正在夹紧水杯")
            self._set_gripper(float(poses["pickup"].get("gripper", 0.0)))
            stage(5, "lifting_cup", "机械臂正在提起水杯")
            self._move_and_wait(poses["lift"])
            with self._state_lock:
                self.runtime.status = "completed"
                self.runtime.progress = 1.0
                self.runtime.current_step = "pickup_completed"
                self.runtime.message = "取水演示完成：水杯已提起，机械臂保持当前位置"
                self.runtime.requires_user_action = None
                self.runtime.completed_at = self._now()
                self.runtime.history.append({
                    "step": "pickup_completed",
                    "status": "completed",
                    "message": self.runtime.message,
                    "at": self.runtime.completed_at,
                })
            self._notify()
        except RobotTaskError as exc:
            with self._state_lock:
                stopped = exc.code == "TASK_STOPPED"
                self.runtime.status = "stopped" if stopped else "failed"
                self.runtime.error = None if stopped else exc.code
                self.runtime.message = "取水演示已停止" if stopped else str(exc)
                self.runtime.requires_user_action = None
                self.runtime.completed_at = self._now()
                self.runtime.history.append({
                    "step": self.runtime.current_step,
                    "status": self.runtime.status,
                    "message": self.runtime.message,
                    "error": self.runtime.error,
                    "at": self.runtime.completed_at,
                })
            self._notify()
        except Exception:
            with self._state_lock:
                self.runtime.status = "failed"
                self.runtime.error = "UNEXPECTED_ROBOT_ERROR"
                self.runtime.message = "取水演示发生未预期错误"
                self.runtime.requires_user_action = None
                self.runtime.completed_at = self._now()
            self._notify()

    def _validate_pickup_start(self) -> dict[str, Any]:
        plan = self.load_plan()
        poses = plan.get("poses", {})
        required = ("standby", "pickup_approach", "pickup", "lift")
        missing = [name for name in required if name not in poses]
        if missing:
            raise RobotTaskError(
                "PICKUP_TRAJECTORY_NOT_CALIBRATED",
                "取水轨迹尚未完成标定",
            )
        controller = self.controller_status()
        if not controller["connected"] or not controller["live"]:
            raise RobotTaskError("ROBOT_NOT_LIVE", "机械臂未处于真实连接模式")
        return plan

    def start_pickup(
        self, member_id: str = "unknown", task_id: str | None = None
    ) -> dict[str, Any]:
        with self._state_lock:
            if self.runtime.status in ACTIVE_TASK_STATUSES:
                raise RobotTaskError("TASK_ALREADY_RUNNING", "机械臂正在执行另一项任务")
            plan = self._validate_pickup_start()
            selected_task_id = task_id or f"pickup_{uuid.uuid4().hex}"
            self._stop_event.clear()
            self._handover_event.clear()
            now = self._now()
            self.runtime = RobotRuntime(
                task_id=selected_task_id,
                member_id=member_id,
                status="starting",
                current_step="starting",
                message="取水演示已通过安全检查，准备执行",
                started_at=now,
                history=[{
                    "step": "starting",
                    "status": "starting",
                    "message": "取水演示已通过安全检查，准备执行",
                    "at": now,
                }],
            )
            thread = threading.Thread(
                target=self._execute_pickup,
                args=(selected_task_id, plan),
                daemon=True,
                name=f"poopsense-{selected_task_id}",
            )
            thread.start()
        self._notify()
        return {
            "accepted": True,
            "task": "pickup_water",
            "task_id": selected_task_id,
            "status": "starting",
            "current_step": "starting",
            "requires_user_action": None,
        }

    def _validate_start(self) -> dict[str, Any]:
        status = self.plan_status()
        if not status["enabled"]:
            raise RobotTaskError("TRAJECTORY_NOT_CALIBRATED", "递水轨迹尚未完成标定")
        plan = self.load_plan()
        if "transport_safe" not in plan.get("poses", {}):
            raise RobotTaskError(
                "TRANSPORT_SAFE_POSE_NOT_CALIBRATED",
                "尚未录入机器狗移动时使用的机械臂安全运输位",
            )
        vbot = self.navigator.health()
        if not vbot.get("configured") or not vbot.get("connected"):
            raise RobotTaskError("VBOT_NOT_READY", "VBot 路线服务尚未连接")
        controller = self.controller_status()
        if not controller["connected"] or not controller["live"]:
            raise RobotTaskError("ROBOT_NOT_LIVE", "机械臂未处于真实连接模式")
        return plan

    def start_delivery(
        self, member_id: str = "unknown", route_name: str | None = None
    ) -> dict[str, Any]:
        with self._state_lock:
            if self.runtime.status in ACTIVE_TASK_STATUSES:
                raise RobotTaskError("TASK_ALREADY_RUNNING", "递水任务正在运行")
            plan = self._validate_start()
            task_id = f"delivery_{uuid.uuid4().hex}"
            selected_route = route_name or self.route_name
            self._stop_event.clear()
            self._handover_event.clear()
            now = self._now()
            self.runtime = RobotRuntime(
                task_id=task_id,
                member_id=member_id,
                route_name=selected_route,
                status="starting",
                current_step="starting",
                message="递水任务已通过安全检查，准备执行",
                started_at=now,
                history=[
                    {
                        "step": "starting",
                        "status": "starting",
                        "message": "递水任务已通过安全检查，准备执行",
                        "at": now,
                    }
                ],
            )
            thread = threading.Thread(
                target=self._execute_delivery,
                args=(task_id, plan, selected_route),
                daemon=True,
                name=f"poopsense-{task_id}",
            )
            thread.start()
        self._notify()
        return {
            "accepted": True,
            "task": "deliver_water",
            "task_id": task_id,
            "status": "starting",
            "current_step": "starting",
            "requires_user_action": None,
        }

    def confirm_handover(self, task_id: str, confirmed: bool) -> dict[str, Any]:
        with self._state_lock:
            if self.runtime.task_id != task_id:
                raise RobotTaskError("TASK_NOT_FOUND", "未找到递水任务")
            if self.runtime.status != "waiting_user" or self.runtime.current_step != "waiting_user_ready":
                raise RobotTaskError("TASK_NOT_WAITING_HANDOVER", "任务尚未等待接杯确认")
            if not confirmed:
                self._stop_event.set()
                self._handover_event.set()
                return {"accepted": True, "task_id": task_id, "status": "stopping"}
            self.runtime.message = "已收到接杯确认"
            self.runtime.requires_user_action = None
            self._handover_event.set()
        self._notify()
        return {"accepted": True, "task_id": task_id, "status": "confirmed"}

    def stop(self) -> dict[str, Any]:
        with self._state_lock:
            task_id = self.runtime.task_id
            route_task_id = self.runtime.route_task_id
            active = self.runtime.status in ACTIVE_TASK_STATUSES
            if active:
                self.runtime.status = "stopping"
                self.runtime.message = (
                    "正在停止机械臂和 VBot"
                    if route_task_id
                    else "正在停止机械臂"
                )
                self.runtime.requires_user_action = None
            self._stop_event.set()
            self._handover_event.set()
        try:
            self.navigator.stop(route_task_id)
        except RobotTaskError:
            pass
        try:
            self._request("POST", "/api/trajectory/stop", json={})
        except RobotTaskError:
            if not active:
                raise
        self._notify()
        return {"stopped": True, "task_id": task_id}

    def runtime_status(self, task_id: str | None = None) -> dict[str, Any]:
        with self._state_lock:
            if task_id and self.runtime.task_id != task_id:
                raise RobotTaskError("TASK_NOT_FOUND", "未找到递水任务")
            return {
                "task_id": self.runtime.task_id,
                "member_id": self.runtime.member_id,
                "route_name": self.runtime.route_name,
                "route_task_id": self.runtime.route_task_id,
                "status": self.runtime.status,
                "progress": self.runtime.progress,
                "current_step": self.runtime.current_step,
                "error": self.runtime.error,
                "message": self.runtime.message,
                "requires_user_action": self.runtime.requires_user_action,
                "started_at": self.runtime.started_at,
                "completed_at": self.runtime.completed_at,
                "history": list(self.runtime.history),
            }
