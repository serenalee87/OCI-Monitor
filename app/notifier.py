import json
import logging
import httpx
from typing import Dict, Any, List
from .config import settings

logger = logging.getLogger("oci-monitor")


async def send_webhook(title: str, content: str, data: Dict[str, Any] = None):
    """Send notification via configured webhook."""
    if not settings.WEBHOOK_URL:
        logger.warning("Webhook URL not configured, skipping notification")
        return

    payload = _build_payload(title, content, data)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                settings.WEBHOOK_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            logger.info(f"Webhook sent: {title} -> {resp.status_code}")
    except Exception as e:
        logger.error(f"Webhook failed: {e}")


def _build_payload(title: str, content: str, data: Dict[str, Any] = None) -> Dict:
    """Build payload according to webhook type."""
    extra = {"data": data} if data else {}

    if settings.WEBHOOK_TYPE == "wecom":
        # 企业微信机器人
        return {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### 🚨 {title}\n\n{content}"
            },
        }

    elif settings.WEBHOOK_TYPE == "feishu":
        # 飞书机器人
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"🚨 {title}"},
                    "template": "red",
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                ],
            },
        }

    elif settings.WEBHOOK_TYPE == "dingtalk":
        # 钉钉机器人
        return {
            "msgtype": "markdown",
            "markdown": {
                "title": f"🚨 {title}",
                "text": f"### 🚨 {title}\n\n{content}",
            },
        }

    else:
        # 自定义 Webhook（通用 JSON）
        return {
            "title": title,
            "content": content,
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            **extra,
        }


async def send_instance_status_alert(changes: List[Dict]):
    """Send instance status change notifications."""
    if not settings.NOTIFY_INSTANCE_STATUS or not changes:
        return

    for change in changes:
        status_emoji = {
            "RUNNING": "🟢",
            "STOPPED": "🔴",
            "TERMINATED": "⚠️",
            "PROVISIONING": "🟡",
        }.get(change["new_status"], "⚪")

        title = f"实例状态变更: {change['instance_name']}"
        content = (
            f"**实例**: {change['instance_name']}\n"
            f"**Compartment**: {change['compartment']}\n"
            f"**状态**: {status_emoji} {change['old_status']} → **{change['new_status']}**\n"
            f"**时间**: {change['time']}"
        )
        await send_webhook(title, content, change)


async def send_resource_alert(alerts: List[Dict]):
    """Send resource threshold alerts."""
    if not settings.NOTIFY_RESOURCE_ALERT or not alerts:
        return

    for alert in alerts:
        title = f"{alert['type']} 告警: {alert['instance_name']}"
        content = (
            f"**实例**: {alert['instance_name']}\n"
            f"**指标**: {alert['type']} 使用率\n"
            f"**当前值**: {alert['value']}%\n"
            f"**阈值**: {alert['threshold']}%\n"
            f"**严重程度**: {alert['severity'].upper()}"
        )
        await send_webhook(title, content, alert)


async def send_budget_alert(warnings: List[Dict]):
    """Send budget/cost alerts."""
    if not settings.NOTIFY_BILLING or not warnings:
        return

    for w in warnings:
        title = f"预算告警: {w['budget_name']}"
        content = (
            f"**预算**: {w['budget_name']}\n"
            f"**预算上限**: ${w['amount']:.2f}\n"
            f"**已花费**: ${w['actual_spend']:.2f}\n"
            f"**使用率**: {w['percentage']}%\n"
            f"**严重程度**: {w['severity'].upper()}"
        )
        await send_webhook(title, content, w)


async def send_free_tier_alert(warnings: List[Dict]):
    """Send free tier compliance alerts."""
    if not warnings:
        return

    for w in warnings:
        title = f"⚠️ 免费套餐超标: {w['type']}"
        content = (
            f"**告警类型**: {w['type']}\n"
            f"**详情**: {w['message']}\n"
            f"**严重程度**: {w['severity'].upper()}\n\n"
            f"---\n"
            f"请检查你的实例配置，确保不超过 Always Free 套餐限制，避免产生额外费用。"
        )
        await send_webhook(title, content, w)


async def send_charge_alert(warnings: List[Dict]):
    """🚨 最关键的告警：检测到费用产生。Always Free 用户不应该有任何花费。"""
    if not warnings:
        return

    for w in warnings:
        is_new = w.get("is_new_charge", False)
        last_spend = w.get("last_known_spend", 0) or 0
        status_text = "🆕 首次检测到费用" if is_new else f"📈 花费变动（上次: ${last_spend:.2f}）"
        title = f"🚨 费用告警: 检测到非零花费！"
        content = (
            f"**⚠️ 重要**: 你的 OCI 账户产生了费用！\n\n"
            f"**预算**: {w['budget_name']}\n"
            f"**当前花费**: ${w['actual_spend']:.2f}\n"
            f"**状态**: {status_text}\n\n"
            f"---\n"
            f"**⚡ 建议立即检查**：\n"
            f"1. 登录 OCI 控制台查看账单详情\n"
            f"2. 检查实例是否超出免费套餐配额\n"
            f"3. 如需降配，请立即操作避免费用继续累积\n\n"
            f"面板地址: 请登录 OCI 控制台 > Billing > Cost Analysis"
        )
        await send_webhook(title, content, w)
