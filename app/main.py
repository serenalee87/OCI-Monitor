import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional

from app.config import settings
from app import database as db
from app.auth import (
    COOKIE_NAME, authenticate_user, create_session_token,
    verify_session_token, is_auth_required,
)
from app.scheduler import setup_scheduler, run_instance_check, run_billing_check
from app.monitors.freetier_monitor import check_free_tier_compliance
from app.notifier import send_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("oci-monitor")

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    await db.init_db()

    oci_ready = await _is_oci_ready()
    if oci_ready:
        scheduler = setup_scheduler(app)
        scheduler.start()
        logger.info("Scheduler started")
        try:
            await run_instance_check()
        except Exception as e:
            logger.error(f"Initial check failed: {e}")
    else:
        logger.warning("OCI not configured. Add accounts via the web panel.")
    yield
    if scheduler:
        scheduler.shutdown()


app = FastAPI(title="OCI Monitor", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Paths that do NOT require authentication
PUBLIC_PATHS = {"/login", "/favicon.ico"}


async def _is_oci_ready() -> bool:
    """Check if OCI is configured via .env OR has accounts in the database."""
    if settings.is_oci_configured():
        return True
    accounts = await db.get_accounts()
    return len(accounts) > 0

# Static asset prefixes to skip (for future CSS/JS if needed)
STATIC_PREFIXES = ("/static", "/assets")


def _get_current_user(request: Request) -> Optional[str]:
    """Extract and verify the session cookie, return username or None."""
    token = request.cookies.get(COOKIE_NAME)
    return verify_session_token(token)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Skip auth for public paths and static assets
    if path in PUBLIC_PATHS or any(path.startswith(p) for p in STATIC_PREFIXES):
        return await call_next(request)

    # If auth is not configured, allow everything (backward compatible)
    if not is_auth_required():
        return await call_next(request)

    # Check if user is authenticated
    user = _get_current_user(request)

    if user is None:
        # API routes return 401 JSON
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"error": "Authentication required"})
        # Page routes redirect to login
        return RedirectResponse(url="/login", status_code=302)

    # Attach username to request state for downstream use
    request.state.user = user
    return await call_next(request)


# ============ Auth Routes ============

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    # If already logged in, redirect to dashboard
    if _get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if not authenticate_user(username, password):
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid username or password",
        }, status_code=401)

    token = create_session_token(username)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=86400 * 7,  # 7 days
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True if using HTTPS behind reverse proxy
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# ============ Dashboard ============

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    instances = await db.get_instances()
    alerts = await db.get_recent_alerts(30)
    budgets = await db.get_budgets()
    accounts = await db.get_accounts()
    status_history = await db.get_status_history(20)

    billing_summary = {"total_spend": 0.0, "currency": "USD", "budgets": budgets, "last_check": None}
    if budgets:
        for b in budgets:
            if b.get("actual_spend"):
                billing_summary["total_spend"] += b["actual_spend"]
        billing_summary["last_check"] = budgets[0].get("last_check")
    else:
        billing_summary["note"] = "未设置预算监控，当前 Always Free 账户花费: $0.00"

    scheduler_status = None
    if scheduler:
        scheduler_status = [{"id": j.id, "name": j.name, "next_run": str(j.next_run_time) if j.next_run_time else None}
                           for j in scheduler.get_jobs()]

    oci_ready = await _is_oci_ready()

    return templates.TemplateResponse(request, "dashboard.html", {
        "instances": instances, "alerts": alerts, "budgets": budgets,
        "accounts": accounts, "billing_summary": billing_summary,
        "status_history": status_history, "scheduler_status": scheduler_status,
        "oci_configured": oci_ready,
        "webhook_configured": bool(settings.WEBHOOK_URL),
    })


# ============ Account Management ============

@app.get("/api/accounts")
async def api_get_accounts():
    return await db.get_accounts()


@app.post("/api/accounts")
async def api_add_account(request: Request):
    data = await request.json()
    required = ["name", "tenancy_ocid", "user_ocid", "fingerprint", "region", "key_file"]
    for field in required:
        if not data.get(field):
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    account_id = await db.save_account(
        data["name"], data["tenancy_ocid"], data["user_ocid"],
        data["fingerprint"], data["region"], data["key_file"],
    )
    return {"message": f"Account '{data['name']}' added", "id": account_id}


@app.delete("/api/accounts/{account_id}")
async def api_delete_account(account_id: int):
    await db.delete_account(account_id)
    return {"message": "Account deleted"}


# ============ API Endpoints ============

@app.get("/api/instances")
async def api_instances():
    return await db.get_instances()

@app.get("/api/alerts")
async def api_alerts(limit: int = 50):
    return await db.get_recent_alerts(limit)

@app.get("/api/budgets")
async def api_budgets():
    return await db.get_budgets()

@app.get("/api/status-history")
async def api_status_history(limit: int = 100):
    return await db.get_status_history(limit)

@app.post("/api/check/instances")
async def api_trigger_instance_check():
    await run_instance_check()
    return {"message": "Instance check triggered"}

@app.post("/api/check/billing")
async def api_trigger_billing_check():
    await run_billing_check()
    return {"message": "Billing check triggered"}

@app.post("/api/test-webhook")
async def api_test_webhook():
    await send_webhook("🔔 测试通知", "OCI Monitor Webhook 测试成功！", {"test": True})
    return {"message": "Test webhook sent"}

@app.get("/api/free-tier")
async def api_free_tier():
    from app.oci_client import create_client_from_account, oci_client as default_client
    accounts = await db.get_accounts()
    merged = {
        "compliant": True, "warnings": [], "instances": [],
        "totals": {"arm_ocpus": 0, "arm_memory_gb": 0, "amd_ocpus": 0, "amd_memory_gb": 0},
        "limits": {"arm": "2 OCPU / 12 GB", "amd": "1 OCPU / 1 GB"},
    }
    if accounts:
        for acc in accounts:
            if not acc["is_active"]:
                continue
            try:
                client = create_client_from_account(acc)
                r = await check_free_tier_compliance(client=client, account_id=acc["id"], account_name=acc["name"])
                merged["instances"].extend(r.get("instances", []))
                merged["warnings"].extend(r.get("warnings", []))
                for k in merged["totals"]:
                    merged["totals"][k] += r["totals"].get(k, 0)
                if not r.get("compliant", True):
                    merged["compliant"] = False
            except Exception as e:
                logger.error(f"Free tier check failed for {acc['name']}: {e}")
    else:
        r = await check_free_tier_compliance(client=default_client)
        merged["instances"] = r.get("instances", [])
        merged["warnings"] = r.get("warnings", [])
        merged["totals"] = r.get("totals", merged["totals"])
        merged["compliant"] = r.get("compliant", True)
    return merged

@app.post("/api/check/free-tier")
async def api_trigger_free_tier_check():
    result = await api_free_tier()
    return {"message": "Free tier check complete", "result": result}

@app.get("/api/config")
async def api_config():
    oci_ready = await _is_oci_ready()
    return {
        "oci_configured": oci_ready,
        "oci_region": settings.OCI_REGION,
        "webhook_configured": bool(settings.WEBHOOK_URL),
        "webhook_url": settings.WEBHOOK_URL,
        "webhook_type": settings.WEBHOOK_TYPE,
        "monitor_interval": settings.MONITOR_INTERVAL,
        "status_check_interval": settings.STATUS_CHECK_INTERVAL,
        "billing_check_interval": settings.BILLING_CHECK_INTERVAL,
        "thresholds": {"cpu": settings.ALERT_CPU_THRESHOLD, "memory": settings.ALERT_MEMORY_THRESHOLD,
                       "disk": settings.ALERT_DISK_THRESHOLD, "budget": settings.ALERT_BUDGET_LIMIT},
        "notify": {"instance_status": settings.NOTIFY_INSTANCE_STATUS,
                   "resource_alert": settings.NOTIFY_RESOURCE_ALERT, "billing": settings.NOTIFY_BILLING},
    }


@app.post("/api/settings")
async def api_update_settings(request: Request):
    global scheduler
    data = await request.json()
    updated = []

    if "monitor_interval" in data:
        val = max(60, int(data["monitor_interval"]))
        settings.MONITOR_INTERVAL = val
        updated.append(f"资源监控间隔: {val}秒")
        if scheduler:
            scheduler.reschedule_job("instance_check", trigger="interval", seconds=val)
    if "status_check_interval" in data:
        val = max(30, int(data["status_check_interval"]))
        settings.STATUS_CHECK_INTERVAL = val
        updated.append(f"状态检查间隔: {val}秒")
        if scheduler:
            scheduler.reschedule_job("status_check", trigger="interval", seconds=val)
    if "billing_check_interval" in data:
        val = max(300, int(data["billing_check_interval"]))
        settings.BILLING_CHECK_INTERVAL = val
        updated.append(f"账单检查间隔: {val}秒")
        if scheduler:
            scheduler.reschedule_job("billing_check", trigger="interval", seconds=val)
    if "alert_cpu_threshold" in data:
        settings.ALERT_CPU_THRESHOLD = int(data["alert_cpu_threshold"])
        updated.append(f"CPU: {settings.ALERT_CPU_THRESHOLD}%")
    if "alert_memory_threshold" in data:
        settings.ALERT_MEMORY_THRESHOLD = int(data["alert_memory_threshold"])
        updated.append(f"内存: {settings.ALERT_MEMORY_THRESHOLD}%")
    if "alert_disk_threshold" in data:
        settings.ALERT_DISK_THRESHOLD = int(data["alert_disk_threshold"])
        updated.append(f"磁盘: {settings.ALERT_DISK_THRESHOLD}%")
    if "notify_instance_status" in data:
        settings.NOTIFY_INSTANCE_STATUS = bool(data["notify_instance_status"])
    if "notify_resource_alert" in data:
        settings.NOTIFY_RESOURCE_ALERT = bool(data["notify_resource_alert"])
    if "notify_billing" in data:
        settings.NOTIFY_BILLING = bool(data["notify_billing"])
    if "webhook_url" in data:
        settings.WEBHOOK_URL = str(data["webhook_url"]).strip()
        updated.append(f"Webhook URL 已更新")
    if "webhook_type" in data:
        val = str(data["webhook_type"]).strip().lower()
        if val in ("custom", "wecom", "feishu", "dingtalk"):
            settings.WEBHOOK_TYPE = val
            updated.append(f"Webhook 类型: {val}")

    logger.info(f"Settings updated: {', '.join(updated)}")
    return {"message": "设置已更新", "updated": updated}
