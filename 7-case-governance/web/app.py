"""Local workbench: native Agent subprocess jobs and real report playback."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import re
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
from flask import Flask, abort, g, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename
from report_store import ReportStore, REASON_NAMES, clean, digest
from task_manager import TaskManager, TaskError, MAX_UPLOAD
from access_control import AccessControl, COOKIE, SESSION_SECONDS
from sharing_network import lan_addresses

WEB = Path(__file__).resolve().parent


def create_app(data_dir=None, task_manager=None, offline=False, trusted_hosts=None, secure_cookie=False):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=MAX_UPLOAD + 1024 * 1024, JSON_AS_ASCII=False)
    app.json.ensure_ascii = False
    store = ReportStore()
    app.extensions["report_store"] = store
    directory = Path(data_dir) if data_dir else WEB / "data"
    access = AccessControl(directory / "access")
    app.extensions["access_control"] = access
    app.config["SECURE_LOGIN_COOKIE"] = bool(secure_cookie)
    tasks = task_manager or TaskManager()
    app.extensions["task_manager"] = tasks
    app.config["OFFLINE_PLAYBACK"] = bool(offline)
    app.config["ALLOW_LIVE_MODE_SWITCH"] = True
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    hosts = {"127.0.0.1", "localhost", "::1"} | {h.lower() for h in (trusted_hosts or [])}

    def owner_for(entry):
        path = entry["run_dir"] / "task.json"
        if path.is_file():
            return json.loads(path.read_bytes()).get("owner_id")
        return None

    access.seed_public([key for key, entry in store.entries.items() if not owner_for(entry)])

    def actor():
        if "actor" not in g:
            g.actor = access.principal(request.cookies.get(COOKIE))
        return g.actor

    def require_actor(admin=False):
        principal = actor()
        if not principal:
            raise TaskError("请先使用管理员发放的邀请码登录，再启动实时审查", 401)
        if admin and principal["role"] != "admin":
            raise TaskError("此操作需要管理员权限", 403)
        return principal

    def entry_visible(key):
        if key not in store.entries:
            return False
        principal = actor()
        owner = owner_for(store.entries[key])
        if principal and (principal["role"] == "admin" or principal["id"] == owner):
            return True
        return not owner and key in access.public_ids()

    def visible_reports():
        return [row for row in store.list() if entry_visible(row["id"])]

    def visible_task(task):
        principal, owner = actor(), task.get("owner_id")
        if principal and (principal["role"] == "admin" or principal["id"] == owner):
            return True
        return not owner and any(entry["run_dir"] == tasks.root / task["task_id"] and entry_visible(key)
                                 for key, entry in store.entries.items())

    def get_visible_task(task_id):
        task = tasks.status(task_id)
        if not visible_task(task):
            abort(404)
        return task

    @app.before_request
    def local_only():
        hostname = urlsplit("http://" + request.host).hostname
        if hostname not in hosts:
            abort(403)
        if request.method != "GET":
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                abort(403)
            if request.headers.get("X-Workbench-Token") != token:
                abort(403)

    @app.after_request
    def protect(response):
        response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin",
                                 "Cache-Control": "no-store" if request.path.startswith("/api") else "no-cache",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
        return response

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error(exc):
        return jsonify(error={400: "请求内容不符合要求", 403: "访问地址、来源或操作凭据不符合要求", 404: "未找到指定报告或接口", 413: "请求内容过大"}.get(exc.code, "请求失败")), exc.code

    @app.errorhandler(TaskError)
    def task_error(exc):
        return jsonify(error=str(exc)), exc.status

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/bootstrap")
    def bootstrap():
        store.refresh()
        offline_mode = app.config["OFFLINE_PLAYBACK"]
        principal = actor()
        return jsonify({**store.system(), "reports": visible_reports(), "review_token": token,
                        "offline_mode": offline_mode, "realtime_enabled": not offline_mode and bool(principal),
                        "model_api_calls_enabled": not offline_mode and bool(principal),
                        "can_enable_realtime": bool(app.config["ALLOW_LIVE_MODE_SWITCH"]) and bool(principal and principal["role"] == "admin"),
                        "access": access.status(principal),
                        "workspace_label": "小组共享工作区" if trusted_hosts else "本地工作区",
                        "audit_environment": bool(app.config.get("ISOLATED_AUDIT", False))})

    @app.post("/api/auth/login")
    def login():
        body = request.get_json(silent=True)
        sid = access.login(body.get("code") if isinstance(body, dict) else None, request.remote_addr or "unknown")
        response = jsonify(access=access.status(access.principal(sid)))
        response.set_cookie(COOKIE, sid, max_age=SESSION_SECONDS, httponly=True,
                            samesite="Lax", secure=app.config["SECURE_LOGIN_COOKIE"])
        return response

    @app.post("/api/auth/logout")
    def logout():
        access.logout(request.cookies.get(COOKIE))
        response = jsonify(logged_out=True)
        response.delete_cookie(COOKIE, httponly=True, samesite="Lax", secure=app.config["SECURE_LOGIN_COOKIE"])
        return response

    @app.post("/api/runtime/enable-realtime")
    def enable_realtime():
        # Local, token-protected opt-in only. This changes availability, never starts a task.
        if not app.config["ALLOW_LIVE_MODE_SWITCH"]:
            abort(403)
        require_actor(admin=True)
        app.config["OFFLINE_PLAYBACK"] = False
        return jsonify(offline_mode=False, realtime_enabled=True, model_api_calls_enabled=True)

    @app.get("/api/reports")
    def reports():
        store.refresh()
        return jsonify(reports=visible_reports())

    def task_view(task):
        folder = tasks.root / task["task_id"]
        store.refresh()
        task["report_id"] = next((key for key, entry in store.entries.items() if entry["run_dir"] == folder), None)
        return task

    @app.post("/api/tasks")
    def start_task():
        if app.config["OFFLINE_PLAYBACK"]:
            raise TaskError("当前为离线回放模式，后端已禁止新增模型审查；查看历史不消耗API额度", 503)
        principal = require_actor()
        if "file" not in request.files:
            raise TaskError("请选择PDF或TXT合同")
        reserved = access.reserve(principal, request.form)
        try:
            task, created = tasks.create(request.files["file"], request.form, store.clauses, owner_id=principal["id"])
        except BaseException:
            if reserved:
                access.release(principal, request.form.get("request_id"))
            raise
        access.finish(principal, request.form.get("request_id"), task["task_id"])
        return jsonify(task=task_view(task), duplicate=not created), 202 if created else 200

    @app.get("/api/tasks")
    def list_tasks():
        return jsonify(tasks=[task_view(task) for task in tasks.list() if visible_task(task)])

    @app.get("/api/tasks/<task_id>")
    def task_status(task_id):
        get_visible_task(task_id)
        try:
            after = int(request.args.get("after", "0"))
            if after < 0:
                raise ValueError
        except ValueError:
            raise TaskError("进度游标须为非负整数") from None
        return jsonify(task=task_view(tasks.status(task_id, after)))

    @app.post("/api/tasks/<task_id>/cancel")
    def stop_task(task_id):
        principal = require_actor()
        task = get_visible_task(task_id)
        if principal["role"] != "admin" and task.get("owner_id") != principal["id"]:
            abort(404)
        return jsonify(task=task_view(tasks.cancel(task_id)))

    def selected(key):
        if key in store.entries and not store.entries[key]["path"].is_file():
            store.refresh()
        if key not in store.entries:
            abort(404)
        if not entry_visible(key):
            abort(404)
        return store.get(key)

    @app.get("/api/reports/<key>")
    def report(key):
        return jsonify(selected(key))

    @app.get("/api/reports/<key>/text")
    def text(key):
        selected(key)
        return jsonify(store.text(key))

    @app.get("/api/reports/<key>/download")
    def download(key):
        selected(key)
        path = store.entries[key]["path"]
        original = path.read_text(encoding="utf-8")
        if clean(original) != original:
            return jsonify(error="原始文件可能含凭据信息，请先在本地检查；未向浏览器导出。"), 400
        return send_file(path, as_attachment=True, download_name=secure_filename(path.name), mimetype="application/json")

    @app.get("/print/<key>")
    def printable(key):
        return render_template("print.html", report=selected(key), reasons=REASON_NAMES,
                               back_url="/?report=" + key + "#/overview")

    def records(key):
        path = directory / "reviews" / (key + ".jsonl")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    @app.get("/api/reports/<key>/reviews")
    def get_reviews(key):
        selected(key)
        return jsonify(records=records(key))

    @app.post("/api/reports/<key>/reviews")
    def review(key):
        principal = require_actor()
        report = selected(key)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400)
        qid, action = body.get("qid"), body.get("action")
        allowed = {c["qid"] for c in report["checks"] if c.get("next_action") == "ESCALATE"}
        allowed |= {x["question_id"] for x in report["supplemental"]}
        if qid not in allowed or action not in ("accept", "correct", "reject", "materials"):
            abort(400)
        reviewer, note = body.get("reviewer"), body.get("note")
        if not isinstance(reviewer, str) or not 1 <= len(reviewer.strip()) <= 80 or not isinstance(note, str) or not 1 <= len(note.strip()) <= 5000:
            abort(400)
        corrected = body.get("corrected_answer", "")
        if not isinstance(corrected, str) or len(corrected) > 2000 or (action == "correct" and not corrected.strip()):
            abort(400)
        record = {"id": secrets.token_hex(12), "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                  "source": "member7_peripheral_review_workbench_user_submission", "document_id": report["identity"]["document_id"],
                  "report_sha256": report["report_sha256"], "qid": qid, "action": action,
                  "reviewer": clean(reviewer.strip()), "note": clean(note.strip()), "corrected_answer": clean(corrected.strip()),
                  "submitted_by_id": principal["id"],
                  "original_agent_report_modified": False}
        path = directory / "reviews" / (key + ".jsonl")
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return jsonify(record=record), 201

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="本地合同初审工作台：真实Agent审查与历史报告回放")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--offline", action="store_true", help="离线历史回放；后端禁止启动新的模型任务")
    parser.add_argument("--lan", action="store_true", help="允许同一局域网设备访问；实时审查仍须邀请码登录")
    parser.add_argument("--allow-host", action="append", default=[], help="额外允许的IP或主机名，不带端口；可重复")
    parser.add_argument("--secure-cookie", action="store_true", help="仅HTTPS发送登录Cookie，供已配置HTTPS的部署环境")
    args = parser.parse_args()
    allowed = set(args.allow_host)
    if any(not re.fullmatch(r"[A-Za-z0-9.:-]+", host) for host in allowed):
        parser.error("--allow-host须为明确IP或主机名，不能包含通配符、协议或路径")
    if args.lan:
        allowed.update(lan_addresses())
    print(f"LOCAL_URL=http://127.0.0.1:{args.port}", flush=True)
    app = create_app(offline=args.offline, trusted_hosts=allowed, secure_cookie=args.secure_cookie)
    if args.lan:
        for host in sorted(allowed):
            print(f"GROUP_URL=http://{host}:{args.port}", flush=True)
    print("ACCESS=INVITE_LOGIN (public history, private uploads)", flush=True)
    print("MODE=" + ("OFFLINE_PLAYBACK" if args.offline else "REALTIME_REVIEW"), flush=True)
    try:
        app.run(host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port, debug=False, use_reloader=False, threaded=True)
    finally:
        app.extensions["task_manager"].close()
