"""Member7 invite login, server-side sessions and per-invite task allowances.

No model imports, API credentials, or changes to native Agent decisions.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from task_manager import TaskError

COOKIE = "contract_workbench_session"
SESSION_SECONDS = 8 * 60 * 60


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_code(value):
    return re.sub(r"[\s-]", "", value).upper()


class AccessControl:
    def __init__(self, directory):
        self.path = Path(directory) / "access.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS invites (
                  id TEXT PRIMARY KEY, code_digest TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                  role TEXT NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                  max_clauses INTEGER NOT NULL, daily_limit INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                  digest TEXT PRIMARY KEY, invite_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures (address TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS failure_address ON login_failures(address,at);
                CREATE TABLE IF NOT EXISTS submissions (
                  invite_id TEXT NOT NULL, request_id TEXT NOT NULL, day TEXT NOT NULL,
                  status TEXT NOT NULL, task_id TEXT,
                  PRIMARY KEY(invite_id,request_id));
                CREATE TABLE IF NOT EXISTS public_reports (id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT);
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def today():
        return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    def seed_public(self, report_ids):
        # Snapshot legacy classroom reports once. Future uploads are private by default.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM settings WHERE name='public_seeded'").fetchone():
                db.executemany("INSERT OR IGNORE INTO public_reports(id) VALUES(?)", [(key,) for key in report_ids])
                db.execute("INSERT INTO settings VALUES('public_seeded','1')")
            db.commit()

    def public_ids(self):
        with self.db() as db:
            return {row[0] for row in db.execute("SELECT id FROM public_reports")}

    def create_invite(self, name, role="member", days=7, max_clauses=None, daily_limit=None):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or role not in ("member", "admin"):
            raise ValueError("名称须为1–60个字符，角色须为member或admin")
        max_clauses = max_clauses if max_clauses is not None else (41 if role == "admin" else 5)
        daily_limit = daily_limit if daily_limit is not None else (20 if role == "admin" else 3)
        if not 1 <= days <= 365 or not 1 <= max_clauses <= 41 or not 1 <= daily_limit <= 100:
            raise ValueError("有效期1–365天，每次1–41类，每日1–100次")
        encoded = base64.b32encode(secrets.token_bytes(12)).decode().rstrip("=")
        code = "HQ-" + "-".join(encoded[i:i+5] for i in range(0, len(encoded), 5))
        identifier, at = uuid4().hex, time.time()
        with self.db() as db:
            db.execute("INSERT INTO invites VALUES(?,?,?,?,?,0,?,?,?)",
                       (identifier, fingerprint(canonical_code(code)), name.strip(), role,
                        at + days*86400, max_clauses, daily_limit, at))
        return {"id": identifier, "name": name.strip(), "role": role, "code": code,
                "max_clauses": max_clauses, "daily_limit": daily_limit, "days": days}

    def list_invites(self):
        with self.db() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,role,expires,revoked,max_clauses,daily_limit FROM invites ORDER BY created")]

    def revoke(self, identifier):
        with self.db() as db:
            changed = db.execute("UPDATE invites SET revoked=1 WHERE id=?", (identifier,)).rowcount
            db.execute("DELETE FROM sessions WHERE invite_id=?", (identifier,))
        return bool(changed)

    def login(self, code, address):
        at, address_hash = time.time(), fingerprint(address)
        if not isinstance(code, str) or len(code) > 128:
            code = ""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_failures WHERE at<?", (at-900,))
            failures = db.execute("SELECT COUNT(*) FROM login_failures WHERE address=?", (address_hash,)).fetchone()[0]
            if failures >= 8:
                db.commit()
                raise TaskError("该地址登录失败次数过多，请15分钟后重试", 429)
            row = db.execute("SELECT * FROM invites WHERE code_digest=? AND revoked=0 AND expires>?",
                             (fingerprint(canonical_code(code)), at)).fetchone()
            if not row:
                db.execute("INSERT INTO login_failures VALUES(?,?)", (address_hash, at))
                db.commit()
                raise TaskError("邀请码无效、已过期或已撤销，请联系管理员", 401)
            sid = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<?", (at,))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (fingerprint(sid), row["id"], at+SESSION_SECONDS))
            db.commit()
        return sid

    def principal(self, sid):
        if not sid or len(sid) > 128:
            return None
        at = time.time()
        with self.db() as db:
            row = db.execute("""SELECT i.id,i.name,i.role,i.max_clauses,i.daily_limit,s.expires AS session_expires
                FROM sessions s JOIN invites i ON s.invite_id=i.id
                WHERE s.digest=? AND s.expires>? AND i.expires>? AND i.revoked=0""",
                             (fingerprint(sid), at, at)).fetchone()
        return dict(row) if row else None

    def logout(self, sid):
        if sid:
            with self.db() as db:
                db.execute("DELETE FROM sessions WHERE digest=?", (fingerprint(sid),))

    def status(self, principal):
        if not principal:
            return {"authenticated": False, "login_method": "invite", "session_hours": 8}
        with self.db() as db:
            used = db.execute("SELECT COUNT(*) FROM submissions WHERE invite_id=? AND day=?",
                              (principal["id"], self.today())).fetchone()[0]
        return {"authenticated": True, "id": principal["id"], "display_name": principal["name"],
                "role": principal["role"], "max_clauses": principal["max_clauses"],
                "daily_limit": principal["daily_limit"], "used_today": used,
                "remaining_today": max(0, principal["daily_limit"]-used), "session_hours": 8}

    def reserve(self, principal, form):
        request_id = form.get("request_id", "")
        if not re.fullmatch(r"[a-f0-9-]{32,36}", request_id):
            raise TaskError("缺少有效请求标识，请刷新页面后提交")
        try:
            clauses = json.loads(form.get("clauses", "[]"))
        except (ValueError, TypeError):
            raise TaskError("条款格式无效") from None
        if not isinstance(clauses, list) or not clauses:
            raise TaskError("请至少选择一个条款")
        if len(clauses) > principal["max_clauses"]:
            raise TaskError(f"当前邀请码每次最多审查{principal['max_clauses']}类，请减少选择或联系管理员", 403)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM submissions WHERE invite_id=? AND request_id=?",
                               (principal["id"], request_id)).fetchone()
            if prior:
                db.commit()
                if prior["status"] == "RESERVED":
                    raise TaskError("同一请求正在提交，请稍后读取原任务", 409)
                return False
            used = db.execute("SELECT COUNT(*) FROM submissions WHERE invite_id=? AND day=?",
                              (principal["id"], self.today())).fetchone()[0]
            if used >= principal["daily_limit"]:
                db.commit()
                raise TaskError("今日任务额度已用完；北京时间零点恢复，历史回放不受影响", 429)
            db.execute("INSERT INTO submissions VALUES(?,?,?,'RESERVED',NULL)",
                       (principal["id"], request_id, self.today()))
            db.commit()
        return True

    def finish(self, principal, request_id, task_id):
        with self.db() as db:
            db.execute("UPDATE submissions SET status='CREATED',task_id=? WHERE invite_id=? AND request_id=?",
                       (task_id, principal["id"], request_id))

    def release(self, principal, request_id):
        with self.db() as db:
            db.execute("DELETE FROM submissions WHERE invite_id=? AND request_id=? AND status='RESERVED'",
                       (principal["id"], request_id))
