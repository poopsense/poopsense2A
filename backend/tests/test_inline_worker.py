from fastapi import HTTPException

from app.agent import parse_model_decision
from app.inline_worker import run_inline_worker_cycle, worker_runtime


def test_model_decision_accepts_fenced_json():
    result = parse_model_decision(
        '```json\n{"action":"no_action","reason":"stable","message":""}\n```'
    )
    assert result["action"] == "no_action"


def test_model_decision_rejects_non_json():
    try:
        parse_model_decision("I cannot return a decision")
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail["code"] == "MODEL_INVALID_DECISION"
    else:
        raise AssertionError("invalid model output must be rejected")


def test_inline_worker_cycle_is_bounded_and_observable(client):
    before = worker_runtime.processed_total
    assert run_inline_worker_cycle() == 0
    assert worker_runtime.last_run_at is not None
    assert worker_runtime.last_error is None
    assert worker_runtime.processed_total == before
