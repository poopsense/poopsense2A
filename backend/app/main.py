import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    AgentAction, AgentConversation, AgentFeedback, AgentHandoff, AgentMemoryEntry, AgentMessage, AgentProfile, AgentProfileRevision, AgentRun, ApiCredential, Assessment, DeviceBinding, FamilyGrant,
    Household, HouseholdMember, HouseholdMembership, MemberAssignment, Observation, SessionRecord, UserAccount,
    UserNotification,
)
from .schemas import (
    AssessmentResult, ClaimInput, ClaimResult, DeviceSessionInput, GrantInput,
    GrantResult, HouseholdMemberCreateInput, HouseholdMemberResult, InboxItem, MemberSessionResult, MemberTrend, PoopVisualDimension, PoopVisualProfile,
    AgentActionResult, AgentChatInput, AgentChatResult, AgentConversationResult,
    AgentConversationSummary, AgentMessageResult, AgentStatusResult,
    AgentFeedbackInput, AgentFeedbackResult, DeviceResult, GrantListItem, HealthProfileInput, HealthProfileResult, MemoryCreateInput, MemoryResult, MemoryUpdateInput,
    AgentProfileResult, AgentProfileUpdate,
    AgentHandoffResult, AgentProfileRevisionResult, AgentRunResult, AgentStepResult,
    SkillContractResult,
    AgentResumeInput, AgentResumeResult,
    PetCheckinResult, PetProfileUpdate, PetSnapshotResult,
    CommunityPostInput, CommunityPostResult,
    AgentConnectionCreateInput, AgentConnectionRespondInput, AgentConnectionResult,
    WeeklyHealthReportResult,
    RawDataAuthorizationInput, RawDataAuthorizationResult, RawDataUploadInput, RawDataUploadResult,
    RobotDeliveryInput, RobotHandoverConfirmationInput, RobotPlanResult,
    RobotPoseCaptureInput, RobotTaskResult,
    NotificationResult, RevokeResult, SessionReceipt,
)
from .service import (
    authorize_household, authorize_member_view, claim_session, create_assessment_version,
    grant_family_view, hash_secret, ingest, member_trend, revoke_family_view,
)
from .agent import chat as agent_chat, resume_paused_chat
from .service import POLICY_VERSION
from .memory import create_self_report, get_health_profile, list_memory, save_health_profile, update_memory
from .inline_worker import inline_worker_loop, worker_runtime
from .agent_native import SKILLS, get_or_create_profile, profile_snapshot
from .agent_loop import list_handoffs, list_steps
from .skills import SKILL_CONTRACTS
from .robot import (
    RobotTaskError, RobotTaskService, UnavailableVBotNavigator, VBotHttpNavigator,
)
from .pet import check_in as pet_check_in, pet_snapshot, update_pet_profile
from .community import list_posts as list_community_posts, publish as publish_community_post, withdraw as withdraw_community_post
from .connections import create_request as create_agent_match, list_connections as list_agent_matches, respond as respond_agent_match, end as end_agent_match
from .weekly_reports import generate as generate_weekly_report, list_reports as list_weekly_reports
from .raw_data import complete_deletion as complete_raw_deletion, create_authorization as create_raw_authorization, list_authorizations as list_raw_authorizations, register_upload as register_raw_upload, revoke as revoke_raw_authorization


vbot_navigator = (
    VBotHttpNavigator(settings.vbot_bridge_url, settings.vbot_bridge_timeout_seconds)
    if settings.vbot_bridge_enabled
    else UnavailableVBotNavigator()
)

robot_service = RobotTaskService(
    settings.robot_host_url,
    Path(settings.robot_trajectory_path),
    settings.robot_timeout_seconds,
    navigator=vbot_navigator,
    route_name=settings.vbot_route_name,
    route_timeout_seconds=settings.vbot_route_timeout_seconds,
    handover_timeout_seconds=settings.robot_handover_timeout_seconds,
)


def persist_robot_runtime(snapshot: dict) -> None:
    """Persist deterministic Tool progress for audit and result feedback."""
    task_id = snapshot.get("task_id")
    if not task_id:
        return
    with SessionLocal() as db:
        action = db.scalar(select(AgentAction).where(
            AgentAction.idempotency_key.in_([
                f"robot-delivery:{task_id}",
                f"robot-pickup:{task_id}",
            ])
        ))
        if not action:
            return
        task_status = snapshot.get("status")
        action.status = {
            "completed": "succeeded",
            "failed": "failed",
            "stopped": "cancelled",
        }.get(task_status, "processing")
        action.result = snapshot
        if task_status in {"completed", "failed", "stopped"}:
            action.processed_at = datetime.now(timezone.utc)
        db.commit()


robot_service.set_event_sink(persist_robot_runtime)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    if settings.bootstrap_demo_device:
        with SessionLocal() as db:
            for user_id, name in [("u_owner", "Demo Owner"), ("u_viewer", "Demo Viewer")]:
                if not db.get(UserAccount, user_id):
                    db.add(UserAccount(id=user_id, display_name=name, active=True))
            if not db.get(Household, "hh_001"):
                db.add(Household(id="hh_001", name="Demo Household", active=True))
            db.flush()
            for user_id, role in [("u_owner", "owner"), ("u_viewer", "viewer")]:
                exists = db.scalar(select(HouseholdMembership).where(
                    HouseholdMembership.household_id == "hh_001",
                    HouseholdMembership.user_id == user_id,
                ))
                if not exists:
                    db.add(HouseholdMembership(household_id="hh_001", user_id=user_id,
                                               role=role, active=True))
            for secret, user_id in [("household-secret", "u_owner"), ("viewer-secret", "u_viewer")]:
                key_hash = hash_secret(secret)
                if not db.get(ApiCredential, key_hash):
                    db.add(ApiCredential(api_key_hash=key_hash, user_id=user_id, active=True))
            for member_id, name, linked_user in [
                ("m_001", "Alex", "u_owner"),
                ("m_002", "Sam", None),
            ]:
                member = db.get(HouseholdMember, member_id)
                if not member:
                    db.add(HouseholdMember(id=member_id, household_id="hh_001",
                                           display_name=name, linked_user_id=linked_user, active=True))
                else:
                    member.display_name = name
            if not db.get(DeviceBinding, "dev_001"):
                db.add(DeviceBinding(device_id="dev_001", household_id="hh_001",
                                     api_key_hash=hash_secret("dev-secret"), active=True))
            db.commit()
            if settings.bootstrap_demo_data and not db.scalar(select(SessionRecord).where(SessionRecord.household_id == "hh_001")):
                now = datetime.now(timezone.utc)
                demo_rows = [
                    ("demo_01", 12, "normal", "brown", "moderate"),
                    ("demo_02", 9, "normal", "brown", "mild"),
                    ("demo_03", 6, "hard", "brown", "moderate"),
                    ("demo_04", 2, "normal", "brown", "moderate"),
                    ("demo_pending", 0, "normal", "brown", "moderate"),
                ]
                for sequence, (session_id, days_ago, shape, color, odor) in enumerate(demo_rows, 1):
                    started = now - timedelta(days=days_ago, hours=2)
                    payload = DeviceSessionInput.model_validate({
                        "schema_version": "1.0", "session_id": session_id,
                        "correlation_id": f"cor_{session_id}", "device_id": "dev_001",
                        "household_id": "hh_001", "firmware_version": "0.3.0",
                        "model_version": "edge-0.2.0", "sequence_number": sequence,
                        "source": "device", "timestamp": started,
                        "end_timestamp": started + timedelta(seconds=90), "duration_s": 90,
                        "clock_status": "synced", "clock_offset_ms": 40,
                        "presence_state": "present", "collection_state": "completed",
                        "observations": {
                            "shape": {"value": shape, "confidence": .88, "source": "sensor", "model_version": "shape-0.1"},
                            "color": {"value": color, "confidence": .91, "source": "sensor", "model_version": "color-0.2"},
                            "odor": {"value": odor, "confidence": .82, "source": "sensor", "model_version": "odor-0.1"},
                        },
                        "temperature_c": 24.6, "humidity_pct": 61.0,
                        "quality": {"overall_confidence": .86, "reasons": []},
                        "member_candidates": [{"member_ref": "m_001", "confidence": .62}],
                    })
                    record, _, _, _ = ingest(db, payload, "dev-secret")
                    if session_id != "demo_pending":
                        claim_session(db, record, ClaimInput(member_id="m_001", claim_method="admin_claim"))
    stop_event = asyncio.Event()
    worker_task = None
    if settings.inline_worker_enabled:
        worker_task = asyncio.create_task(inline_worker_loop(stop_event))
    try:
        yield
    finally:
        if worker_task is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(worker_task, timeout=5)
            except TimeoutError:
                worker_task.cancel()


app = FastAPI(title="PoopSense API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Device-Key", "X-Household-Key"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    """Report whether the local demo dependencies are ready without exposing secrets."""
    db.execute(select(1)).scalar_one()
    return {
        "status": "ready",
        "database": "ok",
        "agent_configured": bool(settings.llm_api_key),
        "proactive_enabled": bool(
            settings.llm_api_key and settings.llm_proactive_enabled
        ),
        "worker_enabled": settings.inline_worker_enabled,
        "worker_running": worker_runtime.running,
        "worker_last_error": worker_runtime.last_error,
    }


def robot_http_error(exc: RobotTaskError) -> HTTPException:
    if exc.code == "TASK_NOT_FOUND":
        status_code = 404
    elif exc.code in {
        "ROBOT_UNAVAILABLE", "ROBOT_NOT_LIVE", "VBOT_UNAVAILABLE",
        "VBOT_NOT_CONFIGURED", "VBOT_NOT_READY",
    }:
        status_code = 503
    else:
        status_code = 409
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)})


@app.get(
    "/api/v1/households/{household_id}/robot/status",
)
def robot_status(household_id: str, x_household_key: str = Header(...),
                 db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key)
    try:
        return {
            "controller": robot_service.controller_status(),
            "vbot": robot_service.navigator_status(),
            "plan": robot_service.plan_status(),
            "task": robot_service.runtime_status(),
        }
    except RobotTaskError as exc:
        raise robot_http_error(exc) from exc


@app.post(
    "/api/v1/households/{household_id}/robot/trajectories/deliver-water/poses/{pose_name}",
    response_model=RobotPlanResult,
)
def capture_delivery_pose(household_id: str, pose_name: str, payload: RobotPoseCaptureInput,
                          x_household_key: str = Header(...), db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key, {"owner", "caregiver"})
    try:
        return robot_service.capture_pose(pose_name, payload.duration)
    except RobotTaskError as exc:
        raise robot_http_error(exc) from exc


@app.post(
    "/api/v1/households/{household_id}/robot/tasks/pickup-water",
    response_model=RobotTaskResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def pickup_water(household_id: str, payload: RobotDeliveryInput,
                 x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    authorize_member_view(db, auth, payload.member_id)
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail={"code": "USER_CONFIRMATION_REQUIRED"})
    task_id = f"pickup_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    action = AgentAction(
        session_id=None,
        subject_member_id=payload.member_id,
        grant_id=None,
        action_type="robot_pickup_water",
        status="processing",
        recipient_id=auth.user_id,
        authorization_basis=f"explicit_user_confirmation:{auth.user_id}",
        policy_version=POLICY_VERSION,
        model_version="deterministic-tool-v1",
        input_summary={"task_id": task_id, "confirmed": True,
                       "scope": "stationary_arm_pickup_only"},
        result={"task_id": task_id, "status": "pending_safety_check"},
        idempotency_key=f"robot-pickup:{task_id}",
        created_at=now,
        processed_at=None,
    )
    db.add(action)
    db.commit()
    try:
        return robot_service.start_pickup(payload.member_id, task_id=task_id)
    except RobotTaskError as exc:
        action.status = "failed"
        action.result = {"task_id": task_id, "status": "failed", "error": exc.code,
                         "message": str(exc)}
        action.processed_at = datetime.now(timezone.utc)
        db.commit()
        raise robot_http_error(exc) from exc


@app.post(
    "/api/v1/households/{household_id}/robot/tasks/deliver-water",
    response_model=RobotTaskResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def deliver_water(household_id: str, payload: RobotDeliveryInput,
                  x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    authorize_member_view(db, auth, payload.member_id)
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail={"code": "USER_CONFIRMATION_REQUIRED"})
    try:
        result = robot_service.start_delivery(payload.member_id, payload.route_name)
        now = datetime.now(timezone.utc)
        action = AgentAction(
            session_id=None,
            subject_member_id=payload.member_id,
            grant_id=None,
            action_type="robot_deliver_water",
            status="processing",
            recipient_id=auth.user_id,
            authorization_basis=f"explicit_user_confirmation:{auth.user_id}",
            policy_version=POLICY_VERSION,
            model_version="deterministic-tool-v1",
            input_summary={
                "task_id": result["task_id"],
                "route_name": payload.route_name or settings.vbot_route_name,
                "confirmed": True,
            },
            result=robot_service.runtime_status(result["task_id"]),
            idempotency_key=f"robot-delivery:{result['task_id']}",
            created_at=now,
            processed_at=None,
        )
        db.add(action)
        db.commit()
        persist_robot_runtime(robot_service.runtime_status(result["task_id"]))
        return result
    except RobotTaskError as exc:
        raise robot_http_error(exc) from exc


@app.get("/api/v1/households/{household_id}/robot/tasks/{task_id}")
def get_robot_task(household_id: str, task_id: str,
                   x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    try:
        result = robot_service.runtime_status(task_id)
        if result.get("member_id"):
            authorize_member_view(db, auth, result["member_id"])
        persist_robot_runtime(result)
        return result
    except RobotTaskError as exc:
        raise robot_http_error(exc) from exc


@app.post("/api/v1/households/{household_id}/robot/tasks/{task_id}/confirm-handover")
def confirm_robot_handover(
    household_id: str,
    task_id: str,
    payload: RobotHandoverConfirmationInput,
    x_household_key: str = Header(...),
    db: Session = Depends(get_db),
):
    auth = authorize_household(db, household_id, x_household_key)
    try:
        task = robot_service.runtime_status(task_id)
        if task.get("member_id"):
            authorize_member_view(db, auth, task["member_id"])
        return robot_service.confirm_handover(task_id, payload.confirmed)
    except RobotTaskError as exc:
        raise robot_http_error(exc) from exc


@app.post("/api/v1/households/{household_id}/robot/tasks/stop")
def stop_robot_task(household_id: str, x_household_key: str = Header(...),
                    db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key, {"owner", "caregiver"})
    try:
        return robot_service.stop()
    except RobotTaskError as exc:
        raise robot_http_error(exc) from exc


@app.post("/api/v1/device-sessions", response_model=SessionReceipt, status_code=status.HTTP_202_ACCEPTED)
def receive_device_session(
    payload: DeviceSessionInput,
    x_device_key: str = Header(...),
    db: Session = Depends(get_db),
):
    record, assignment, assessment, duplicate = ingest(db, payload, x_device_key)
    return SessionReceipt(
        session_id=record.external_session_id,
        correlation_id=record.correlation_id,
        received_at=record.received_at,
        assignment_status=assignment.assignment_status,
        assessment_status=assessment.status,
        message=assessment.message,
        duplicate=duplicate,
    )


@app.post("/api/v1/raw-data-uploads", response_model=RawDataUploadResult, status_code=status.HTTP_202_ACCEPTED)
def receive_raw_data_upload(payload: RawDataUploadInput, x_device_key: str = Header(...),
                            db: Session = Depends(get_db)):
    return RawDataUploadResult(**register_raw_upload(db, payload, x_device_key))


@app.get("/api/v1/households/{household_id}/claim-inbox", response_model=list[InboxItem])
def claim_inbox(household_id: str, x_household_key: str = Header(...), db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key, {"owner", "caregiver"})
    rows = db.execute(
        select(SessionRecord, MemberAssignment)
        .join(MemberAssignment, MemberAssignment.session_id == SessionRecord.id)
        .where(SessionRecord.household_id == household_id,
               MemberAssignment.active.is_(True),
               MemberAssignment.assignment_status == "pending_claim")
        .order_by(SessionRecord.received_at.desc())
    ).all()
    return [InboxItem(session_id=s.external_session_id, received_at=s.received_at,
                      candidates=a.candidates, assignment_version=a.version) for s, a in rows]


@app.post("/api/v1/households/{household_id}/sessions/{session_id}/claim", response_model=ClaimResult)
def claim(household_id: str, session_id: str, payload: ClaimInput,
          x_household_key: str = Header(...), db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key, {"owner", "caregiver"})
    record = db.scalar(select(SessionRecord).where(
        SessionRecord.external_session_id == session_id,
        SessionRecord.household_id == household_id,
    ))
    if not record:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"})
    assignment = claim_session(db, record, payload)
    return ClaimResult(session_id=session_id, member_id=assignment.member_id,
                       assignment_status=assignment.assignment_status, version=assignment.version)


@app.post(
    "/api/v1/households/{household_id}/sessions/{session_id}/reassess",
    response_model=AssessmentResult,
)
def reassess(household_id: str, session_id: str, x_household_key: str = Header(...),
             db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key, {"owner", "caregiver"})
    record = db.scalar(select(SessionRecord).where(
        SessionRecord.external_session_id == session_id,
        SessionRecord.household_id == household_id,
    ))
    if not record:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"})
    assessment = create_assessment_version(db, record)
    db.commit()
    return AssessmentResult(
        session_id=session_id, version=assessment.version, status=assessment.status,
        reliable=assessment.reliable, risk_level=assessment.risk_level,
        message=assessment.message, policy_version=assessment.policy_version,
        reasons=assessment.reasons,
    )


@app.get(
    "/api/v1/households/{household_id}/members/{member_id}/trends",
    response_model=MemberTrend,
)
def trends(household_id: str, member_id: str, days: int = 30,
           x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    authorize_member_view(db, auth, member_id)
    if days < 1 or days > 365:
        raise HTTPException(status_code=422, detail={"code": "INVALID_TREND_PERIOD"})
    return member_trend(db, household_id, member_id, days)


@app.get(
    "/api/v1/households/{household_id}/members",
    response_model=list[HouseholdMemberResult],
)
def list_members(household_id: str, x_household_key: str = Header(...),
                 db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    query = select(HouseholdMember).where(
        HouseholdMember.household_id == household_id,
        HouseholdMember.active.is_(True),
    )
    if auth.role != "owner":
        granted_ids = select(FamilyGrant.subject_member_id).where(
            FamilyGrant.household_id == household_id,
            FamilyGrant.viewer_user_id == auth.user_id,
            FamilyGrant.active.is_(True), FamilyGrant.status == "active",
            FamilyGrant.can_view.is_(True),
        )
        query = query.where(
            (HouseholdMember.linked_user_id == auth.user_id)
            | HouseholdMember.id.in_(granted_ids)
        )
    members = db.scalars(query.order_by(HouseholdMember.display_name)).all()
    return [HouseholdMemberResult(
        member_id=item.id, display_name=item.display_name,
        linked_to_current_user=item.linked_user_id == auth.user_id,
    ) for item in members]


@app.post("/api/v1/households/{household_id}/members", response_model=HouseholdMemberResult)
def create_household_member(household_id: str, payload: HouseholdMemberCreateInput,
                            x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key, {"owner"})
    display_name = payload.display_name.strip()
    duplicate = db.scalar(select(HouseholdMember).where(
        HouseholdMember.household_id == household_id,
        HouseholdMember.active.is_(True),
        HouseholdMember.display_name == display_name,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "MEMBER_NAME_ALREADY_EXISTS"})
    import uuid
    member = HouseholdMember(id=f"m_{uuid.uuid4().hex[:12]}", household_id=household_id,
                             display_name=display_name, linked_user_id=None, active=True)
    db.add(member); db.commit()
    return HouseholdMemberResult(member_id=member.id, display_name=member.display_name,
                                 linked_to_current_user=False)


@app.get("/api/v1/households/{household_id}/devices", response_model=list[DeviceResult])
def list_devices(household_id: str, x_household_key: str = Header(...),
                 db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key)
    devices = db.scalars(select(DeviceBinding).where(
        DeviceBinding.household_id == household_id
    ).order_by(DeviceBinding.device_id)).all()
    result = []
    for device in devices:
        latest = db.scalar(select(SessionRecord).where(
            SessionRecord.device_id == device.device_id
        ).order_by(SessionRecord.received_at.desc()))
        result.append(DeviceResult(
            device_id=device.device_id, household_id=device.household_id,
            active=device.active, status="online" if device.active else "unbound",
            firmware_version=latest.firmware_version if latest else None,
            model_version=latest.model_version if latest else None,
            last_seen_at=latest.received_at if latest else None,
        ))
    return result


@app.get(
    "/api/v1/households/{household_id}/members/{member_id}/grants",
    response_model=list[GrantListItem],
)
def list_grants(household_id: str, member_id: str,
                x_household_key: str = Header(...), db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key, {"owner"})
    grants = db.scalars(select(FamilyGrant).where(
        FamilyGrant.household_id == household_id,
        FamilyGrant.subject_member_id == member_id,
    ).order_by(FamilyGrant.version.desc())).all()
    return [GrantListItem(
        grant_id=g.id, household_id=g.household_id, subject_member_id=g.subject_member_id,
        viewer_user_id=g.viewer_user_id, version=g.version, status=g.status,
        can_view=g.can_view, redline_notifications=g.redline_notifications,
        granted_at=g.granted_at, revoked_at=g.revoked_at,
    ) for g in grants]


@app.post("/api/v1/households/{household_id}/agent/chat", response_model=AgentChatResult)
def chat_with_agent(household_id: str, payload: AgentChatInput,
                    x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    result = agent_chat(db, auth, payload.member_id, payload.message, payload.conversation_id)
    message = result["message"]
    return AgentChatResult(
        conversation_id=result["conversation"].id,
        message=AgentMessageResult(message_id=message.id, role=message.role, content=message.content,
                                   created_at=message.created_at),
        decision=result["decision"], allowed_actions=result["allowed_actions"],
        authorization_basis=result["authorization_basis"], policy_version=message.policy_version,
        model_version=message.model_version,
        delegated_agent=result["delegated_agent"], skill=result["skill"],
        skill_version=result["skill_version"], run_id=result["run"].id,
    )


@app.get("/api/v1/households/{household_id}/agent/runs/{run_id}", response_model=AgentRunResult)
def get_agent_run(household_id: str, run_id: str,
                  x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    run = db.get(AgentRun, run_id)
    if not run or run.household_id != household_id:
        raise HTTPException(status_code=404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    if run.subject_member_id:
        authorize_member_view(db, auth, run.subject_member_id)
    if auth.role != "owner" and run.created_by_user_id != auth.user_id:
        raise HTTPException(status_code=403, detail={"code": "AGENT_RUN_PRIVATE"})
    return AgentRunResult(
        run_id=run.id, member_id=run.subject_member_id, trigger=run.trigger,
        goal=run.goal, status=run.status, current_step=run.current_step,
        max_steps=run.max_steps, result=run.result, error=run.error,
        created_at=run.created_at, completed_at=run.completed_at,
        steps=[AgentStepResult(
            step_index=step.step_index, agent_name=step.agent_name,
            skill_name=step.skill_name, skill_version=step.skill_version,
            status=step.status,
            output_summary=step.output_summary, started_at=step.started_at,
            completed_at=step.completed_at, error=step.error,
        ) for step in list_steps(db, run.id)],
        handoffs=[AgentHandoffResult(
            from_agent=item.from_agent, to_agent=item.to_agent,
            skill_name=item.skill_name, skill_version=item.skill_version,
            context_domains=item.context_domains, status=item.status,
            authorization_basis=item.authorization_basis,
            created_at=item.created_at, accepted_at=item.accepted_at,
        ) for item in list_handoffs(db, run.id)],
    )


@app.get("/api/v1/households/{household_id}/agent/skills", response_model=list[SkillContractResult])
def list_agent_skills(household_id: str, x_household_key: str = Header(...),
                      db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key)
    return [SkillContractResult(
        name=contract.name, version=contract.version, agent=contract.agent,
        risk=contract.risk, allowed_roles=list(contract.allowed_roles),
        context_domains=list(contract.context_domains),
        proactive_allowed=contract.proactive_allowed,
        confirmation_required=contract.confirmation_required,
        input_schema=contract.input_schema, output_schema=contract.output_schema,
    ) for contract in SKILL_CONTRACTS.values()]


@app.post(
    "/api/v1/households/{household_id}/agent/runs/{run_id}/resume",
    response_model=AgentResumeResult,
)
def resume_agent_run(household_id: str, run_id: str, payload: AgentResumeInput,
                     x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    result = resume_paused_chat(db, auth, run_id, payload.confirmed)
    run_view = get_agent_run(household_id, run_id, x_household_key, db)
    message = result["message"]
    return AgentResumeResult(
        run=run_view,
        message=AgentMessageResult(message_id=message.id, role=message.role, content=message.content,
                                   created_at=message.created_at),
    )


@app.get("/api/v1/households/{household_id}/agent/status", response_model=AgentStatusResult)
def agent_status(household_id: str, x_household_key: str = Header(...),
                 db: Session = Depends(get_db)):
    authorize_household(db, household_id, x_household_key)
    return AgentStatusResult(
        provider="deepseek", model=settings.llm_model,
        configured=bool(settings.llm_api_key),
        proactive_enabled=settings.llm_proactive_enabled and bool(settings.llm_api_key),
        policy_version=POLICY_VERSION,
        worker_enabled=settings.inline_worker_enabled,
        worker_running=worker_runtime.running,
        worker_last_run_at=worker_runtime.last_run_at,
        worker_last_error=worker_runtime.last_error,
        worker_processed_total=worker_runtime.processed_total,
        skills=list(SKILLS),
        agents=["main_agent", "health_doctor", "life_coach", "household_steward"],
    )


def render_agent_profile(profile: AgentProfile) -> AgentProfileResult:
    return AgentProfileResult(
        member_id=profile.subject_member_id,
        scope="member" if profile.subject_member_id else "household",
        display_name=profile.display_name,
        tone=profile.soul.get("tone", "温柔、直接、不说教"),
        relationship_goal=profile.soul.get("relationship_goal", "长期理解身体节奏"),
        proactive_enabled=profile.proactive_enabled,
        daily_non_redline_limit=profile.daily_non_redline_limit,
        quiet_start=profile.quiet_start, quiet_end=profile.quiet_end,
        timezone=profile.timezone, version=profile.version, updated_at=profile.updated_at,
        explanation_basis=[
            "名称、语气和关系目标来自用户保存的 Soul 设置",
            "主动频率与静默时段来自该 Agent 的可见配置",
            "Soul 不会修改或覆盖原始传感观测",
        ],
    )


@app.get("/api/v1/households/{household_id}/agent/profiles/{scope_id}", response_model=AgentProfileResult)
def get_agent_profile(household_id: str, scope_id: str,
                      x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    member_id = None if scope_id == "household" else scope_id
    if member_id:
        authorize_member_view(db, auth, member_id)
        member = db.get(HouseholdMember, member_id)
        if auth.role != "owner" and (not member or member.linked_user_id != auth.user_id):
            raise HTTPException(status_code=403, detail={"code": "AGENT_SOUL_PRIVATE"})
    elif auth.role != "owner":
        raise HTTPException(status_code=403, detail={"code": "OWNER_REQUIRED"})
    return render_agent_profile(get_or_create_profile(db, household_id, member_id))


@app.put("/api/v1/households/{household_id}/agent/profiles/{scope_id}", response_model=AgentProfileResult)
def update_agent_profile(household_id: str, scope_id: str, payload: AgentProfileUpdate,
                         x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    member_id = None if scope_id == "household" else scope_id
    if member_id:
        authorize_member_view(db, auth, member_id)
        member = db.get(HouseholdMember, member_id)
        if auth.role != "owner" and (not member or member.linked_user_id != auth.user_id):
            raise HTTPException(status_code=403, detail={"code": "AGENT_SOUL_PRIVATE"})
    elif auth.role != "owner":
        raise HTTPException(status_code=403, detail={"code": "OWNER_REQUIRED"})
    profile = get_or_create_profile(db, household_id, member_id)
    profile.display_name = payload.display_name
    profile.soul = {"tone": payload.tone, "relationship_goal": payload.relationship_goal}
    profile.proactive_enabled = payload.proactive_enabled
    profile.quiet_start, profile.quiet_end = payload.quiet_start, payload.quiet_end
    profile.timezone = payload.timezone
    profile.version += 1
    profile.updated_by_user_id = auth.user_id
    profile.updated_at = datetime.now(timezone.utc)
    db.flush()
    db.add(AgentProfileRevision(
        profile_id=profile.id, household_id=household_id, subject_member_id=member_id,
        version=profile.version, snapshot=profile_snapshot(profile),
        changed_by_user_id=auth.user_id, change_reason="user_update",
        created_at=profile.updated_at,
    ))
    db.commit()
    db.refresh(profile)
    return render_agent_profile(profile)


@app.get(
    "/api/v1/households/{household_id}/agent/profiles/{scope_id}/history",
    response_model=list[AgentProfileRevisionResult],
)
def get_agent_profile_history(household_id: str, scope_id: str,
                              x_household_key: str = Header(...), db: Session = Depends(get_db)):
    # Reuse the exact same private-scope authorization as the current profile view.
    profile_view = get_agent_profile(household_id, scope_id, x_household_key, db)
    member_id = profile_view.member_id
    profile = db.scalar(select(AgentProfile).where(
        AgentProfile.household_id == household_id,
        AgentProfile.subject_member_id == member_id,
    ))
    rows = db.scalars(select(AgentProfileRevision).where(
        AgentProfileRevision.profile_id == profile.id
    ).order_by(AgentProfileRevision.version.desc())).all()
    return [AgentProfileRevisionResult(
        version=row.version, snapshot=row.snapshot,
        changed_by_user_id=row.changed_by_user_id, change_reason=row.change_reason,
        created_at=row.created_at,
    ) for row in rows]


def notification_is_visible(db: Session, notification: UserNotification, user_id: str) -> bool:
    if notification.recipient_user_id != user_id:
        return False
    action = db.get(AgentAction, notification.agent_action_id)
    if not action:
        return False
    if action.grant_id is not None:
        grant = db.get(FamilyGrant, action.grant_id)
        return bool(grant and grant.active and grant.status == "active" and grant.can_view
                    and grant.viewer_user_id == user_id)
    member = db.get(HouseholdMember, notification.subject_member_id)
    return bool(member and member.active and member.linked_user_id == user_id)


def render_notification(row: UserNotification) -> NotificationResult:
    return NotificationResult(
        notification_id=row.id, notification_type=row.notification_type,
        title=row.title, body=row.body, priority=row.priority, status=row.status,
        member_id=row.subject_member_id, authorization_basis=row.authorization_basis,
        created_at=row.created_at, read_at=row.read_at,
        acknowledged_at=row.acknowledged_at,
    )


@app.get(
    "/api/v1/households/{household_id}/notifications",
    response_model=list[NotificationResult],
)
def list_notifications(household_id: str, notification_status: str | None = None,
                       x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    query = select(UserNotification).where(
        UserNotification.household_id == household_id,
        UserNotification.recipient_user_id == auth.user_id,
    )
    if notification_status:
        query = query.where(UserNotification.status == notification_status)
    rows = db.scalars(query.order_by(UserNotification.created_at.desc()).limit(50)).all()
    return [render_notification(row) for row in rows if notification_is_visible(db, row, auth.user_id)]


def update_notification_status(db: Session, household_id: str, notification_id: int,
                               user_id: str, target: str) -> NotificationResult:
    row = db.get(UserNotification, notification_id)
    if not row or row.household_id != household_id or not notification_is_visible(db, row, user_id):
        raise HTTPException(status_code=404, detail={"code": "NOTIFICATION_NOT_FOUND"})
    now = datetime.now(timezone.utc)
    if target == "read":
        if row.status == "unread":
            row.status = "read"
        row.read_at = row.read_at or now
    else:
        row.status = "acknowledged"
        row.read_at = row.read_at or now
        row.acknowledged_at = row.acknowledged_at or now
    db.commit()
    db.refresh(row)
    return render_notification(row)


@app.post(
    "/api/v1/households/{household_id}/notifications/{notification_id}/read",
    response_model=NotificationResult,
)
def mark_notification_read(household_id: str, notification_id: int,
                           x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return update_notification_status(db, household_id, notification_id, auth.user_id, "read")


@app.post(
    "/api/v1/households/{household_id}/notifications/{notification_id}/acknowledge",
    response_model=NotificationResult,
)
def acknowledge_notification(household_id: str, notification_id: int,
                             x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return update_notification_status(db, household_id, notification_id, auth.user_id, "acknowledged")


@app.get(
    "/api/v1/households/{household_id}/agent/conversations",
    response_model=list[AgentConversationSummary],
)
def list_conversations(household_id: str, member_id: str,
                       x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    authorize_member_view(db, auth, member_id)
    rows = db.scalars(select(AgentConversation).where(
        AgentConversation.household_id == household_id,
        AgentConversation.subject_member_id == member_id,
        AgentConversation.created_by_user_id == auth.user_id,
        AgentConversation.status == "active",
    ).order_by(AgentConversation.updated_at.desc()).limit(20)).all()
    return [AgentConversationSummary(
        conversation_id=item.id, member_id=item.subject_member_id,
        updated_at=item.updated_at,
    ) for item in rows]


@app.get(
    "/api/v1/households/{household_id}/agent/actions",
    response_model=list[AgentActionResult],
)
def list_agent_actions(household_id: str, limit: int = 20,
                       x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    limit = min(max(limit, 1), 100)
    rows = db.scalars(select(AgentAction).where(
        AgentAction.recipient_id == auth.user_id,
    ).order_by(AgentAction.created_at.desc()).limit(limit)).all()
    return [AgentActionResult(
        action_id=item.id, action_type=item.action_type, status=item.status,
        member_id=item.subject_member_id, authorization_basis=item.authorization_basis,
        model_version=item.model_version, result=item.result, created_at=item.created_at,
        processed_at=item.processed_at,
    ) for item in rows]


def render_memory(item: AgentMemoryEntry) -> MemoryResult:
    return MemoryResult(
        memory_id=item.id, logical_id=item.logical_id,
        member_id=item.subject_member_id, version=item.version,
        source_type=item.source_type, memory_key=item.memory_key,
        content=item.content, editable=item.source_type != "sensor_fact",
        correction_reason=item.correction_reason, created_at=item.created_at,
    )


@app.get(
    "/api/v1/households/{household_id}/members/{member_id}/memory",
    response_model=list[MemoryResult],
)
def member_memory(household_id: str, member_id: str, include_history: bool = False,
                  x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return [render_memory(item) for item in list_memory(db, auth, member_id, include_history)]


@app.get(
    "/api/v1/households/{household_id}/members/{member_id}/health-profile",
    response_model=HealthProfileResult,
)
def read_health_profile(household_id: str, member_id: str,
                        x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return HealthProfileResult(**get_health_profile(db, auth, member_id))


@app.put(
    "/api/v1/households/{household_id}/members/{member_id}/health-profile",
    response_model=HealthProfileResult,
)
def update_health_profile(household_id: str, member_id: str, payload: HealthProfileInput,
                          x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return HealthProfileResult(**save_health_profile(db, auth, member_id, payload))


@app.put(
    "/api/v1/households/{household_id}/agent/messages/{message_id}/feedback",
    response_model=AgentFeedbackResult,
)
def rate_agent_message(household_id: str, message_id: int, payload: AgentFeedbackInput,
                       x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    message = db.get(AgentMessage, message_id)
    conversation = db.get(AgentConversation, message.conversation_id) if message else None
    if (not message or message.role != "assistant" or not conversation
            or conversation.household_id != household_id
            or conversation.created_by_user_id != auth.user_id):
        raise HTTPException(status_code=404, detail={"code": "AGENT_MESSAGE_NOT_FOUND"})
    authorize_member_view(db, auth, conversation.subject_member_id)
    now = datetime.now(timezone.utc)
    feedback = db.scalar(select(AgentFeedback).where(
        AgentFeedback.message_id == message_id,
        AgentFeedback.created_by_user_id == auth.user_id,
    ))
    if feedback:
        feedback.rating, feedback.reason, feedback.updated_at = payload.rating, payload.reason, now
    else:
        feedback = AgentFeedback(
            message_id=message_id, household_id=household_id,
            subject_member_id=conversation.subject_member_id,
            created_by_user_id=auth.user_id, rating=payload.rating,
            reason=payload.reason, created_at=now, updated_at=now,
        )
        db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return AgentFeedbackResult(
        feedback_id=feedback.id, message_id=feedback.message_id,
        rating=feedback.rating, reason=feedback.reason, updated_at=feedback.updated_at,
    )


@app.post(
    "/api/v1/households/{household_id}/members/{member_id}/memory",
    response_model=MemoryResult,
)
def add_member_memory(household_id: str, member_id: str, payload: MemoryCreateInput,
                      x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return render_memory(create_self_report(db, auth, member_id, payload))


@app.put(
    "/api/v1/households/{household_id}/members/{member_id}/memory/{logical_id}",
    response_model=MemoryResult,
)
def revise_member_memory(household_id: str, member_id: str, logical_id: str,
                         payload: MemoryUpdateInput, x_household_key: str = Header(...),
                         db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return render_memory(update_memory(db, auth, member_id, logical_id, payload))


@app.get(
    "/api/v1/households/{household_id}/agent/conversations/{conversation_id}",
    response_model=AgentConversationResult,
)
def conversation_history(household_id: str, conversation_id: str,
                         x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation or conversation.household_id != household_id or conversation.created_by_user_id != auth.user_id:
        raise HTTPException(status_code=404, detail={"code": "CONVERSATION_NOT_FOUND"})
    authorize_member_view(db, auth, conversation.subject_member_id)
    messages = db.scalars(select(AgentMessage).where(
        AgentMessage.conversation_id == conversation_id
    ).order_by(AgentMessage.id)).all()
    return AgentConversationResult(
        conversation_id=conversation.id, member_id=conversation.subject_member_id,
        messages=[AgentMessageResult(message_id=m.id, role=m.role, content=m.content, created_at=m.created_at)
                  for m in messages],
    )


@app.get(
    "/api/v1/households/{household_id}/members/{member_id}/sessions",
    response_model=list[MemberSessionResult],
)
def member_sessions(household_id: str, member_id: str,
                    x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    authorize_member_view(db, auth, member_id)
    rows = db.execute(
        select(SessionRecord, MemberAssignment, Assessment)
        .join(MemberAssignment, MemberAssignment.session_id == SessionRecord.id)
        .join(Assessment, Assessment.session_id == SessionRecord.id)
        .where(
            SessionRecord.household_id == household_id,
            MemberAssignment.active.is_(True),
            MemberAssignment.assignment_status == "confirmed",
            MemberAssignment.member_id == member_id,
            Assessment.active.is_(True),
        )
        .order_by(SessionRecord.occurred_at.desc())
        .limit(50)
    ).all()
    observations_by_session: dict[int, dict[str, Observation]] = {}
    if rows:
        record_ids = [record.id for record, _, _ in rows]
        observations = db.scalars(select(Observation).where(Observation.session_id.in_(record_ids))).all()
        for observation in observations:
            observations_by_session.setdefault(observation.session_id, {})[observation.dimension] = observation

    shape_variants = {
        "compact": "compact",
        "elongated": "elongated",
        "scattered": "scattered",
        "irregular": "irregular",
        "normal": "elongated",
        "hard": "scattered",
        "loose": "irregular",
    }

    def render_visual_dimension(observation: Observation | None) -> PoopVisualDimension | None:
        if not observation or observation.value is None or observation.confidence is None:
            return None
        return PoopVisualDimension(
            value=observation.value,
            confidence=observation.confidence,
            source=observation.source,
            model_version=observation.model_version,
        )

    results: list[MemberSessionResult] = []
    for record, assignment, assessment in rows:
        evidence = observations_by_session.get(record.id, {})
        shape = evidence.get("shape")
        variant = shape_variants.get(shape.value if shape else "", "uncertain")
        reliable_visual = assessment.reliable and variant != "uncertain"
        results.append(MemberSessionResult(
            session_id=record.external_session_id, occurred_at=record.occurred_at,
            assignment_version=assignment.version, assessment_status=assessment.status,
            risk_level=assessment.risk_level, message=assessment.message,
            visual_profile=PoopVisualProfile(
                variant=variant if reliable_visual else "uncertain",
                reliable=reliable_visual,
                shape=render_visual_dimension(shape) if reliable_visual else None,
                color=render_visual_dimension(evidence.get("color")) if reliable_visual else None,
                odor=render_visual_dimension(evidence.get("odor")) if reliable_visual else None,
            ),
        ))
    return results


@app.get(
    "/api/v1/households/{household_id}/members/{member_id}/pet",
    response_model=PetSnapshotResult,
)
def get_pet(household_id: str, member_id: str,
            x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return PetSnapshotResult(**pet_snapshot(db, auth, member_id))


@app.post(
    "/api/v1/households/{household_id}/members/{member_id}/pet/check-in",
    response_model=PetCheckinResult,
)
def check_in_pet(household_id: str, member_id: str,
                 x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    duplicate, snapshot = pet_check_in(db, auth, member_id)
    return PetCheckinResult(duplicate=duplicate, pet=PetSnapshotResult(**snapshot))


@app.put(
    "/api/v1/households/{household_id}/members/{member_id}/pet",
    response_model=PetSnapshotResult,
)
def revise_pet(household_id: str, member_id: str, payload: PetProfileUpdate,
               x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key)
    return PetSnapshotResult(**update_pet_profile(
        db, auth, member_id, payload.name, payload.selected_skin,
    ))


@app.get("/api/v1/households/{household_id}/community/posts", response_model=list[CommunityPostResult])
def community_posts(household_id: str, limit: int = 20,
                    db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return [CommunityPostResult(**item) for item in list_community_posts(db, auth, limit)]


@app.post("/api/v1/households/{household_id}/community/posts", response_model=CommunityPostResult)
def create_community_post(household_id: str, payload: CommunityPostInput,
                          db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return CommunityPostResult(**publish_community_post(
        db, auth, payload.member_id, payload.topic, payload.content,
    ))


@app.post("/api/v1/households/{household_id}/community/posts/{post_id}/withdraw", response_model=CommunityPostResult)
def remove_community_post(household_id: str, post_id: str,
                          db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return CommunityPostResult(**withdraw_community_post(db, auth, post_id))


@app.get("/api/v1/households/{household_id}/members/{member_id}/agent-connections", response_model=list[AgentConnectionResult])
def agent_connections(household_id: str, member_id: str, db: Session = Depends(get_db),
                      x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return [AgentConnectionResult(**item) for item in list_agent_matches(db, auth, member_id)]


@app.post("/api/v1/households/{household_id}/agent-connections", response_model=AgentConnectionResult)
def request_agent_connection(household_id: str, payload: AgentConnectionCreateInput,
                             db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return AgentConnectionResult(**create_agent_match(
        db, auth, payload.initiator_member_id, payload.target_post_id,
    ))


@app.post("/api/v1/households/{household_id}/agent-connections/{connection_id}/respond", response_model=AgentConnectionResult)
def answer_agent_connection(household_id: str, connection_id: str, payload: AgentConnectionRespondInput,
                            db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return AgentConnectionResult(**respond_agent_match(db, auth, connection_id, payload.member_id, payload.accept))


@app.post("/api/v1/households/{household_id}/agent-connections/{connection_id}/end", response_model=AgentConnectionResult)
def close_agent_connection(household_id: str, connection_id: str, member_id: str,
                           db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return AgentConnectionResult(**end_agent_match(db, auth, connection_id, member_id))


@app.get("/api/v1/households/{household_id}/members/{member_id}/weekly-reports", response_model=list[WeeklyHealthReportResult])
def weekly_reports(household_id: str, member_id: str, db: Session = Depends(get_db),
                   x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return [WeeklyHealthReportResult(**item) for item in list_weekly_reports(db, auth, member_id)]


@app.post("/api/v1/households/{household_id}/members/{member_id}/weekly-reports", response_model=WeeklyHealthReportResult)
def create_weekly_report(household_id: str, member_id: str, db: Session = Depends(get_db),
                         x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return WeeklyHealthReportResult(**generate_weekly_report(db, auth, member_id))


@app.get("/api/v1/households/{household_id}/raw-data-authorizations", response_model=list[RawDataAuthorizationResult])
def raw_data_authorizations(household_id: str, db: Session = Depends(get_db),
                            x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return [RawDataAuthorizationResult(**item) for item in list_raw_authorizations(db, auth)]


@app.post("/api/v1/households/{household_id}/raw-data-authorizations", response_model=RawDataAuthorizationResult)
def grant_raw_data_upload(household_id: str, payload: RawDataAuthorizationInput,
                          db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return RawDataAuthorizationResult(**create_raw_authorization(db, auth, payload))


@app.delete("/api/v1/households/{household_id}/raw-data-authorizations/{authorization_id}", response_model=RawDataAuthorizationResult)
def withdraw_raw_data_upload(household_id: str, authorization_id: str,
                             db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return RawDataAuthorizationResult(**revoke_raw_authorization(db, auth, authorization_id))


@app.post("/api/v1/households/{household_id}/raw-data-authorizations/{authorization_id}/complete-deletion", response_model=RawDataAuthorizationResult)
def delete_raw_cloud_copies(household_id: str, authorization_id: str,
                            db: Session = Depends(get_db), x_household_key: str | None = Header(default=None)):
    auth = authorize_household(db, household_id, x_household_key)
    return RawDataAuthorizationResult(**complete_raw_deletion(db, auth, authorization_id))


@app.post(
    "/api/v1/households/{household_id}/members/{member_id}/grants",
    response_model=GrantResult,
)
def create_grant(household_id: str, member_id: str, payload: GrantInput,
                 x_household_key: str = Header(...), db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key, {"owner"})
    grant = grant_family_view(db, auth, member_id, payload)
    return GrantResult(
        grant_id=grant.id, household_id=grant.household_id,
        subject_member_id=grant.subject_member_id, viewer_user_id=grant.viewer_user_id,
        version=grant.version, status=grant.status, can_view=grant.can_view,
        redline_notifications=grant.redline_notifications,
    )


@app.delete(
    "/api/v1/households/{household_id}/grants/{grant_id}",
    response_model=RevokeResult,
)
def revoke_grant(household_id: str, grant_id: int, x_household_key: str = Header(...),
                 db: Session = Depends(get_db)):
    auth = authorize_household(db, household_id, x_household_key, {"owner"})
    grant, cancelled = revoke_family_view(db, auth, grant_id)
    return RevokeResult(grant_id=grant.id, status=grant.status, cancelled_actions=cancelled)
