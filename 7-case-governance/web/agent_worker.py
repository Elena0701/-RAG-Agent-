"""Observe the unchanged native main.py in an isolated existing-venv process."""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback

sys.dont_write_bytecode = True
from task_manager import RUNS, CODE, ROOT, now, dump
from report_store import clean, digest, ingestion_module


class StopService(BaseException):
    pass


def execution_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise StopService("另一个工作进程正在审查；本任务未调用模型") from None
    return stream


class Observer:
    def __init__(self, folder, task, secrets):
        self.folder, self.task, self.secrets = folder, task, secrets
        self.sequence, self.completed, self.qid, self.round = 0, 0, None, None
        self.stats = {"extraction_calls":0, "verification_calls":0, "success_calls":0, "failed_calls":0,
                      "prompt_tokens":0, "completion_tokens":0, "total_tokens":0}
        self.failures = {"extraction":0, "verification":0}
        self.state = {"status":"RUNNING", "stage":"initializing", "started_at":now(), "completed":0}

    def redact(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return clean(text)

    def append(self, name, value):
        with (self.folder / name).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(self.redact(json.dumps(value, ensure_ascii=False, default=str)) + "\n")

    def emit(self, stage, message, **fields):
        self.sequence += 1
        event = {"sequence":self.sequence, "timestamp":now(), "stage":stage, "message":message,
                 "qid":self.qid, "round":self.round, "completed":self.completed, **fields}
        self.append("events.jsonl", event)
        self.state.update(stage=stage, qid=self.qid, round=self.round, completed=self.completed,
                          last_sequence=self.sequence, api_usage=self.stats.copy())
        dump(self.folder / "state.json", clean(self.state))

    def observe_api(self, stage, messages, call, describe):
        if sum(self.stats[k] for k in ("extraction_calls", "verification_calls")) >= len(self.task["clauses"]) * (self.task["max_retries"]+1) * 3:
            raise StopService("已达外围工作台请求次数上限，停止新增调用并保留断点")
        self.stats[stage+"_calls"] += 1
        call_id = stage + "_" + str(self.stats[stage+"_calls"])
        self.append("api_trace.jsonl", {"timestamp":now(), "event":"request", "stage":stage, "call_id":call_id, "messages":messages})
        self.emit(stage, "正在调用事实抽取模型" if stage=="extraction" else "正在调用证据语义核验模型", model_call_status="REQUEST", call_id=call_id)
        begin = time.monotonic()
        try:
            response = call()
        except Exception as exc:
            status, code = getattr(exc,"status_code",None), getattr(exc,"code",None)
            hard = status in (401,402,403,429) or code in {"API_AUTH_FAILED","API_BALANCE_INSUFFICIENT","API_FORBIDDEN","API_RATE_LIMITED"}
            self.failures[stage] = self.failures[stage]+1 if hard else 0
            self.stats["failed_calls"] += 1
            self.append("api_trace.jsonl", {"timestamp":now(), "event":"error", "stage":stage, "call_id":call_id,
                                          "exception_type":type(exc).__name__, "code":code, "status_code":status})
            self.emit(stage, "模型调用异常：" + str(code or status or type(exc).__name__), model_call_status="ERROR")
            if self.failures[stage] >= 2:
                raise StopService("连续两次认证、额度、权限或限流故障，停止新增调用；增加检索无法解决该故障") from None
            raise
        self.failures[stage] = 0
        self.stats["success_calls"] += 1
        record = describe(response)
        for key in ("prompt_tokens","completion_tokens","total_tokens"):
            self.stats[key] += (record.get("usage") or {}).get(key,0) or 0
        self.append("api_trace.jsonl", {"timestamp":now(), "event":"response", "stage":stage, "call_id":call_id,
                                      "elapsed_seconds":round(time.monotonic()-begin,3), **record})
        self.emit(stage, "模型响应已收到", model_call_status="SUCCESS", call_id=call_id)
        return response

    def instrument(self, agent):
        verifier = getattr(agent.rag_tool.model_call, "client", None)
        if verifier is not None:
            cfg = verifier.config
            if cfg.api_key and cfg.api_key not in self.secrets:
                self.secrets.append(cfg.api_key)
            observer = self
            class Verifier:
                config = cfg
                def __getattr__(self, name):
                    return getattr(verifier, name)
                def __call__(self, messages):
                    return observer.observe_api("verification", messages, lambda:verifier(messages),
                        lambda result:{"content":result, **(verifier.last_call or {})})
            agent.rag_tool.model_call.client = Verifier()
        create = agent.llm_client.chat.completions.create
        agent.llm_client.chat.completions.create = lambda *a,**kw:self.observe_api("extraction",kw.get("messages"),lambda:create(*a,**kw),
            lambda r:{"response":r.model_dump(mode="json"), "usage":r.usage.model_dump() if r.usage else {}})
        # These wrappers only observe method boundaries; original arguments/results are unchanged.
        for name, stage in (("create_tasks","planning"),("prepare_document","parsing"),("retrieve","retrieval"),
                            ("extract","extraction"),("verify","verification"),("review_rules","rules"),
                            ("decide_next_action","decision"),("save_report","report")):
            original = getattr(agent,name)
            def wrap(original=original, name=name, stage=stage):
                @functools.wraps(original)
                def observed(*args, **kwargs):
                    if name=="review_rules" and self.qid in {"Q1","Q2","Q3","Q4","Q5"}:
                        result=original(*args,**kwargs)
                        self.emit(stage, "Q1–Q5业务规则核验未执行", state="NOT_EXECUTED")
                        return result
                    self.emit(stage, {"planning":"正在创建所选审查任务","parsing":"正在解析合同并建立混合检索索引",
                                    "retrieval":"正在检索合同证据","extraction":"正在抽取候选答案","verification":"正在核验证据",
                                    "rules":"正在核验业务规则","decision":"正在形成Agent决策","report":"正在生成原生JSON报告"}[stage])
                    result=original(*args,**kwargs)
                    fields={}
                    if name=="retrieve": fields["candidate_count"]=len(result.get("text",[]))
                    if name=="verify": fields.update(verification_status=result.get("verification_status"),coverage_status=result.get("coverage_status"))
                    if name=="decide_next_action": fields["decision"]=result
                    if name=="prepare_document" and result.get("status")=="SUCCESS":
                        source=self.folder/"input"/self.task["filename"]
                        parsed=ingestion_module().ingest(source)
                        dump(self.folder/"text_snapshot.json", {"normalized_text":parsed.text,"normalized_sha256":digest(parsed.text.encode()),
                             "raw_sha256":digest(source.read_bytes()),"source_format":source.suffix[1:].upper(),
                             "pages":parsed.pages,"parse_method":parsed.method,"warnings":parsed.warnings,
                             "normalizer_sha256":digest((CODE/"tools/rag_tool/rag_core/pdf_ingest.py").read_bytes())})
                    failed = name=="prepare_document" and result.get("status")!="SUCCESS"
                    self.emit(stage, "步骤未完成" if failed else "步骤完成", state="FAILED" if failed else "DONE", **fields)
                    return result
                return observed
            setattr(agent,name,wrap())
        review = agent.review_task
        def review_task(task, document):
            self.qid, self.round=task["question_id"],1
            result=review(task,document)
            self.completed+=1
            self.emit("decision","该条款处理完成",event="clause_completed",decision=result.get("next_action"),
                      verification_status=result.get("verification_status"),retry_count=result.get("retry_count",0))
            return result
        agent.review_task=review_task
        return verifier


class Tee:
    def __init__(self, log, observer): self.log,self.observer=log,observer
    def write(self, value): self.log.write(self.observer.redact(value)); self.log.flush(); return len(value)
    def flush(self): self.log.flush()
    def isatty(self): return False


def run(folder):
    if not folder.resolve().is_relative_to(RUNS.resolve()) or not re.fullmatch(r"[a-f0-9]{32}",folder.name):
        raise ValueError("Invalid task directory")
    if Path(sys.prefix).resolve() != (CODE/".venv").resolve():
        raise ValueError("Use the existing Agent virtual environment")
    task=json.loads((folder/"task.json").read_bytes())
    observer=Observer(folder,task,[])
    begin=time.monotonic()
    metadata={"scope":"real_web_agent_run","web_task_id":task["task_id"],"started_at":now(),
              "contract_path":str(folder/"input"/task["filename"]),"original_filename":task["original_filename"],
              "raw_contract_sha256":task["raw_contract_sha256"],"question_ids":task["clauses"],
              "annotation_access":"none","api_count_semantics":"SDK create calls / verifier HTTP calls; SDK internal retries may add HTTP requests"}
    guard=None
    code=0
    stdout,stderr=sys.stdout,sys.stderr
    with (folder/"terminal.log").open("x",encoding="utf-8",newline="\n") as log:
        sys.stdout=sys.stderr=Tee(log,observer)
        try:
            guard=execution_lock(RUNS/".execution.lock")
            os.chdir(CODE)
            sys.path.insert(0,str(CODE))
            from dotenv import load_dotenv
            load_dotenv(CODE/".env",override=False)
            load_dotenv(CODE/"agents/.env",override=False)
            observer.secrets.extend(v for k,v in os.environ.items() if k.endswith("API_KEY") and v)
            observer.emit("initializing","正在加载已有Agent及模型配置")
            # Reuse the existing source-fingerprint utility, without invoking its runner.
            sys.path.insert(0,str(ROOT/"7-case-governance/scripts"))
            from run_case import sources
            metadata["core_sources_before"]=sources()
            import main as native
            original_build=native.build_agent
            def build(**kwargs):
                original_progress=kwargs["progress"]
                def progress(message):
                    original_progress(message)
                    match=re.search(r"第 (\d+) 轮",message)
                    if match: observer.round=int(match[1])
                    observer.emit(observer.state["stage"],message,event="native_progress")
                kwargs["progress"]=progress
                agent=original_build(**kwargs)
                verifier=observer.instrument(agent)
                metadata.update(extraction_model=agent.model,verification_config=verifier.config.public_metadata() if verifier else None,
                    rag_config={k:v for k,v in agent.rag_tool.config.items() if not callable(v)},policy=agent.rule_tool.config,
                    top_k=agent.top_k,max_retries=agent.max_retries,python_executable=sys.executable)
                dump(folder/"run_metadata.json",metadata)
                return agent
            native.build_agent=build
            sys.argv=[str(CODE/"main.py"),metadata["contract_path"],"--clauses",*task["clauses"],
                      "--top-k",str(task["top_k"]),"--max-retries",str(task["max_retries"]),"--output-dir",str(folder)]
            metadata["native_argv"]=[sys.executable,"-B","-u",*sys.argv]
            native.main()
            reports=[p for p in (folder/"reports").glob("*.json") if not p.name.endswith(".conversation.json")]
            report=json.loads(reports[0].read_bytes()) if reports else {}
            if len(report.get("checks",[]))!=len(task["clauses"]):
                raise StopService("Agent未完成全部任务；请检查解析/索引日志及原生报告")
            observer.state.update(status="COMPLETED",report_file=str(reports[0].relative_to(folder)),
                                  agent_status=report.get("status"))
            observer.emit("report","原生报告及对话已保存",state="DONE")
        except StopService as exc:
            code=3
            observer.state.update(status="STOPPED",error=str(exc))
            observer.emit(observer.state["stage"],str(exc),event="stopped")
        except BaseException as exc:
            code=2
            (folder/"worker_error.log").write_text(observer.redact(traceback.format_exc()), encoding="utf-8")
            observer.state.update(status="FAILED",error="工作进程异常："+type(exc).__name__+"；查看本地日志及断点")
            observer.emit(observer.state["stage"],observer.state["error"],event="error")
        finally:
            metadata.update(ended_at=now(),elapsed_seconds=round(time.monotonic()-begin,3),exit_code=code,api_usage=observer.stats,
                            runner_status=observer.state["status"])
            if "core_sources_before" in metadata:
                metadata["core_sources_after"]=sources()
                metadata["core_sources_unchanged"]=metadata["core_sources_before"]==metadata["core_sources_after"]
            dump(folder/"run_metadata.json",metadata)
            dump(folder/"artifact_manifest.json",{"files":[{"path":str(p.relative_to(folder)),"bytes":p.stat().st_size,"sha256":digest(p.read_bytes())}
                 for part in ("reports","conversations","checkpoints") for p in sorted((folder/part).glob("*")) if p.is_file()],
                 "scope":"native artifacts unchanged"})
            observer.state.update(ended_at=now(),exit_code=code,elapsed_seconds=metadata["elapsed_seconds"],api_usage=observer.stats)
            dump(folder/"state.json",observer.state)
            sys.stdout,sys.stderr=stdout,stderr
            if guard: guard.close()
    return code


if __name__=="__main__":
    raise SystemExit(run(Path(sys.argv[1]).resolve()))
