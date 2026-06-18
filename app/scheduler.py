import logging
from typing import Dict
from app.monitors.instance_monitor import get_all_instances, get_instance_metrics, check_instance_status_changes, check_resource_alerts
from app.monitors.billing_monitor import get_budgets, check_budget_alerts, check_any_charge
from app.monitors.freetier_monitor import check_free_tier_compliance
from app.notifier import send_instance_status_alert, send_resource_alert, send_budget_alert, send_charge_alert
from app.oci_client import create_client_from_account, oci_client
from app import database as db

logger = logging.getLogger("oci-monitor")

_previous_instance_states: Dict[str, str] = {}
_alerted_keys: set = set()


def _alert_key(alert_type: str, title: str) -> str:
    return f"{alert_type}:{title}"


async def run_instance_check():
    """Check instances across all configured accounts."""
    logger.info("Running instance check...")
    try:
        accounts = await db.get_accounts()

        if accounts:
            for acc in accounts:
                if not acc["is_active"]:
                    continue
                try:
                    client = create_client_from_account(acc)
                    instances = await get_all_instances(client=client, account_id=acc["id"], account_name=acc["name"])
                    if not instances:
                        continue

                    metrics_map = {}
                    for inst in instances:
                        if inst["status"] == "RUNNING":
                            m = await get_instance_metrics(inst["compartment_id"], inst["id"], client=client)
                            metrics_map[inst["id"]] = m

                    await db.save_instances(instances, metrics_map, account_id=acc["id"], account_name=acc["name"])
                    await db.update_account_check(acc["id"])

                    changes = await check_instance_status_changes(instances, _previous_instance_states)
                    if changes:
                        for change in changes:
                            await db.save_status_change(change["instance_id"], change["instance_name"],
                                                        change["old_status"], change["new_status"],
                                                        account_name=acc["name"])
                        await send_instance_status_alert(changes)

                    alerts = await check_resource_alerts(instances, metrics_map)
                    if alerts:
                        new_alerts = []
                        for a in alerts:
                            key = _alert_key("resource", f"{a['type']}: {a['instance_name']}")
                            if key not in _alerted_keys:
                                _alerted_keys.add(key)
                                await db.save_alert("resource", f"{a['type']} Alert: {a['instance_name']}",
                                                    f"{a['type']} at {a['value']}% (threshold: {a['threshold']}%)",
                                                    a["severity"], a)
                                new_alerts.append(a)
                        if new_alerts:
                            await send_resource_alert(new_alerts)

                    ft_result = await check_free_tier_compliance(client=client, account_id=acc["id"], account_name=acc["name"])
                    for w in ft_result.get("warnings", []):
                        if w["severity"] != "info":
                            key = _alert_key("free_tier", f"{acc['name']}:{w['type']}")
                            if key not in _alerted_keys:
                                _alerted_keys.add(key)
                                await db.save_alert("free_tier", f"[{acc['name']}] {w['type']}", w["message"], w["severity"], w)

                    logger.info(f"Account {acc['name']}: {len(instances)} instances")
                except Exception as e:
                    logger.error(f"Failed to check account {acc['name']}: {e}", exc_info=True)
        else:
            instances = await get_all_instances()
            if instances:
                metrics_map = {}
                for inst in instances:
                    if inst["status"] == "RUNNING":
                        m = await get_instance_metrics(inst["compartment_id"], inst["id"])
                        metrics_map[inst["id"]] = m
                await db.save_instances(instances, metrics_map)

                changes = await check_instance_status_changes(instances, _previous_instance_states)
                if changes:
                    for change in changes:
                        await db.save_status_change(change["instance_id"], change["instance_name"],
                                                    change["old_status"], change["new_status"])
                    await send_instance_status_alert(changes)

                alerts = await check_resource_alerts(instances, metrics_map)
                if alerts:
                    new_alerts = []
                    for a in alerts:
                        key = _alert_key("resource", f"{a['type']}: {a['instance_name']}")
                        if key not in _alerted_keys:
                            _alerted_keys.add(key)
                            await db.save_alert("resource", f"{a['type']} Alert: {a['instance_name']}",
                                                f"{a['type']} at {a['value']}%", a["severity"], a)
                            new_alerts.append(a)
                    if new_alerts:
                        await send_resource_alert(new_alerts)

                ft_result = await check_free_tier_compliance()
                for w in ft_result.get("warnings", []):
                    if w["severity"] != "info":
                        key = _alert_key("free_tier", w["type"])
                        if key not in _alerted_keys:
                            _alerted_keys.add(key)
                            await db.save_alert("free_tier", w["type"], w["message"], w["severity"], w)

                logger.info(f"Instance check complete: {len(instances)} instances")
    except Exception as e:
        logger.error(f"Instance check failed: {e}", exc_info=True)


async def run_billing_check():
    logger.info("Running billing check...")
    try:
        accounts = await db.get_accounts()
        if accounts:
            for acc in accounts:
                if not acc["is_active"]:
                    continue
                try:
                    client = create_client_from_account(acc)
                    budgets = await get_budgets(client=client, account_id=acc["id"], account_name=acc["name"])
                    if budgets:
                        await db.save_budgets(budgets, account_id=acc["id"], account_name=acc["name"])
                    charge_warnings = await check_any_charge(client=client)
                    if charge_warnings:
                        for w in charge_warnings:
                            await db.save_alert("charge", f"[{acc['name']}] 费用告警", w["message"], w["severity"], w)
                        await send_charge_alert(charge_warnings)
                    warnings = await check_budget_alerts(client=client)
                    if warnings:
                        for w in warnings:
                            await db.save_alert("budget", f"[{acc['name']}] {w['budget_name']}", w["message"], w["severity"], w)
                        await send_budget_alert(warnings)
                    logger.info(f"Billing: {acc['name']} — {len(budgets)} budgets")
                except Exception as e:
                    logger.error(f"Failed billing for {acc['name']}: {e}", exc_info=True)
        else:
            budgets = await get_budgets()
            if budgets:
                await db.save_budgets(budgets)
            charge_warnings = await check_any_charge()
            if charge_warnings:
                for w in charge_warnings:
                    await db.save_alert("charge", f"费用告警: {w['budget_name']}", w["message"], w["severity"], w)
                await send_charge_alert(charge_warnings)
            warnings = await check_budget_alerts()
            if warnings:
                for w in warnings:
                    await db.save_alert("budget", f"Budget Alert: {w['budget_name']}", w["message"], w["severity"], w)
                await send_budget_alert(warnings)
            logger.info(f"Billing check complete: {len(budgets)} budgets")
    except Exception as e:
        logger.error(f"Billing check failed: {e}", exc_info=True)


def setup_scheduler(app):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.config import settings

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_instance_check, "interval", seconds=settings.MONITOR_INTERVAL,
                      id="instance_check", name="实例资源监控", replace_existing=True)
    scheduler.add_job(run_instance_check, "interval", seconds=settings.STATUS_CHECK_INTERVAL,
                      id="status_check", name="实例状态检查", replace_existing=True)
    scheduler.add_job(run_billing_check, "interval", seconds=settings.BILLING_CHECK_INTERVAL,
                      id="billing_check", name="账单检查", replace_existing=True)
    return scheduler
