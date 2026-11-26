"""Local subprocess jobs. This module never imports an Agent or model client."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from uuid import uuid4

from werkzeug.utils import secure_filename
from report_store import ROOT, CODE, MEMBER, clean, digest

RUNS = MEMBER / "results/web_runs"
MAX_UPLOAD = 10 * 1024 * 1024
TERMINAL = {"COMPLETED", "FAILED", "STOPPED", "CANCELLED", "INTERRUPTED"}


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def dump(path, value):
    # Windows readers/antivirus may briefly deny replacing an open status file.
    # Unique temporary names also avoid collisions between worker and monitor.
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for attempt in range(9):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 8:
                    raise
                time.sleep(0.025 * (attempt + 1))
    finally:
        if temporary.exists():
            temporary.unlink()


def pid_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class TaskError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class TaskManager:
    def __init__(self, root=RUNS, launcher=subprocess.Popen):
        self.root = Path(root)
        self.launcher = launcher
        self.lock = threading.RLock()
        self.processes = {}
        self.closing = False

    def path(self, task_id):
        if not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise TaskError("任务不存在", 404)
        folder = self.root / task_id
        if not folder.resolve().is_relative_to(self.root.resolve()) or not (folder / "task.json").is_file():
            raise TaskError("任务不存在", 404)
        return folder

    def create(self, upload, form, catalog, owner_id=None):
        request_id = form.get("request_id", "")
        if not re.fullmatch(r"[a-f0-9-]{32,36}", request_id):
            raise TaskError("缺少有效请求标识，请刷新页面后提交")
        try:
            clauses = json.loads(form.get("clauses", "[]"))
            top_k, retries = int(form.get("top_k", 5)), int(form.get("max_retries", 2))
        except (ValueError, TypeError):
            raise TaskError("条款或参数格式无效") from None
        valid = {c["id"] for c in catalog}
        if (not isinstance(clauses, list) or not clauses or not all(isinstance(c, str) and c in valid for c in clauses)
                or len(set(clauses)) != len(clauses) or len(clauses) > 41):
            raise TaskError("请勾选1–41个有效条款，不能重复")
        clauses.sort(key=lambda q: int(q[1:]))
        if not 1 <= top_k <= 20 or not 0 <= retries <= 2:
            raise TaskError("top-k须为1–20，最大补查次数须为0–2")
        if len(clauses) > 5 and form.get("large_scope_confirmed") != "true":
            raise TaskError("超过5类条款需先确认页面显示的调用规模")
        name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(name).suffix.lower()
        if suffix not in (".txt", ".pdf"):
            raise TaskError("仅支持PDF或UTF-8 TXT合同")
        content = upload.stream.read(MAX_UPLOAD + 1)
        if not content:
            raise TaskError("合同内容为空")
        if len(content) > MAX_UPLOAD:
            raise TaskError("合同不能超过10 MB", 413)
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            raise TaskError("PDF文件头无效，请选择真实PDF")
        if suffix == ".txt":
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise TaskError("TXT须使用UTF-8编码，请另存为UTF-8后上传") from None
            if not text.strip() or "\x00" in text:
                raise TaskError("TXT为空或含二进制字符")
        signature = digest(json.dumps([digest(content), clauses, top_k, retries]).encode())
        with self.lock:
            if self.closing:
                raise TaskError("服务正在停止", 503)
            # A retried HTTP submission with the same ID never spawns another job.
            for path in self.root.glob("*/task.json"):
                previous = json.loads(path.read_bytes())
                if previous["request_id"] == request_id:
                    if previous.get("owner_id") != owner_id:
                        raise TaskError("请求标识已被使用，请重新提交", 409)
                    if previous["input_signature"] != signature:
                        raise TaskError("同一请求标识不能用于不同合同或参数", 409)
                    return self.status(path.parent.name), False
            if any(process.poll() is None for process in self.processes.values()):
                raise TaskError("已有审查正在运行，请等待完成或先停止该任务", 409)
            task_id = uuid4().hex
            folder = self.root / task_id
            (folder / "input").mkdir(parents=True, exist_ok=False)
            safe = secure_filename(name)
            if not safe or Path(safe).suffix.lower() != suffix:
                safe = "contract" + suffix
            contract = folder / "input" / safe
            contract.write_bytes(content)
            task = {"task_id": task_id, "request_id": request_id, "input_signature": signature,
                    "created_at": now(), "original_filename": clean(name[:180]), "filename": safe,
                    "clauses": clauses, "top_k": top_k, "max_retries": retries,
                    "raw_contract_sha256": digest(content), "file_bytes": len(content),
                    "large_scope_confirmed": len(clauses) > 5, "source": "real_web_agent_run",
                    "owner_id": owner_id}
            dump(folder / "task.json", task)
            dump(folder / "state.json", {"status": "STARTING", "started_at": now(), "stage": "initializing"})
            python = CODE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            command = [str(python), "-B", "-u", str(Path(__file__).with_name("agent_worker.py")), str(folder.resolve())]
            env = os.environ.copy()
            env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
            try:
                with (folder / "worker_boot.log").open("wb") as log:
                    process = self.launcher(command, cwd=str(CODE), env=env, stdout=log, stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.processes[task_id] = process
                if hasattr(process, "pid"):
                    dump(folder / "process.json", {"pid": process.pid, "started_at": now()})
                threading.Thread(target=self._monitor, args=(task_id, process), daemon=True).start()
            except OSError:
                dump(folder / "state.json", {"status": "FAILED", "stage": "initializing", "ended_at": now(),
                                             "error": "无法启动已有虚拟环境的Python，请检查路径与权限"})
            return self.status(task_id), True

    def _monitor(self, task_id, process):
        try:
            process.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            self.cancel(task_id, "任务超过一小时，外围工作台已停止进程；已发出的请求可能计费")
        with self.lock:
            folder = self.path(task_id)
            state = json.loads((folder / "state.json").read_bytes())
            if state["status"] not in TERMINAL:
                dump(folder / "state.json", {**state, "status": "FAILED", "ended_at": now(),
                                             "error": "工作进程已退出，未形成完整报告；保留日志及已有断点", "exit_code": process.returncode})

    def status(self, task_id, after=0):
        folder = self.path(task_id)
        task = json.loads((folder / "task.json").read_bytes())
        state = json.loads((folder / "state.json").read_bytes())
        events = []
        path = folder / "events.jsonl"
        if path.is_file():
            for line in path.read_bytes().splitlines(keepends=True):
                if not line.endswith(b"\n"):
                    continue
                try:
                    event = json.loads(line)
                    if event["sequence"] > after:
                        events.append(event)
                except (ValueError, UnicodeError):
                    pass  # A trailing line may still be in flight.
        process = self.processes.get(task_id)
        # A worker holds the OS lock independently of the server. Never resume automatically.
        if state["status"] not in TERMINAL and process is None:
            process_path = folder / "process.json"
            if process_path.is_file() and not pid_alive(json.loads(process_path.read_bytes())["pid"]):
                state = {**state, "status": "INTERRUPTED", "ended_at": now(),
                         "error": "原工作进程已退出，记录未完整结束；保留已有报告/日志/断点，不自动重跑"}
                dump(folder / "state.json", state)
            else:
                state = {**state, "reconnected": True}
        completed = max([e.get("completed", 0) for e in events] + [state.get("completed", 0)])
        return clean({**task, **state, "completed": completed, "total": len(task["clauses"]),
                      "events": events[-1000:], "last_sequence": max([e["sequence"] for e in events] + [after]),
                      "output_directory": folder.relative_to(ROOT).as_posix() if folder.is_relative_to(ROOT) else folder.name})

    def list(self):
        return [self.status(p.parent.name) for p in sorted(self.root.glob("*/task.json"), reverse=True)]

    def cancel(self, task_id, reason="使用者停止了任务；已发出的模型请求可能计费，原生断点已保留"):
        with self.lock:
            folder = self.path(task_id)
            process = self.processes.get(task_id)
            if process is None or process.poll() is not None:
                raise TaskError("当前服务没有可停止的该任务进程", 409)
            process.terminate()
            process.wait(timeout=10)
            state = json.loads((folder / "state.json").read_bytes())
            dump(folder / "state.json", {**state, "status": "CANCELLED", "ended_at": now(), "error": reason})
            return self.status(task_id)

    def close(self):
        self.closing = True
        for task_id, process in list(self.processes.items()):
            if process.poll() is None:
                self.cancel(task_id, "本地服务停止，后台审查已终止；保留已完成条款断点")
