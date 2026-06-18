import oci
import logging
from typing import Optional
from .config import settings

logger = logging.getLogger("oci-monitor")


class OCIClient:
    """Wrapper around OCI Python SDK clients — supports multiple accounts."""

    def __init__(self, account_config: dict = None):
        self._config = account_config
        self._compute_client = None
        self._monitoring_client = None
        self._budget_client = None
        self._identity_client = None
        self._ons_client = None

    def _get_config(self) -> dict:
        if self._config is None:
            if not settings.is_oci_configured():
                raise RuntimeError("OCI 未配置，请在 .env 或面板中配置账号")
            self._config = {
                "user": settings.OCI_USER_OCID,
                "fingerprint": settings.OCI_FINGERPRINT,
                "tenancy": settings.OCI_TENANCY_OCID,
                "region": settings.OCI_REGION,
                "key_file": settings.OCI_KEY_FILE,
            }
        return self._config

    @property
    def compute(self):
        if self._compute_client is None:
            self._compute_client = oci.core.ComputeClient(self._get_config())
        return self._compute_client

    @property
    def monitoring(self):
        if self._monitoring_client is None:
            self._monitoring_client = oci.monitoring.MonitoringClient(self._get_config())
        return self._monitoring_client

    @property
    def budget(self):
        if self._budget_client is None:
            self._budget_client = oci.budget.BudgetClient(self._get_config())
        return self._budget_client

    @property
    def identity(self):
        if self._identity_client is None:
            self._identity_client = oci.identity.IdentityClient(self._get_config())
        return self._identity_client

    @property
    def ons(self):
        if self._ons_client is None:
            self._ons_client = oci.ons.NotificationControlPlaneClient(self._get_config())
        return self._ons_client

    @property
    def tenancy_ocid(self) -> str:
        return self._get_config().get("tenancy", settings.OCI_TENANCY_OCID)

    @property
    def region(self) -> str:
        return self._get_config().get("region", settings.OCI_REGION)

    def list_compartments(self):
        try:
            response = self.identity.list_compartments(
                compartment_id=self.tenancy_ocid,
                compartment_id_in_subtree=True,
                lifecycle_state="ACTIVE",
            )
            return response.data
        except Exception as e:
            logger.error(f"Failed to list compartments: {e}")
            return []

    def list_instances(self, compartment_id: str):
        try:
            response = self.compute.list_instances(compartment_id=compartment_id)
            return response.data
        except Exception as e:
            logger.error(f"Failed to list instances in {compartment_id}: {e}")
            return []


def create_client_from_account(account: dict) -> OCIClient:
    """Create an OCI client from a database account record."""
    config = {
        "user": account["user_ocid"],
        "fingerprint": account["fingerprint"],
        "tenancy": account["tenancy_ocid"],
        "region": account["region"],
        "key_file": account["key_file"],
    }
    return OCIClient(config)


# Default singleton (fallback to .env)
oci_client = OCIClient()
