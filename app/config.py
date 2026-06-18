import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)


class Settings:
    # OCI Auth
    OCI_TENANCY_OCID: str = os.getenv("OCI_TENANCY_OCID", "")
    OCI_USER_OCID: str = os.getenv("OCI_USER_OCID", "")
    OCI_FINGERPRINT: str = os.getenv("OCI_FINGERPRINT", "")
    OCI_REGION: str = os.getenv("OCI_REGION", "ap-tokyo-1")
    OCI_KEY_FILE: str = os.getenv("OCI_KEY_FILE", "/app/config/oci_api_key.pem")

    # Webhook
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_TYPE: str = os.getenv("WEBHOOK_TYPE", "custom")  # custom/wecom/feishu/dingtalk

    # Monitor intervals (seconds)
    MONITOR_INTERVAL: int = int(os.getenv("MONITOR_INTERVAL", "300"))
    BILLING_CHECK_INTERVAL: int = int(os.getenv("BILLING_CHECK_INTERVAL", "3600"))
    STATUS_CHECK_INTERVAL: int = int(os.getenv("STATUS_CHECK_INTERVAL", "60"))

    # Alert thresholds
    ALERT_CPU_THRESHOLD: int = int(os.getenv("ALERT_CPU_THRESHOLD", "85"))
    ALERT_MEMORY_THRESHOLD: int = int(os.getenv("ALERT_MEMORY_THRESHOLD", "90"))
    ALERT_DISK_THRESHOLD: int = int(os.getenv("ALERT_DISK_THRESHOLD", "85"))
    ALERT_BUDGET_LIMIT: float = float(os.getenv("ALERT_BUDGET_LIMIT", "0"))

    # Web panel
    WEB_PORT: int = int(os.getenv("WEB_PORT", "8199"))
    WEB_USERNAME: str = os.getenv("WEB_USERNAME", "")
    WEB_PASSWORD: str = os.getenv("WEB_PASSWORD", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    # Notify controls
    NOTIFY_INSTANCE_STATUS: bool = os.getenv("NOTIFY_INSTANCE_STATUS", "true").lower() == "true"
    NOTIFY_RESOURCE_ALERT: bool = os.getenv("NOTIFY_RESOURCE_ALERT", "true").lower() == "true"
    NOTIFY_BILLING: bool = os.getenv("NOTIFY_BILLING", "true").lower() == "true"

    # Database
    DB_PATH: str = os.getenv("DB_PATH", "/app/data/monitor.db")

    @classmethod
    def is_oci_configured(cls) -> bool:
        return all([cls.OCI_TENANCY_OCID, cls.OCI_USER_OCID, cls.OCI_FINGERPRINT])


settings = Settings()
