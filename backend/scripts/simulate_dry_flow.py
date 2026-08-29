"""Inject one reliable dry-stool result for the local end-to-end demo.

This script only simulates the sensor result and assigns it to a demo member.
It never starts the physical robot. The arm still requires two explicit clicks
in the Agent UI before the pickup-only trajectory can begin.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import sys
import uuid

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--member", default="m_001")
    parser.add_argument("--device-key", default="dev-secret")
    parser.add_argument("--household-key", default="household-secret")
    args = parser.parse_args()

    # The local SQLite demo database stores device timestamps without timezone
    # information. Use the machine's local wall-clock value so a fresh sample
    # sorts after older local demo rows. Production PostgreSQL keeps timestamptz.
    now = datetime.now().astimezone()
    token = uuid.uuid4().hex[:10]
    session_id = f"demo_dry_{token}"
    payload = {
        "schema_version": "1.0",
        "session_id": session_id,
        "correlation_id": f"cor_{session_id}",
        "device_id": "dev_001",
        "household_id": "hh_001",
        "firmware_version": "0.3.0",
        "model_version": "edge-demo-dry-v1",
        "sequence_number": int(now.timestamp() * 1000),
        "source": "device",
        "timestamp": now.isoformat(),
        "end_timestamp": (now + timedelta(seconds=90)).isoformat(),
        "duration_s": 90,
        "clock_status": "synced",
        "clock_offset_ms": 0,
        "presence_state": "present",
        "collection_state": "completed",
        "observations": {
            "shape": {
                "value": "hard",
                "confidence": 0.96,
                "source": "sensor",
                "model_version": "shape-demo-dry-v1",
            },
            "color": {
                "value": "brown",
                "confidence": 0.94,
                "source": "sensor",
                "model_version": "color-demo-v1",
            },
            "odor": {
                "value": "moderate",
                "confidence": 0.90,
                "source": "sensor",
                "model_version": "odor-demo-v1",
            },
        },
        "temperature_c": 24.6,
        "humidity_pct": 61.0,
        "quality": {"overall_confidence": 0.95, "reasons": []},
        "member_candidates": [{"member_ref": args.member, "confidence": 0.91}],
    }

    try:
        with httpx.Client(base_url=args.backend, timeout=15, trust_env=False) as client:
            received = client.post(
                "/api/v1/device-sessions",
                headers={"X-Device-Key": args.device_key},
                json=payload,
            )
            received.raise_for_status()
            claim = client.post(
                f"/api/v1/households/hh_001/sessions/{session_id}/claim",
                headers={"X-Household-Key": args.household_key},
                json={"member_id": args.member, "claim_method": "admin_claim"},
            )
            claim.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"DRY_FLOW_FAILED {exc}", file=sys.stderr)
        return 1

    print(f"DRY_FLOW_READY session_id={session_id} member_id={args.member}")
    print("Keep the Home page open. Within 5 seconds it should show the cartoon, then Agent advice.")
    print("The physical arm will not move until you click 准备取水 and 确认开始取水.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
