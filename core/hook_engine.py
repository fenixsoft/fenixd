"""
hook_engine.py — SPEC 状态变化事件 hook 订阅与执行引擎（add-spec-hooks）。

事件源是 EventBus 的状态 diff（old_status != new_status）。两级配置存
`.fenix/config.yaml` 的 `hooks` 段（设计 D2）：

    hooks:
      global:                       # 对所有 spec 生效（设置页配置）
        - id: h-3f9a2b
          enabled: true
          events: [done, blocked]
          action: restart-daemon
          ...
      specs:                        # 仅对指定 spec 生效（spec 详情页配置）
        add-xxx:
          - { id: h-7c1d9e, enabled: true, events: [done], action: commit-push }

七个动作（D4）：restart-daemon / restart-dashboard / commit / push /
commit-push / webhook / shell。命中 hook 在独立 daemon 线程并发执行，
不阻塞 EventBus 分发（D3）；动作失败不重试，写审计 + admin_store 站内告警（D5）。
审计 `.fenix/hook_audit.jsonl` append-only（D6），dashboard 经
`read_hook_audit` 纯函数读取尾部。

线程安全：审计写入带进程内线程锁 + 跨进程 fcntl.flock（风格对齐
admin_store 的 DisputeAuditStore 追加模式）。
"""

import fcntl
import json
import os
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .admin_store import AdminStore, ESCALATION
from .state_machine import SpecStatus

# ── 常量 ───────────────────────────────────────────────────────────

# 全部合法动作（D4 七枚举）
HOOK_ACTIONS = (
    "restart-daemon",
    "restart-dashboard",
    "commit",
    "push",
    "commit-push",
    "webhook",
    "shell",
)

# 订阅事件类型 = 十状态枚举（drafted … pushed）
VALID_EVENTS = tuple(SpecStatus.ALL)

# 超时缺省（D4：shell 缺省 60，webhook 缺省 10）
DEFAULT_SHELL_TIMEOUT_SECONDS = 60
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 10

# dashboard 重启探测（D4：保持 8787 端口；探测超时则失败告警）
DEFAULT_DASHBOARD_PORT = 8787
DEFAULT_DASHBOARD_SESSION = "fenix-dashboard"
DASHBOARD_PROBE_ATTEMPTS = 20
DASHBOARD_PROBE_INTERVAL = 0.5

# 审计 detail 截断（D6：≤2KB）
DETAIL_LIMIT = 2048

# 审计状态（D6）
STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"
STATUS_NOOP = "noop"
STATUS_SKIPPED = "skipped"


def _utcnow_iso() -> str:
    """UTC ISO 时间戳（Z 后缀，与既有日志格式一致）。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate(text: str, limit: int = DETAIL_LIMIT) -> str:
    """截断到 limit 字符（≤2KB 审计约束），保留头部。"""
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…(截断)"


def _num(value, default: float) -> float:
    """数值兜底：非法/非正数回退缺省。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def _tail_combined(stdout: Optional[str], stderr: Optional[str]) -> str:
    """合并 stdout+stderr 尾部（shell/commit 输出入审计）。"""
    parts = [s for s in (stdout, stderr) if s and s.strip()]
    if not parts:
        return ""
    return _truncate("\n".join(p.strip() for p in parts)[-DETAIL_LIMIT:], DETAIL_LIMIT)


def _run_git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """在项目根执行 git 子命令（统一超时 60s）。"""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


def render_message_template(template: str, spec: str, event: str) -> str:
    """渲染提交信息模板（D4：未知变量原样保留，不致命）。

    支持的模板变量：{spec} / {event}。缺省模板 `[fenix] hook: {spec} {event}`。
    """
    if not template:
        return f"[fenix] hook: {spec} {event}"
    out = template.replace("{spec}", spec).replace("{event}", event)
    return out


def hook_config(config: dict) -> dict:
    """返回配置中的 hooks 段（缺省空结构，不修改入参）。"""
    hooks = config.get("hooks") if isinstance(config, dict) else None
    if not isinstance(hooks, dict):
        return {"global": [], "specs": {}}
    return hooks


def validate_hook_entry(entry: Any) -> Optional[str]:
    """校验单条 hook 配置（tasks 1.1 / D7）。

    规则：
    - 必须为 dict；
    - events 非空列表，取值 ∈ 十状态枚举；
    - action ∈ 七枚举；
    - action=webhook 必须 url 非空字符串；
    - action=shell 必须 command 非空字符串。

    Returns: 非法时返回错误描述（含字段路径），合法返回 None。
    """
    if not isinstance(entry, dict):
        return "hook 条目必须为对象"
    events = entry.get("events")
    if not isinstance(events, list) or not events:
        return "events 必须为非空数组（订阅的事件类型，取十状态枚举值）"
    for ev in events:
        if ev not in VALID_EVENTS:
            return f"events 含非法事件类型: {ev!r}（应为 {list(VALID_EVENTS)} 之一）"
    action = entry.get("action")
    if action not in HOOK_ACTIONS:
        return f"action 非法: {action!r}（应为 {list(HOOK_ACTIONS)} 之一）"
    if action == "webhook":
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            return "webhook 动作必须提供非空 url"
    if action == "shell":
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            return "shell 动作必须提供非空 command"
    return None


def validate_hooks_config(config: dict) -> Optional[str]:
    """校验配置 hooks 段全部条目（tasks 1.1 / 4.2 共用）。

    违规返回首个错误描述；合法返回 None。忽略非 dict 的段落结构（视为空）。
    """
    hooks = config.get("hooks")
    if hooks is None:
        return None
    if not isinstance(hooks, dict):
        return "hooks 段必须为对象（global 列表 + specs 映射）"
    globals_ = hooks.get("global")
    if globals_ is not None and not isinstance(globals_, list):
        return "hooks.global 必须为列表"
    for idx, h in enumerate(globals_ or []):
        err = validate_hook_entry(h)
        if err:
            return f"hooks.global[{idx}] {err}"
    specs = hooks.get("specs")
    if specs is not None and not isinstance(specs, dict):
        return "hooks.specs 必须为对象（spec 名 → hook 列表）"
    for spec_name, hook_list in (specs or {}).items():
        if not isinstance(hook_list, list):
            return f"hooks.specs.{spec_name} 必须为列表"
        for idx, h in enumerate(hook_list):
            err = validate_hook_entry(h)
            if err:
                return f"hooks.specs.{spec_name}[{idx}] {err}"
    return None


def match_hooks(config: dict, spec: str, event_type: str) -> List[Tuple[dict, str]]:
    """事件匹配（tasks 1.2 / D3）：(spec, event_type) → 命中的 hook 列表。

    返回 [(hook_cfg, scope), ...]，scope ∈ "global" | "spec"。
    匹配不看 enabled（disabled 在执行阶段记 skipped 审计）；事件类型 = 新状态。
    """
    hooks = hook_config(config)
    matched: List[Tuple[dict, str]] = []
    for h in hooks.get("global") or []:
        if isinstance(h, dict) and event_type in (h.get("events") or []):
            matched.append((h, "global"))
    spec_hooks = hooks.get("specs") or {}
    for h in spec_hooks.get(spec) or []:
        if isinstance(h, dict) and event_type in (h.get("events") or []):
            matched.append((h, "spec"))
    return matched


def read_hook_audit(project_root, spec: Optional[str] = None, limit: int = 20) -> list:
    """读取 .fenix/hook_audit.jsonl 尾部（D6 / tasks 1.3 / 4.1）。

    按 spec 过滤（spec=None 不过滤）、时间倒序、limit 截断；文件不存在/损坏返回 []。
    """
    path = Path(project_root) / ".fenix" / "hook_audit.jsonl"
    if not path.exists():
        return []
    out: list = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(d, dict) and (spec is None or d.get("spec") == spec):
                    out.append(d)
    except OSError:
        return []
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    if limit and limit > 0:
        out = out[:limit]
    return out


class HookEngine:
    """SPEC 状态事件 hook 引擎：匹配、异步执行、审计、失败告警。

    装配（D8）：daemon 启动时实例化并作为 hook_dispatcher 注入 EventBus。
    执行时实时从 config 对象读 hooks 段（D3：享受 30s 配置热更新，
    无独立缓存失效问题——config 对象是各组件共享的同一引用）。
    """

    def __init__(self, project_root, config: dict, logger=None, admin_store=None):
        self.project_root = Path(project_root)
        self.config = config
        self.logger = logger
        self.admin_store = admin_store
        self._audit_lock = threading.Lock()
        # 框架目录：core/hook_engine.py → 框架根（bin/fenix_dashboard.py 所在）
        self._framework_root = Path(__file__).resolve().parent.parent
        self._project_name = None

    # ── 事件分发（EventBus diff 处调用，只投递不阻塞）────────────────

    def dispatch(self, spec: str, from_status: Optional[str],
                 to_status: str, entry: Optional[dict]) -> None:
        """(spec, from, to, entry) 事件分发：匹配 + 每命中 hook 一个线程并发执行。

        分发阶段任何异常只记日志，不向调用方抛（状态机写入路径不被 hook 阻塞）。
        """
        try:
            matches = match_hooks(self.config, spec, to_status)
        except Exception as e:
            self._log_error(
                f"hook 匹配失败 spec={spec} event={to_status}: {type(e).__name__}: {e}")
            return
        if not matches:
            return
        for cfg, scope in matches:
            hook_id = cfg.get("id") if isinstance(cfg, dict) else None
            th = threading.Thread(
                target=self._execute_one,
                args=(hook_id, scope, spec, from_status, to_status, entry or {}),
                name=f"hook-{hook_id or 'anon'}-{spec}",
                daemon=True,
            )
            th.start()

    # ── 单条执行 ────────────────────────────────────────────────────

    def _find_live_hook(self, hook_id, scope: str, spec: str) -> Optional[dict]:
        """执行前从实时 config 读 hooks 段，按 id + 作用域找回该条配置。

        配置在投递与执行间隙被删除 → 静默跳过（不写审计）。
        """
        if not hook_id:
            return None
        hooks = hook_config(self.config)
        candidates = []
        if scope == "global":
            candidates = hooks.get("global") or []
        else:
            candidates = (hooks.get("specs") or {}).get(spec) or []
        for h in candidates:
            if isinstance(h, dict) and h.get("id") == hook_id:
                return h
        return None

    def _execute_one(self, hook_id, scope: str, spec: str,
                     from_status: Optional[str], to_status: str,
                     entry: dict) -> None:
        """单条 hook 的执行线程：实时重读配置、enabled 判 skip、执行、审计。

        单 hook 异常互不影响（线程级 try 全包裹，失败走 failure 审计+告警）。
        """
        try:
            cfg = self._find_live_hook(hook_id, scope, spec)
            if cfg is None:
                return
            if not cfg.get("enabled", True):
                self._audit(spec, to_status, from_status, to_status, hook_id,
                            cfg.get("action"), scope, STATUS_SKIPPED,
                            "enabled=false，已跳过", 0.0)
                return
            err = validate_hook_entry(cfg)
            if err:
                # 配置被手工改坏：记 failure 但不告警（配置层错误，审计暴露）
                self._audit(spec, to_status, from_status, to_status, hook_id,
                            cfg.get("action"), scope, STATUS_FAILURE,
                            f"hook 配置非法（不执行）: {err}", 0.0)
                return
            self._execute_action(cfg, scope, spec, from_status, to_status, entry)
        except Exception as e:
            detail = f"hook 执行异常: {type(e).__name__}: {e}"
            try:
                self._audit(spec, to_status, from_status, to_status, hook_id,
                            "?", scope, STATUS_FAILURE, detail, 0.0)
                self._alert_failure(spec, to_status, "?", scope, detail)
            except Exception:
                pass

    def _execute_action(self, cfg: dict, scope: str, spec: str,
                        from_status: Optional[str], to_status: str,
                        entry: dict) -> None:
        """按动作类型执行并统一写审计；失败再发站内告警（D5，不重试）。"""
        action = cfg["action"]
        hook_id = cfg.get("id")
        started = time.monotonic()

        if action == "restart-daemon":
            ok, detail = self._action_restart_daemon()
            status = STATUS_SUCCESS if ok else STATUS_FAILURE
        elif action == "commit":
            status, detail = self._action_commit(cfg, spec, to_status)
        elif action == "push":
            status, detail = self._action_push()
        elif action == "commit-push":
            status, detail = self._action_commit_push(cfg, spec, to_status)
        elif action == "restart-dashboard":
            ok, detail = self._action_restart_dashboard(cfg)
            status = STATUS_SUCCESS if ok else STATUS_FAILURE
        elif action == "webhook":
            status, detail = self._action_webhook(cfg, spec, from_status, to_status, entry)
        elif action == "shell":
            status, detail = self._action_shell(cfg, spec, from_status, to_status, entry)
        else:  # 校验已保证合法，防御兜底
            status, detail = STATUS_FAILURE, f"未知动作: {action}"

        duration = time.monotonic() - started
        self._audit(spec, to_status, from_status, to_status, hook_id,
                    action, scope, status, detail, duration)
        if status == STATUS_FAILURE:
            self._alert_failure(spec, to_status, action, scope, detail)

    # ── 七种动作（D4） ──────────────────────────────────────────────

    def _action_restart_daemon(self) -> Tuple[bool, str]:
        """touch .fenix/restart_request，复用 supervisor 优雅重启协议。"""
        req = self.project_root / ".fenix" / "restart_request"
        try:
            req.parent.mkdir(parents=True, exist_ok=True)
            req.touch()
            return True, "restart_request 已写入（supervisor 将执行优雅重启）"
        except OSError as e:
            return False, f"touch .fenix/restart_request 失败: {e}"

    def _action_commit(self, cfg: dict, spec: str, event: str) -> Tuple[str, str]:
        """git add -A + git commit -m <模板渲染>；无变更 → noop 成功。"""
        message = render_message_template(cfg.get("message") or "", spec, event)
        try:
            add = _run_git(["add", "-A"], self.project_root)
        except (subprocess.SubprocessError, OSError) as e:
            return STATUS_FAILURE, f"git add 执行失败: {e}"
        if add.returncode != 0:
            return STATUS_FAILURE, f"git add -A 失败: {_tail_combined(add.stdout, add.stderr)}"
        try:
            quiet = _run_git(["diff", "--cached", "--quiet"], self.project_root)
        except (subprocess.SubprocessError, OSError) as e:
            return STATUS_FAILURE, f"git diff 执行失败: {e}"
        if quiet.returncode == 0:
            return STATUS_NOOP, "无变更（nothing to commit）"
        try:
            res = _run_git(["commit", "-m", message], self.project_root)
        except (subprocess.SubprocessError, OSError) as e:
            return STATUS_FAILURE, f"git commit 执行失败: {e}"
        if res.returncode != 0:
            return STATUS_FAILURE, f"git commit 失败: {_tail_combined(res.stdout, res.stderr)}"
        return STATUS_SUCCESS, f"已提交: {_tail_combined(res.stdout, res.stderr)}"

    def _action_push(self) -> Tuple[str, str]:
        """git push（跟随当前分支 upstream）。"""
        try:
            res = _run_git(["push"], self.project_root)
        except (subprocess.SubprocessError, OSError) as e:
            return STATUS_FAILURE, f"git push 执行失败: {e}"
        if res.returncode != 0:
            return STATUS_FAILURE, f"git push 失败: {_tail_combined(res.stdout, res.stderr)}"
        return STATUS_SUCCESS, _tail_combined(res.stdout, res.stderr) or "push 完成"

    def _action_commit_push(self, cfg: dict, spec: str, event: str) -> Tuple[str, str]:
        """先 commit 后 push；commit noop 仍 push；push 失败不回滚本地提交。"""
        cstatus, cdetail = self._action_commit(cfg, spec, event)
        if cstatus == STATUS_FAILURE:
            return STATUS_FAILURE, cdetail
        pstatus, pdetail = self._action_push()
        if pstatus == STATUS_FAILURE:
            return STATUS_FAILURE, f"commit 已完成但 push 失败（本地提交保留）: {pdetail}"
        if cstatus == STATUS_NOOP:
            return STATUS_SUCCESS, f"commit noop（无变更）；{pdetail}"
        return STATUS_SUCCESS, f"{cdetail}；{pdetail}"

    def _action_restart_dashboard(self, cfg: dict) -> Tuple[bool, str]:
        """tmux respawn-window -k -t <target> 重启 dashboard 会话。

        固化启动命令（2026-09-06 从存活会话提取固化）：``env -u CLAUDE_PID
        python3 <framework>/bin/fenix_dashboard.py --serve``——env -u CLAUDE_PID
        防 claude-watchdog 绑会话自杀；保持 8787 端口（serve() 内部解析配置
        端口，缺省 8787）与原工作目录。重启后以端口重新可服务为成功判据。
        """
        target = (cfg.get("target") or "").strip() or DEFAULT_DASHBOARD_SESSION
        try:
            has = subprocess.run(["tmux", "has-session", "-t", target],
                                 capture_output=True, text=True, timeout=10)
        except (subprocess.SubprocessError, OSError) as e:
            return False, f"tmux has-session 失败: {e}"
        if has.returncode != 0:
            return False, f"tmux 会话 {target} 不存在，无法重启"
        dash = self._framework_root / "bin" / "fenix_dashboard.py"
        if not dash.is_file():
            return False, f"dashboard 启动脚本不存在: {dash}"
        shell_cmd = (
            f"cd {shlex.quote(str(self.project_root))} && "
            f"env -u CLAUDE_PID python3 {shlex.quote(str(dash))} --serve"
        )
        try:
            respawn = subprocess.run(
                ["tmux", "respawn-window", "-k", "-t", target, shell_cmd],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.SubprocessError, OSError) as e:
            return False, f"tmux respawn-window 失败: {e}"
        if respawn.returncode != 0:
            return False, f"tmux respawn-window 失败: {_tail_combined(respawn.stdout, respawn.stderr)}"
        port = self._dashboard_port()
        if not self._probe_dashboard(port):
            return False, f"dashboard 已 respawn，但 {port} 端口 {DASHBOARD_PROBE_ATTEMPTS * DASHBOARD_PROBE_INTERVAL:.0f}s 内未恢复 HTTP 可服务"
        return True, f"dashboard 会话 {target} 已重启（端口 {port} 恢复可服务）"

    def _dashboard_port(self) -> int:
        """dashboard 服务端口：config dashboard.port 合法则用之，否则 8787。"""
        try:
            from .config import ConfigLoader
            port = ConfigLoader.get(self.config, "dashboard.port", DEFAULT_DASHBOARD_PORT)
            port = int(port)
            if 0 < port < 65536:
                return port
        except (TypeError, ValueError):
            pass
        return DEFAULT_DASHBOARD_PORT

    @staticmethod
    def _probe_dashboard(port: int) -> bool:
        """轮询探测端口 HTTP 可服务（任何 HTTP 响应即视为服务已恢复）。"""
        url = f"http://127.0.0.1:{port}/"
        for _ in range(DASHBOARD_PROBE_ATTEMPTS):
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    resp.read(64)
                return True
            except urllib.error.HTTPError:
                return True  # 服务已响应（返回了错误码也算已起来）
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(DASHBOARD_PROBE_INTERVAL)
        return False

    def _action_webhook(self, cfg: dict, spec: str, from_status: Optional[str],
                        to_status: str, entry: dict) -> Tuple[str, str]:
        """POST JSON 通知（含审计）；2xx = 成功，响应体截断 2KB 记审计。"""
        url = (cfg.get("url") or "").strip()
        payload = {
            "event": to_status,
            "spec": spec,
            "from_status": from_status,
            "to_status": to_status,
            "ts": _utcnow_iso(),
            "error": entry.get("error"),
            "frozen": bool(entry.get("frozen", False)),
            "hook_id": cfg.get("id"),
            "action": "webhook",
            "project": self.project_name,
        }
        timeout = _num(cfg.get("timeout_seconds"), DEFAULT_WEBHOOK_TIMEOUT_SECONDS)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = resp.status
                body = resp.read(DETAIL_LIMIT)
        except urllib.error.HTTPError as e:
            return STATUS_FAILURE, f"webhook 非 2xx: HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return STATUS_FAILURE, f"webhook 请求失败: {e}"
        if not (200 <= code < 300):
            return STATUS_FAILURE, f"webhook 非 2xx: HTTP {code}"
        detail = _truncate(body.decode("utf-8", errors="replace")) if body else "webhook 已送达（空响应）"
        return STATUS_SUCCESS, detail

    def _action_shell(self, cfg: dict, spec: str, from_status: Optional[str],
                      to_status: str, entry: dict) -> Tuple[str, str]:
        """bash -c <command>，注入事件环境变量，超时强杀。"""
        command = (cfg.get("command") or "").strip()
        timeout = _num(cfg.get("timeout_seconds"), DEFAULT_SHELL_TIMEOUT_SECONDS)
        env = dict(os.environ)
        env["FENIX_HOOK_EVENT"] = to_status
        env["FENIX_HOOK_SPEC"] = spec
        env["FENIX_HOOK_FROM_STATUS"] = from_status or ""
        env["FENIX_HOOK_TO_STATUS"] = to_status
        env["FENIX_HOOK_ERROR"] = str(entry.get("error") or "")
        env["FENIX_HOOK_PROJECT_ROOT"] = str(self.project_root)
        try:
            res = subprocess.run(
                ["bash", "-c", command],
                cwd=str(self.project_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            detail = f"shell 超时（>{timeout:.0f}s）已强杀"
            tail = _tail_combined(e.stdout or "", e.stderr or "")
            return STATUS_FAILURE, f"{detail}{('：' + tail) if tail else ''}"
        except OSError as e:
            return STATUS_FAILURE, f"shell 执行失败: {e}"
        if res.returncode != 0:
            return STATUS_FAILURE, (
                f"退出码 {res.returncode}: {_tail_combined(res.stdout, res.stderr)}"
            )
        tail = _tail_combined(res.stdout, res.stderr)
        return STATUS_SUCCESS, tail or "退出码 0"

    # ── 审计与告警（D5/D6） ─────────────────────────────────────────

    def _audit(self, spec: str, event: str, from_status: Optional[str],
               to_status: Optional[str], hook_id, action, scope: str,
               status: str, detail: str, duration_s: float) -> None:
        """带锁追加一条审计记录到 .fenix/hook_audit.jsonl。"""
        rec = {
            "ts": _utcnow_iso(),
            "spec": spec,
            "event": event,
            "from_status": from_status,
            "to_status": to_status,
            "hook_id": hook_id,
            "action": action,
            "scope": scope,
            "status": status,
            "detail": _truncate(detail),
            "duration_ms": int(duration_s * 1000),
        }
        path = self.project_root / ".fenix" / "hook_audit.jsonl"
        lockfile = Path(str(path) + ".lock")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            with self._audit_lock:
                with lockfile.open("w", encoding="utf-8") as lf:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    try:
                        with path.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            f.flush()
                    finally:
                        fcntl.flock(lf, fcntl.LOCK_UN)
        except OSError as e:
            self._log_error(f"审计写入失败: {e}")

    def _alert_failure(self, spec: str, event: str, action: str,
                       scope: str, detail: str) -> None:
        """动作失败 → 站内告警（D5，signal_type=hook_failure，severity major）。"""
        try:
            store = self.admin_store if self.admin_store is not None else AdminStore(self.project_root)
            store.append({
                "kind": ESCALATION,
                "signal_type": "hook_failure",
                "severity": "major",
                "spec": spec,
                "description": (
                    f"hook 动作失败：spec={spec} event={event} "
                    f"action={action} scope={scope}"
                ),
                "evidence": _truncate(detail),
                "recommended_action": (
                    "查看 .fenix/hook_audit.jsonl 与本条告警溯因；hook 动作失败不会自动重试"
                ),
            })
            self._log_warning(
                f"hook_failure: action={action} spec={spec} event={event} scope={scope}")
        except Exception as e:
            self._log_error(f"hook 失败告警写入失败: {type(e).__name__}: {e}")

    @property
    def project_name(self) -> str:
        """项目名（webhook payload 用）；config 缺省以项目根目录名兜底。"""
        if self._project_name is None:
            proj = self.config.get("project") if isinstance(self.config, dict) else None
            name = proj.get("name") if isinstance(proj, dict) else None
            self._project_name = name or self.project_root.name
        return self._project_name

    def _log_error(self, message: str) -> None:
        if self.logger is not None:
            try:
                self.logger.error("hook_engine", message)
                return
            except Exception:
                pass
        print(f"[hook_engine] ERROR {message}", flush=True)

    def _log_warning(self, message: str) -> None:
        if self.logger is not None:
            try:
                self.logger.warning("hook_engine", message)
                return
            except Exception:
                pass
        print(f"[hook_engine] WARNING {message}", flush=True)
