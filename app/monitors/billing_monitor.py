import logging
from typing import List, Dict, Any
from app.oci_client import oci_client, OCIClient
from app.config import settings
from app import database as db

logger = logging.getLogger("oci-monitor")


async def get_budgets(client: OCIClient = None, account_id: int = None,
                      account_name: str = None) -> List[Dict[str, Any]]:
    if client is None:
        client = oci_client
    budgets = []
    try:
        tenancy = client.tenancy_ocid
        response = client.budget.list_budgets(compartment_id=tenancy)
        for b in response.data:
            budgets.append({
                "id": b.id,
                "display_name": b.display_name,
                "amount": b.amount,
                "budget_type": b.budget_type,
                "lifecycle_state": b.lifecycle_state,
                "actual_spend": getattr(b, "actual_spend", None),
                "forecast_spend": getattr(b, "forecast_spend", None),
                "time_created": b.time_created.isoformat() if b.time_created else None,
                "reset_period": getattr(b, "reset_period", None),
            })
    except Exception as e:
        logger.error(f"Failed to fetch budgets: {e}")
    return budgets


async def get_budget_alerts(client: OCIClient = None) -> List[Dict[str, Any]]:
    if client is None:
        client = oci_client
    alerts = []
    try:
        budgets = await get_budgets(client=client)
        for b in budgets:
            try:
                response = client.budget.list_alert_rules(budget_id=b["id"])
                for rule in response.data:
                    alerts.append({
                        "budget_id": b["id"],
                        "budget_name": b["display_name"],
                        "alert_rule_id": rule.id,
                        "display_name": rule.display_name,
                        "threshold": rule.threshold,
                        "threshold_type": rule.threshold_type,
                        "type": rule.type,
                        "message": rule.message,
                        "lifecycle_state": rule.lifecycle_state,
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch alert rules for budget {b['id']}: {e}")
    except Exception as e:
        logger.error(f"Failed to fetch budget alerts: {e}")
    return alerts


async def check_budget_alerts(client: OCIClient = None) -> List[Dict[str, Any]]:
    if client is None:
        client = oci_client
    warnings = []
    try:
        budgets = await get_budgets(client=client)
        for b in budgets:
            actual = b.get("actual_spend")
            amount = b.get("amount", 0)
            if actual and amount and amount > 0:
                pct = (actual / amount) * 100
                if pct >= 90:
                    warnings.append({
                        "budget_id": b["id"], "budget_name": b["display_name"],
                        "amount": amount, "actual_spend": actual,
                        "percentage": round(pct, 1),
                        "severity": "critical" if pct >= 100 else "warning",
                        "message": f"预算 {b['display_name']} 已使用 {pct:.1f}%（${actual:.2f} / ${amount:.2f}）",
                    })
    except Exception as e:
        logger.error(f"Budget check failed: {e}")
    return warnings


async def check_any_charge(client: OCIClient = None) -> List[Dict[str, Any]]:
    if client is None:
        client = oci_client
    warnings = []
    try:
        budgets = await get_budgets(client=client)
        for b in budgets:
            actual = b.get("actual_spend")
            if actual is not None and actual > 0:
                last_known = await db.get_last_known_spend(b["id"])
                warnings.append({
                    "budget_id": b["id"], "budget_name": b["display_name"],
                    "actual_spend": actual, "last_known_spend": last_known,
                    "severity": "critical",
                    "message": (
                        f"🚨 检测到费用！预算 [{b['display_name']}] "
                        f"当前花费: ${actual:.2f}"
                        f"（上次: ${last_known:.2f}）" if last_known and last_known > 0
                        else f"🚨 检测到费用！预算 [{b['display_name']}] 当前花费: ${actual:.2f}（首次检测到非零花费）"
                    ),
                    "is_new_charge": (last_known is None or last_known == 0),
                })
                await db.save_known_spend(b["id"], actual)
    except Exception as e:
        logger.error(f"Charge check failed: {e}")
    return warnings
