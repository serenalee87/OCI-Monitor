import aiosqlite
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from .config import settings

logger = logging.getLogger("oci-monitor")


async def init_db():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS oci_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, tenancy_ocid TEXT NOT NULL, user_ocid TEXT NOT NULL,
                fingerprint TEXT NOT NULL, region TEXT NOT NULL, key_file TEXT NOT NULL,
                is_active INTEGER DEFAULT 1, created_at TEXT, last_check TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS instances (
                id TEXT PRIMARY KEY,
                name TEXT, status TEXT, compartment TEXT, shape TEXT, region TEXT,
                metrics_json TEXT, last_check TEXT, time_created TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT, title TEXT, content TEXT, severity TEXT,
                data_json TEXT, created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id TEXT PRIMARY KEY,
                display_name TEXT, amount REAL, actual_spend REAL,
                forecast_spend REAL, last_check TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT, instance_name TEXT,
                old_status TEXT, new_status TEXT, created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS spend_tracker (
                budget_id TEXT PRIMARY KEY,
                last_known_spend REAL, first_detected TEXT, last_checked TEXT
            )
        """)

        # === Migration: add new columns to existing tables ===
        migrations = [
            ("ALTER TABLE instances ADD COLUMN account_id INTEGER", []),
            ("ALTER TABLE instances ADD COLUMN account_name TEXT", []),
            ("ALTER TABLE budgets ADD COLUMN account_id INTEGER", []),
            ("ALTER TABLE budgets ADD COLUMN account_name TEXT", []),
            ("ALTER TABLE status_history ADD COLUMN account_name TEXT", []),
        ]
        for sql, params in migrations:
            try:
                await db.execute(sql, params)
            except Exception:
                pass  # Column already exists

        await db.commit()
    logger.info("Database initialized")


# ============ Account Management ============

async def save_account(name, tenancy_ocid, user_ocid, fingerprint, region, key_file) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO oci_accounts (name, tenancy_ocid, user_ocid, fingerprint, region, key_file, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, tenancy_ocid, user_ocid, fingerprint, region, key_file, now),
        )
        await db.commit()
        return cursor.lastrowid

async def get_accounts() -> List[Dict]:
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM oci_accounts ORDER BY id")
        return [dict(r) for r in await cursor.fetchall()]

async def get_account(account_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM oci_accounts WHERE id=?", (account_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def delete_account(account_id: int):
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("DELETE FROM oci_accounts WHERE id=?", (account_id,))
        await db.commit()

async def update_account_check(account_id: int):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("UPDATE oci_accounts SET last_check=? WHERE id=?", (now, account_id))
        await db.commit()


# ============ Data Operations ============

async def save_instances(instances, metrics_map, account_id=None, account_name=None):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        for inst in instances:
            metrics = metrics_map.get(inst["id"], {})
            await db.execute(
                """INSERT INTO instances (id,account_id,account_name,name,status,compartment,shape,region,metrics_json,last_check,time_created)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       account_id=excluded.account_id,account_name=excluded.account_name,
                       name=excluded.name,status=excluded.status,compartment=excluded.compartment,
                       shape=excluded.shape,region=excluded.region,metrics_json=excluded.metrics_json,
                       last_check=excluded.last_check""",
                (inst["id"], account_id, account_name, inst["name"], inst["status"],
                 inst["compartment"], inst["shape"], inst["region"],
                 json.dumps(metrics), now, inst.get("time_created")),
            )
        await db.commit()

async def save_alert(alert_type, title, content, severity, data=None):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute(
            "INSERT INTO alerts (alert_type,title,content,severity,data_json,created_at) VALUES (?,?,?,?,?,?)",
            (alert_type, title, content, severity, json.dumps(data or {}), now),
        )
        await db.commit()

async def save_status_change(instance_id, instance_name, old_status, new_status, account_name=None):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute(
            "INSERT INTO status_history (account_name,instance_id,instance_name,old_status,new_status,created_at) VALUES (?,?,?,?,?,?)",
            (account_name, instance_id, instance_name, old_status, new_status, now),
        )
        await db.commit()

async def save_budgets(budgets, account_id=None, account_name=None):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        for b in budgets:
            await db.execute(
                """INSERT INTO budgets (id,account_id,account_name,display_name,amount,actual_spend,forecast_spend,last_check)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       account_id=excluded.account_id,account_name=excluded.account_name,
                       display_name=excluded.display_name,amount=excluded.amount,
                       actual_spend=excluded.actual_spend,forecast_spend=excluded.forecast_spend,
                       last_check=excluded.last_check""",
                (b["id"], account_id, account_name, b["display_name"], b["amount"],
                 b.get("actual_spend"), b.get("forecast_spend"), now),
            )
        await db.commit()


# ============ Query Functions ============

async def get_instances():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM instances ORDER BY account_name, name")
        return [dict(r) for r in await cursor.fetchall()]

async def get_recent_alerts(limit=50):
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cursor.fetchall()]

async def get_status_history(limit=100):
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM status_history ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cursor.fetchall()]

async def get_budgets():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM budgets")
        return [dict(r) for r in await cursor.fetchall()]

async def get_last_known_spend(budget_id):
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cursor = await db.execute("SELECT last_known_spend FROM spend_tracker WHERE budget_id=?", (budget_id,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def save_known_spend(budget_id, spend):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute(
            """INSERT INTO spend_tracker (budget_id,last_known_spend,first_detected,last_checked)
               VALUES (?,?,?,?)
               ON CONFLICT(budget_id) DO UPDATE SET last_known_spend=excluded.last_known_spend,last_checked=excluded.last_checked""",
            (budget_id, spend, now, now),
        )
        await db.commit()
