import os
from dataclasses import dataclass
from pathlib import Path


def _load_local_env() -> None:
    """Load developer-only secrets without overriding real environment variables."""
    path = Path(__file__).resolve().parents[1] / ".env.local"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "POOPSENSE_DATABASE_URL", "sqlite:///./poopsense-local.db"
    )
    reliable_confidence_threshold: float = float(
        os.getenv("POOPSENSE_RELIABLE_CONFIDENCE_THRESHOLD", "0.70")
    )
    bootstrap_demo_device: bool = os.getenv(
        "POOPSENSE_BOOTSTRAP_DEMO_DEVICE", "true"
    ).lower() in {"1", "true", "yes"}
    bootstrap_demo_data: bool = os.getenv(
        "POOPSENSE_BOOTSTRAP_DEMO_DATA", "true"
    ).lower() in {"1", "true", "yes"}
    auto_create_schema: bool = os.getenv(
        "POOPSENSE_AUTO_CREATE_SCHEMA", "true"
    ).lower() in {"1", "true", "yes"}
    outbox_max_attempts: int = int(os.getenv("POOPSENSE_OUTBOX_MAX_ATTEMPTS", "3"))
    outbox_retry_base_seconds: int = int(
        os.getenv("POOPSENSE_OUTBOX_RETRY_BASE_SECONDS", "5")
    )
    outbox_lease_seconds: int = int(os.getenv("POOPSENSE_OUTBOX_LEASE_SECONDS", "60"))
    inline_worker_enabled: bool = os.getenv(
        "POOPSENSE_INLINE_WORKER_ENABLED", "true"
    ).lower() in {"1", "true", "yes"}
    inline_worker_poll_seconds: float = float(
        os.getenv("POOPSENSE_INLINE_WORKER_POLL_SECONDS", "1")
    )
    inline_worker_batch_size: int = int(
        os.getenv("POOPSENSE_INLINE_WORKER_BATCH_SIZE", "20")
    )
    llm_api_key: str = os.getenv(
        "POOPSENSE_LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")
    )
    llm_base_url: str = os.getenv("POOPSENSE_LLM_BASE_URL", "https://api.deepseek.com")
    llm_model: str = os.getenv("POOPSENSE_LLM_MODEL", "deepseek-v4-pro")
    llm_timeout_seconds: float = float(os.getenv("POOPSENSE_LLM_TIMEOUT_SECONDS", "30"))
    llm_proactive_enabled: bool = os.getenv(
        "POOPSENSE_LLM_PROACTIVE_ENABLED", "true"
    ).lower() in {"1", "true", "yes"}
    robot_host_url: str = os.getenv("POOPSENSE_ROBOT_HOST_URL", "http://localhost:5000")
    robot_timeout_seconds: float = float(os.getenv("POOPSENSE_ROBOT_TIMEOUT_SECONDS", "5"))
    robot_trajectory_path: str = os.getenv(
        "POOPSENSE_ROBOT_TRAJECTORY_PATH",
        str(Path(__file__).resolve().parents[1] / "robot_trajectories" / "deliver_water.json"),
    )
    vbot_bridge_enabled: bool = os.getenv(
        "POOPSENSE_VBOT_BRIDGE_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    vbot_bridge_url: str = os.getenv(
        "POOPSENSE_VBOT_BRIDGE_URL", "http://192.168.126.2:8765"
    )
    vbot_bridge_timeout_seconds: float = float(
        os.getenv("POOPSENSE_VBOT_BRIDGE_TIMEOUT_SECONDS", "5")
    )
    vbot_route_name: str = os.getenv(
        "POOPSENSE_VBOT_ROUTE_NAME", "poopsense_water_delivery"
    )
    vbot_route_timeout_seconds: float = float(
        os.getenv("POOPSENSE_VBOT_ROUTE_TIMEOUT_SECONDS", "180")
    )
    robot_handover_timeout_seconds: float = float(
        os.getenv("POOPSENSE_ROBOT_HANDOVER_TIMEOUT_SECONDS", "60")
    )
    cors_origins: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv(
            "POOPSENSE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",") if item.strip()
    )


settings = Settings()
