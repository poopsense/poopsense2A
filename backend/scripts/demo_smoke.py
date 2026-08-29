"""Read-only smoke test for the running PoopSense demo."""

from __future__ import annotations

import argparse
import sys

import httpx


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", default="http://127.0.0.1:5173")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--test-model", action="store_true")
    args = parser.parse_args()
    headers = {"X-Household-Key": "household-secret"}

    try:
        with httpx.Client(timeout=45) as client:
            frontend = client.get(args.frontend)
            require(frontend.status_code == 200, "frontend is not reachable")
            require("PoopSense" in frontend.text, "frontend shell is unexpected")

            ready = client.get(f"{args.backend}/ready")
            require(ready.status_code == 200, "backend readiness failed")
            readiness = ready.json()
            require(readiness.get("database") == "ok", "database is not ready")
            require(readiness.get("worker_last_error") is None, "worker has an error")

            members = client.get(
                f"{args.backend}/api/v1/households/hh_001/members", headers=headers
            )
            require(members.status_code == 200, "member list failed")
            member_rows = members.json()
            require(bool(member_rows), "demo household has no members")
            member_id = member_rows[0]["member_id"]

            trend = client.get(
                f"{args.backend}/api/v1/households/hh_001/members/{member_id}/trends?days=30",
                headers=headers,
            )
            require(trend.status_code == 200, "member trend failed")

            status = client.get(
                f"{args.backend}/api/v1/households/hh_001/agent/status", headers=headers
            )
            require(status.status_code == 200, "agent status failed")
            agent = status.json()
            require(agent.get("worker_running") is True, "agent worker is not running")

            if args.test_model:
                require(agent.get("configured") is True, "model is not configured")
                chat = client.post(
                    f"{args.backend}/api/v1/households/hh_001/agent/chat",
                    headers=headers,
                    json={"member_id": member_id, "message": "请用一句话确认演示系统已连接。"},
                )
                require(chat.status_code == 200, f"model call failed: {chat.status_code}")
                require(bool(chat.json()["message"]["content"].strip()), "model returned an empty reply")

        print(
            "DEMO_SMOKE_OK "
            f"frontend=ok database=ok members={len(member_rows)} "
            f"agent_configured={str(agent.get('configured')).lower()} "
            f"model_tested={str(args.test_model).lower()}"
        )
        return 0
    except (httpx.HTTPError, RuntimeError, KeyError) as exc:
        print(f"DEMO_SMOKE_FAILED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
