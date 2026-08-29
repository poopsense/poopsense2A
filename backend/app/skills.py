from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


@dataclass(frozen=True)
class SkillContract:
    name: str
    version: str
    agent: str
    risk: str
    allowed_roles: tuple[str, ...]
    context_domains: tuple[str, ...]
    proactive_allowed: bool
    confirmation_required: bool
    input_schema: dict[str, str]
    output_schema: dict[str, str]


SKILL_CONTRACTS = {
    item.name: item for item in [
        SkillContract("explain_record", "1.0.0", "health_doctor", "low",
                      ("owner", "caregiver", "viewer"),
                      ("recent_assessments", "visible_memory", "feedback_preferences"), False, False,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
        SkillContract("summarize_trend", "1.0.0", "health_doctor", "low",
                      ("owner", "caregiver", "viewer"),
                      ("trend", "recent_assessments", "visible_memory", "feedback_preferences"), False, False,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
        SkillContract("health_education", "1.0.0", "health_doctor", "low",
                      ("owner", "caregiver", "viewer"),
                      ("trend", "self_report_memory", "feedback_preferences"), False, False,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
        SkillContract("comprehensive_review", "1.0.0", "health_doctor", "medium",
                      ("owner", "caregiver", "viewer"),
                      ("trend", "recent_assessments", "visible_memory", "self_report_memory", "feedback_preferences"), False, False,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
        SkillContract("lifestyle_coaching", "1.0.0", "life_coach", "low",
                      ("owner", "caregiver", "viewer"),
                      ("trend", "self_report_memory", "feedback_preferences"), False, False,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
        SkillContract("urgent_care", "1.0.0", "health_doctor", "high",
                      ("owner", "caregiver", "viewer"),
                      ("recent_assessments", "visible_memory", "feedback_preferences"), True, False,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
        SkillContract("send_check_in", "1.0.0", "life_coach", "medium",
                      ("owner", "caregiver"), ("trend", "self_report_memory", "feedback_preferences"), True, False,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
        SkillContract("manage_household", "1.0.0", "household_steward", "medium",
                      ("owner", "caregiver"), ("household_scope",), False, True,
                      {"goal": "str", "member_id": "str", "decision": "str"},
                      {"reply": "str", "decision": "str"}),
    ]
}


def contract_for(skill_name: str) -> SkillContract:
    contract = SKILL_CONTRACTS.get(skill_name)
    if not contract:
        raise HTTPException(status_code=422, detail={"code": "SKILL_NOT_REGISTERED"})
    return contract


def _validate(schema: dict[str, str], payload: dict[str, Any], code: str) -> None:
    type_map = {"str": str, "bool": bool, "dict": dict, "list": list, "int": int}
    for field, type_name in schema.items():
        if field not in payload or not isinstance(payload[field], type_map[type_name]):
            raise HTTPException(status_code=422, detail={"code": code, "field": field})


def validate_skill_input(contract: SkillContract, payload: dict[str, Any], role: str) -> None:
    if role not in contract.allowed_roles:
        raise HTTPException(status_code=403, detail={"code": "SKILL_PERMISSION_DENIED"})
    _validate(contract.input_schema, payload, "SKILL_INPUT_INVALID")


def validate_skill_output(contract: SkillContract, payload: dict[str, Any]) -> None:
    _validate(contract.output_schema, payload, "SKILL_OUTPUT_INVALID")


def should_pause_for_confirmation(contract: SkillContract, goal: str) -> bool:
    if not contract.confirmation_required:
        return False
    action_phrases = (
        "帮我授权", "开启授权", "关闭授权", "撤回授权", "确认归属",
        "纠正归属", "添加成员", "删除成员", "邀请成员",
    )
    return any(phrase in goal for phrase in action_phrases)
