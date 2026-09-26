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

one-shot 重启 hook（hook-restart-once）：all-done → restart-daemon 触发成功后
写 `.fenix/hook_cleanup_request.json` 清理标记；daemon 重启后 HookEngine 于
启动时清扫标记并从项目级/用户级 config.yaml 摘除该 hook——挂一次触发一次，
不会每次全员收口都重启（再需重启重新挂 hook 即可）。

线程安全：审计写入带进程内线程锁 + 跨进程 fcntl.flock（风格对齐
admin_store 的 DisputeAuditStore 追加模式）。
"""

import fcntl
import json
import os
import shlex
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .admin_store import AdminStore, ESCALATION
from .state_machine import SpecStatus, StateParser

# ── 常量 ───────────────────────────────────────────────────────────

# 项目级伪事件（fix-hook-all-specs-done）：全部 SPEC 均处于成功终态时触发，
# 仅全局作用域匹配。供用户在项目级 hook 界面挂 restart-daemon 等
# 项目级收口动作——「全部 SPEC 自然收口后的安全重启点」。
HOOK_EVENT_ALL_DONE = "all-done"

# 成功终态集合：all-done 判定口径（与前端 PRIORITY_TERMINAL 一致）。
# blocked/bug-found/frozen 等非终态视为「仍有进行中」不触发。
SPEC_SUCCESS_TERMINAL = (SpecStatus.DONE, SpecStatus.PUSHED)

# one-shot 重启清理标记（hook-restart-once）：all-done → restart-daemon 触发
# 成功后写入；daemon 重启后 HookEngine 启动清扫消费此标记，从项目级/用户级
# config.yaml 摘除对应 hook，实现「挂一次、触发一次」。
HOOK_RESTART_CLEANUP_FILENAME = "hook_cleanup_request.json"

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

# 订阅事件类型 = 全部状态枚举（SpecStatus.ALL）+ 项目级伪事件 all-done
VALID_EVENTS = tuple(SpecStatus.ALL) + (HOOK_EVENT_ALL_DONE,)

# 超时缺省（D4：shell 缺省 60，webhook 缺省 10）
DEFAULT_SHELL_TIMEOUT_SECONDS = 60
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 10

# webhook url scheme 白名单：urlopen 支持 file://ftp:// 等 scheme，放行会把
# 本地/内网资源读入审计记录（响应体截 2KB 落 hook_audit.jsonl）——仅允许
# http/https，校验（validate_hook_entry）与执行侧（_action_webhook）双检。
WEBHOOK_ALLOWED_SCHEMES = ("http", "https")

# dashboard 重启探测（D4：保持 8787 端口；探测超时则失败告警）
DEFAULT_DASHBOARD_PORT = 8787
DEFAULT_DASHBOARD_SESSION = "fenix-dashboard"
DASHBOARD_PROBE_ATTEMPTS = 20
DASHBOARD_PROBE_INTERVAL = 0.5

# commit/commit-push 缺省提交范围（fix-hook-commit-pathsweep）：路径限定到
# 收口产物，杜绝状态 hook 自动提交/推送卷入工作区无关或敏感改动（对齐
# evolution._git_commit / archive_commit 的「MUST NOT git add -A」惯例）。
# 需要更大范围时在 hook 配置显式提供 paths 字段（如 paths: ["."]）。
DEFAULT_COMMIT_PATHS = ("spec", ".fenix/STATE.md")

# 审计 detail 截断（D6：≤2KB）
DETAIL_LIMIT = 2048

# 审计状态（D6）
STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"
STATUS_NOOP = "noop"
STATUS_SKIPPED = "skipped"

# 审计尾读参数（read_hook_audit）：审计文件 append-only 且无轮转，读取端
# 按块（64KB）从文件尾倒序回退，行数按 limit 的 8 倍超采样——过滤后仍可能
# 凑满 limit，避免全量读入随文件增长而开销失控。
AUDIT_TAIL_BLOCK_BYTES = 64 * 1024
AUDIT_TAIL_OVERSAMPLE = 8


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
    # 排除 bool（bool 是 int 子类，显式前判，对齐 _positive_int_or_default
    # 范式；否则 True 会被 float() 变 1.0 → 1 秒超时，False 被静默吞掉）
    if isinstance(value, bool):
        return default
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
    - events 非空列表，取值 ∈ VALID_EVENTS（SpecStatus.ALL + 伪事件 all-done，
      后者仅全局作用域生效）；
    - action ∈ 七枚举；
    - action=webhook 必须 url 非空字符串；
    - action=shell 必须 command 非空字符串；
    - action=commit/commit-push 可选 paths：非空字符串数组（git pathspec，
      缺省仅 DEFAULT_COMMIT_PATHS 收口产物）。

    Returns: 非法时返回错误描述（含字段路径），合法返回 None。
    """
    if not isinstance(entry, dict):
        return "hook 条目必须为对象"
    events = entry.get("events")
    if not isinstance(events, list) or not events:
        return "events 必须为非空数组（订阅的事件类型，取值为全部状态枚举 SpecStatus.ALL 之一）"
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
        scheme = urllib.parse.urlparse(url.strip()).scheme.lower()
        if scheme not in WEBHOOK_ALLOWED_SCHEMES:
            return (
                f"webhook url scheme 非法: {scheme or '(缺失)'}"
                f"（仅允许 {list(WEBHOOK_ALLOWED_SCHEMES)}，禁 file:// 等本地/内网协议）"
            )
    if action == "shell":
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            return "shell 动作必须提供非空 command"
    if action in ("commit", "commit-push") and entry.get("paths") is not None:
        paths = entry.get("paths")
        if (
            not isinstance(paths, list)
            or not paths
            or not all(isinstance(p, str) and p.strip() for p in paths)
        ):
            return "commit/commit-push 的 paths 必须为非空字符串数组（git pathspec，如 [\"spec\"]）"
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
    all-done 是项目级伪事件：仅全局作用域匹配（spec 级订阅被忽略）。
    """
    hooks = hook_config(config)
    matched: List[Tuple[dict, str]] = []
    # events 类型守卫：仅列表型 events 参与匹配。手写坏配置（如 events: done）
    # 若退化为字符串子串包含，"ne"/"on" 等无关事件也会命中，制造与配置意图
    # 无关的 failure 审计噪音（非法配置要到执行阶段 validate_hook_entry 才拦截）。
    for h in hooks.get("global") or []:
        evs = h.get("events") if isinstance(h, dict) else None
        if isinstance(evs, list) and event_type in evs:
            matched.append((h, "global"))
    if event_type == HOOK_EVENT_ALL_DONE:
        return matched
    spec_hooks = hooks.get("specs") or {}
    for h in spec_hooks.get(spec) or []:
        evs = h.get("events") if isinstance(h, dict) else None
        if isinstance(evs, list) and event_type in evs:
            matched.append((h, "spec"))
    return matched


def _read_audit_tail_lines(path: Path, min_lines: int) -> List[str]:
    """从文件尾按块倒序读取原始行，凑满 min_lines 行或到文件头即止。

    块边界切断的行按字节拼接还原，返回的行保持文件原始顺序（从头到尾）。
    仅当收集行数达 min_lines 时提前止步，此时文件更靠前的内容不读入。
    """
    lines: List[str] = []
    remainder = b""  # 块首被切断的半行（其行头在更靠前的块里），留给下一轮回拼
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        while pos > 0 and len(lines) < min_lines:
            read_size = min(AUDIT_TAIL_BLOCK_BYTES, pos)
            pos -= read_size
            f.seek(pos)
            parts = (f.read(read_size) + remainder).split(b"\n")
            # 块首（非文件头）可能切断一行：保留半行，其余均为完整行
            remainder = parts.pop(0) if pos > 0 else b""
            # [fenix-ignore:5c8668b8ae79] decode 已带 errors="replace"，且 read_hook_audit 的 except 已含 UnicodeDecodeError，条目描述的无容错 decode 与 OSError-only 捕获在当前代码中不存在
            lines.extend(p.decode("utf-8", errors="replace") for p in reversed(parts))
    lines.reverse()
    return lines


def read_hook_audit(project_root, spec: Optional[str] = None, limit: int = 20) -> list:
    """读取 .fenix/hook_audit.jsonl 尾部（D6 / tasks 1.3 / 4.1）。

    按 spec 过滤（spec=None 不过滤）、时间倒序、limit 截断；文件不存在/损坏返回 []。
    """
    path = Path(project_root) / ".fenix" / "hook_audit.jsonl"
    if not path.exists():
        return []
    out: list = []
    try:
        # 读取层：limit>0 时尾读 limit 的 8 倍行数即可（过滤/坏行冗余）；
        # limit<=0 语义为不截断返回全量，须整文件读入。
        if limit and limit > 0:
            raw_lines = _read_audit_tail_lines(path, limit * AUDIT_TAIL_OVERSAMPLE)
        else:
            raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict) and (spec is None or d.get("spec") == spec):
                out.append(d)
    except (OSError, UnicodeDecodeError):
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
        # all-done 去重（fix-hook-all-specs-done）：全员终态期间只发一次，
        # 任一 spec 离开终态即复位（见 dispatch）。进程内存态，重启自然复位。
        self._all_done_fired = False
        self._all_done_lock = threading.Lock()
        # 框架目录：core/hook_engine.py → 框架根（bin/fenix_dashboard.py 所在）
        self._framework_root = Path(__file__).resolve().parent.parent
        self._project_name = None
        # one-shot 清扫（hook-restart-once）：消费上次 all-done → restart-daemon
        # 触发遗留的清理标记，摘除对应 hook；失败仅告警不阻断 daemon 启动。
        try:
            self._consume_restart_cleanup()
        except Exception as e:
            self._log_warning(
                f"one-shot 重启 hook 清扫失败（hook 保留，下次启动重试）: "
                f"{type(e).__name__}: {e}"
            )

    # ── 事件分发（EventBus diff 处调用，只投递不阻塞）────────────────

    def dispatch(
        self, spec: str, from_status: Optional[str], to_status: str, entry: Optional[dict]
    ) -> None:
        """(spec, from, to, entry) 事件分发：匹配 + 每命中 hook 一个线程并发执行。

        分发阶段任何异常只记日志，不向调用方抛（状态机写入路径不被 hook 阻塞）。
        """
        try:
            matches = match_hooks(self.config, spec, to_status)
        except Exception as e:
            self._log_error(f"hook 匹配失败 spec={spec} event={to_status}: {type(e).__name__}: {e}")
            return
        try:
            for cfg, scope in matches:
                hook_id = cfg.get("id") if isinstance(cfg, dict) else None
                th = threading.Thread(
                    target=self._execute_one,
                    args=(hook_id, scope, spec, from_status, to_status, entry or {}, cfg),
                    name=f"hook-{hook_id or 'anon'}-{spec}",
                    daemon=True,
                )
                th.start()

            # 项目级 all-done 评估（fix-hook-all-specs-done）：迁移进成功终态时
            # 检查全员是否收口；迁移到任何非终态则复位去重标志（打回后再收口
            # 可再次触发）。
            if to_status in SPEC_SUCCESS_TERMINAL:
                self._maybe_dispatch_all_done(spec)
            else:
                with self._all_done_lock:
                    self._all_done_fired = False
        except Exception as e:
            self._log_error(
                f"hook 投递失败（不向调用方抛）spec={spec} event={to_status}: "
                f"{type(e).__name__}: {e}"
            )

    # ── 项目级 all-done（fix-hook-all-specs-done）────────────────────

    def _maybe_dispatch_all_done(self, trigger_spec: str) -> None:
        """终态迁移时评估「全部 SPEC 均完成」：是则以 all-done 触发全局 hook。

        - 口径：STATE.md 全部条目 status ∈ (done, pushed)——blocked/bug-found/
          frozen 等一律视为「仍有进行中」不触发（STATE 由状态机先行落盘，
          EventBus 派发读到的必为迁移后状态）；
        - 去重：全员终态期间只发一次（内存标志），任一 spec 离开终态即复位；
        - 触发 spec 以 "*" 记审计（项目级语义），trigger_spec 入 entry 供
          webhook/shell 溯源。
        """
        try:
            entries = StateParser.parse(self.project_root / ".fenix" / "STATE.md")
        except Exception as e:
            self._log_warning(f"all-done 评估失败（跳过）: {e}")
            return
        if not entries:
            return
        if any(e.get("status") not in SPEC_SUCCESS_TERMINAL for e in entries.values()):
            return
        with self._all_done_lock:
            if self._all_done_fired:
                return
            self._all_done_fired = True
        try:
            for cfg, scope in match_hooks(self.config, "*", HOOK_EVENT_ALL_DONE):
                hook_id = cfg.get("id") if isinstance(cfg, dict) else None
                th = threading.Thread(
                    target=self._execute_one,
                    args=(
                        hook_id,
                        scope,
                        "*",
                        None,
                        HOOK_EVENT_ALL_DONE,
                        {"trigger_spec": trigger_spec},
                        cfg,
                    ),
                    name=f"hook-{hook_id or 'anon'}-all-done",
                    daemon=True,
                )
                th.start()
        except Exception as e:
            self._log_error(f"all-done hook 投递失败（不向调用方抛）: {type(e).__name__}: {e}")

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

    def _execute_one(
        self,
        hook_id,
        scope: str,
        spec: str,
        from_status: Optional[str],
        to_status: str,
        entry: dict,
        matched_cfg: Optional[dict] = None,
    ) -> None:
        """单条 hook 的执行线程：实时重读配置、enabled 判 skip、执行、审计。

        单 hook 异常互不影响（线程级 try 全包裹，失败走 failure 审计+告警）。
        无 id 的手写 hook（validate_hook_entry 允许缺省 id 的受支持形态）无法
        按 id 重查实时配置，按投递时命中的原始配置 matched_cfg 执行并照常写
        审计；带 id 条目在投递与执行间隙被删除仍静默跳过（不写审计）。
        """
        try:
            cfg = self._find_live_hook(hook_id, scope, spec)
            if cfg is None:
                if not hook_id and isinstance(matched_cfg, dict):
                    cfg = matched_cfg
                else:
                    return
            if not cfg.get("enabled", True):
                self._audit(
                    spec,
                    to_status,
                    from_status,
                    to_status,
                    hook_id,
                    cfg.get("action"),
                    scope,
                    STATUS_SKIPPED,
                    "enabled=false，已跳过",
                    0.0,
                )
                return
            err = validate_hook_entry(cfg)
            if err:
                # 配置被手工改坏：记 failure 但不告警（配置层错误，审计暴露）
                self._audit(
                    spec,
                    to_status,
                    from_status,
                    to_status,
                    hook_id,
                    cfg.get("action"),
                    scope,
                    STATUS_FAILURE,
                    f"hook 配置非法（不执行）: {err}",
                    0.0,
                )
                return
            self._execute_action(cfg, scope, spec, from_status, to_status, entry)
        except Exception as e:
            detail = f"hook 执行异常: {type(e).__name__}: {e}"
            try:
                self._audit(
                    spec,
                    to_status,
                    from_status,
                    to_status,
                    hook_id,
                    "?",
                    scope,
                    STATUS_FAILURE,
                    detail,
                    0.0,
                )
                self._alert_failure(spec, to_status, "?", scope, detail)
            except Exception:
                pass

    def _execute_action(
        self,
        cfg: dict,
        scope: str,
        spec: str,
        from_status: Optional[str],
        to_status: str,
        entry: dict,
    ) -> None:
        """按动作类型执行并统一写审计；失败再发站内告警（D5，不重试）。"""
        action = cfg["action"]
        hook_id = cfg.get("id")
        started = time.monotonic()

        if action == "restart-daemon":
            ok, detail = self._action_restart_daemon()
            status = STATUS_SUCCESS if ok else STATUS_FAILURE
            # one-shot（hook-restart-once）：仅 all-done 触发且 hook 有 id 时写
            # 清理标记。标记失败不降级本次成功（hook 留存，下一轮收口再触发）；
            # 无 id 的手写 hook 无法定位摘除目标，保持常驻旧语义。
            if ok and to_status == HOOK_EVENT_ALL_DONE and hook_id:
                mark_err = self._mark_restart_cleanup(hook_id)
                detail = (
                    f"{detail}；清理标记写入失败（hook 保留）: {mark_err}"
                    if mark_err
                    else f"{detail}（one-shot：重启后本 hook 将自动清理）"
                )
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
        self._audit(
            spec,
            to_status,
            from_status,
            to_status,
            hook_id,
            action,
            scope,
            status,
            detail,
            duration,
        )
        if status == STATUS_FAILURE:
            self._alert_failure(spec, to_status, action, scope, detail)

    # ── 七种动作（D4） ──────────────────────────────────────────────

    def _action_restart_daemon(self) -> Tuple[bool, str]:
        """touch .fenix/restart_request，复用 supervisor 优雅重启协议。

        fix-supervisor-hosting-chain D4：写请求前先校验该项目 supervisor 存在；
        不存在时复用 `_alert_failure` 链路走 failure（不再报假成功），detail 含
        「无 supervisor，重启请求不会被消费」。
        """
        try:
            from core.fenix_session import supervisor_running
        except ImportError:
            supervisor_running = None
        if supervisor_running is not None:
            try:
                if not supervisor_running(self.project_root):
                    return False, (
                        "本项目无 supervisor，重启请求不会被消费："
                        ".fenix/restart_request 未写入。经 Dashboard 项目页"
                        "「安装托管」或 /fenix-setup 恢复 supervisor 托管后重试"
                    )
            except Exception:
                pass  # 判定异常：按旧行为继续写入，不卡死 hook
        req = self.project_root / ".fenix" / "restart_request"
        try:
            req.parent.mkdir(parents=True, exist_ok=True)
            req.touch()
            return True, "restart_request 已写入（supervisor 将执行优雅重启）"
        except OSError as e:
            return False, f"touch .fenix/restart_request 失败: {e}"

    # ── one-shot 重启 hook（hook-restart-once）──────────────────────

    def _mark_restart_cleanup(self, hook_id) -> Optional[str]:
        """all-done → restart-daemon 触发成功后写清理标记。

        fcntl 锁内读-改-写合并 hook_ids（多个 all-done 重启 hook 并发触发不
        互吞），临时文件 + rename 原子落盘（防 supervisor SIGKILL 截断出
        半截 JSON）。返回 None 成功，否则错误描述。
        """
        path = self.project_root / ".fenix" / HOOK_RESTART_CLEANUP_FILENAME
        lockfile = Path(str(path) + ".lock")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with lockfile.open("w", encoding="utf-8") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    ids: List[str] = []
                    if path.exists():
                        try:
                            data = json.loads(path.read_text(encoding="utf-8"))
                            raw = data.get("hook_ids") if isinstance(data, dict) else None
                            ids = [str(x) for x in raw if x] if isinstance(raw, list) else []
                        except (json.JSONDecodeError, OSError):
                            ids = []  # 半截/损坏标记：重建即可
                    hid = str(hook_id or "")
                    if hid and hid not in ids:
                        ids.append(hid)
                    payload = {"ts": _utcnow_iso(), "hook_ids": ids}
                    tmp = path.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(path)
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)
            return None
        except OSError as e:
            return f"标记写入失败: {e}"

    def _consume_restart_cleanup(self) -> None:
        """启动清扫（hook-restart-once）：消费清理标记，摘除已触发过的重启 hook。

        项目级与用户级 config.yaml 分别读-改-写（不用合并视图回写，避免把
        用户级 hooks 复制进项目文件）；内存视图同步过滤，热更新从已清理
        磁盘重收敛前保持一致。无标记 no-op；标记删除放最后且仅在配置摘除
        全部成功时执行——摘除有文件失败则保留标记待下次启动幂等重扫，
        删标记失败同理（ids 已不在，重扫等价 noop）。
        """
        path = self.project_root / ".fenix" / HOOK_RESTART_CLEANUP_FILENAME
        if not path.exists():
            return
        hook_ids: set = set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data.get("hook_ids") if isinstance(data, dict) else None
            hook_ids = {str(x) for x in raw if x} if isinstance(raw, list) else set()
        except (json.JSONDecodeError, OSError) as e:
            self._log_warning(f"hook 清理标记损坏，跳过清扫: {e}")
            return
        if hook_ids:
            changed, failed = self._remove_hook_ids_from_config_files(hook_ids)
            self._remove_hook_ids_from_memory(hook_ids)
            if failed:
                self._log_warning(
                    f"one-shot 重启 hook 清扫: 摘除 {sorted(hook_ids)} 时"
                    f" {failed} 个配置文件读改失败（已改 {changed} 个），"
                    f"保留清理标记待下次启动重试"
                )
                return
            self._log_warning(
                f"one-shot 重启 hook 清扫: 已从配置摘除 {sorted(hook_ids)}"
                f"（改动 {changed} 个配置文件）"
            )
        else:
            self._log_warning("hook 清理标记为空，按 noop 消费")
        try:
            path.unlink()
        except OSError as e:
            self._log_warning(f"hook 清理标记删除失败（下次启动重试）: {e}")

    def _hook_config_paths(self) -> List[Path]:
        """清理涉及的两级配置文件路径（用户级优先，均可能不存在）。"""
        paths: List[Path] = []
        try:
            from .config import USER_CONFIG_DIR

            paths.append(USER_CONFIG_DIR / "config.yaml")
        except Exception:
            pass
        paths.append(self.project_root / ".fenix" / "config.yaml")
        return paths

    @staticmethod
    def _split_yaml_header(raw: str) -> str:
        """取文件头部连续注释/空行块原样保留（safe_dump 会丢弃注释）。"""
        header: List[str] = []
        for line in raw.splitlines(keepends=True):
            if line.strip() == "" or line.lstrip().startswith("#"):
                header.append(line)
            else:
                break
        return "".join(header)

    def _remove_hook_ids_from_config_files(self, hook_ids: set) -> Tuple[int, int]:
        """从两级 config.yaml 的 hooks 段按 id 摘除条目。

        返回 (changed, failed)：changed 为实际改写文件数；failed 为清扫
        未完成的文件数（读/解析/写回失败——该文件是否残留待摘 id 无法
        确认，调用方据此保留清理标记待下次启动重试）。
        """
        import yaml

        changed = 0
        failed = 0
        for cfg_path in self._hook_config_paths():
            try:
                if not cfg_path.exists():
                    continue
                raw = cfg_path.read_text(encoding="utf-8")
                data = yaml.safe_load(raw)
                hooks = data.get("hooks") if isinstance(data, dict) else None
                if not isinstance(hooks, dict):
                    continue
                dirty = False
                g = hooks.get("global")
                if isinstance(g, list):
                    kept = [h for h in g if not (isinstance(h, dict) and h.get("id") in hook_ids)]
                    if kept != g:
                        hooks["global"] = kept
                        dirty = True
                specs = hooks.get("specs")
                if isinstance(specs, dict):
                    for name, lst in list(specs.items()):
                        if not isinstance(lst, list):
                            continue
                        kept = [
                            h for h in lst if not (isinstance(h, dict) and h.get("id") in hook_ids)
                        ]
                        if kept != lst:
                            specs[name] = kept
                            dirty = True
                if not dirty:
                    continue
                # mkstemp(0600) + os.replace 原子写回（对齐 config_admin.write_config
                # 模式），并把 tmp 权限收敛回原文件 mode——经 dashboard 保存过的
                # config.yaml（含 llm providers apikey 等敏感字段）为 0600，
                # 不能被 umask 缺省权限放宽成 0644。
                mode = cfg_path.stat().st_mode & 0o7777
                fd, tmp_name = tempfile.mkstemp(
                    dir=str(cfg_path.parent), prefix=".config-", suffix=".yaml.tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(
                            self._split_yaml_header(raw)
                            + yaml.safe_dump(
                                data, allow_unicode=True, default_flow_style=False, sort_keys=False
                            )
                        )
                    os.chmod(tmp_name, mode)
                    os.replace(tmp_name, cfg_path)
                except Exception:
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                    raise
                changed += 1
            except (OSError, yaml.YAMLError) as e:
                failed += 1
                self._log_warning(f"hook 清扫读改 {cfg_path} 失败: {e}")
        return changed, failed

    def _remove_hook_ids_from_memory(self, hook_ids: set) -> None:
        """内存合并视图同步过滤（热更新从已清理磁盘重收敛前保持一致）。"""
        hooks = self.config.get("hooks") if isinstance(self.config, dict) else None
        if not isinstance(hooks, dict):
            return
        g = hooks.get("global")
        if isinstance(g, list):
            hooks["global"] = [
                h for h in g if not (isinstance(h, dict) and h.get("id") in hook_ids)
            ]
        specs = hooks.get("specs")
        if isinstance(specs, dict):
            for name, lst in list(specs.items()):
                if isinstance(lst, list):
                    specs[name] = [
                        h for h in lst if not (isinstance(h, dict) and h.get("id") in hook_ids)
                    ]

    def _resolve_commit_paths(self, cfg: dict) -> List[str]:
        """解析 commit/commit-push 的 add/commit pathspec（缺省仅收口产物）。

        hook 配置 paths 字段为非空字符串列表时原样采用（用户显式扩大范围）；
        否则用 DEFAULT_COMMIT_PATHS 过滤——仅保留磁盘存在或已有跟踪文件的
        路径，规避「pathspec matches nothing」令整条 git add fatal（同
        archive_commit 的处理）。
        """
        configured = cfg.get("paths")
        if isinstance(configured, list) and configured and all(
            isinstance(p, str) and p.strip() for p in configured
        ):
            return [p.strip() for p in configured]
        paths: List[str] = []
        for p in DEFAULT_COMMIT_PATHS:
            if (self.project_root / p).exists():
                paths.append(p)
                continue
            try:
                tracked = _run_git(["ls-files", "--", p], self.project_root)
            except (subprocess.SubprocessError, OSError):
                continue
            if tracked.stdout.strip():
                paths.append(p)
        return paths

    def _action_commit(self, cfg: dict, spec: str, event: str) -> Tuple[str, str]:
        """路径限定提交（缺省仅收口产物，paths 字段可显式扩大）；无变更 → noop。

        add 与 commit 均以同一 pathspec 限定，确保索引中残留的其他暂存内容
        不会被裹挟进本条提交（对齐 evolution._git_commit 惯例）。
        """
        message = render_message_template(cfg.get("message") or "", spec, event)
        paths = self._resolve_commit_paths(cfg)
        if not paths:
            return STATUS_NOOP, "无变更（无可提交的收口产物路径；需更大范围请配置 paths）"
        try:
            add = _run_git(["add", "-A", "--"] + paths, self.project_root)
        except (subprocess.SubprocessError, OSError) as e:
            return STATUS_FAILURE, f"git add 执行失败: {e}"
        if add.returncode != 0:
            return STATUS_FAILURE, f"git add 失败: {_tail_combined(add.stdout, add.stderr)}"
        try:
            quiet = _run_git(["diff", "--cached", "--quiet", "--"] + paths, self.project_root)
        except (subprocess.SubprocessError, OSError) as e:
            return STATUS_FAILURE, f"git diff 执行失败: {e}"
        if quiet.returncode == 0:
            return STATUS_NOOP, "无变更（nothing to commit）"
        try:
            res = _run_git(["commit", "-m", message, "--"] + paths, self.project_root)
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
            has = subprocess.run(
                ["tmux", "has-session", "-t", target], capture_output=True, text=True, timeout=10
            )
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
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.SubprocessError, OSError) as e:
            return False, f"tmux respawn-window 失败: {e}"
        if respawn.returncode != 0:
            return (
                False,
                f"tmux respawn-window 失败: {_tail_combined(respawn.stdout, respawn.stderr)}",
            )
        port = self._dashboard_port()
        if not self._probe_dashboard(port):
            # 上限按每轮 urlopen timeout=2s + 间隔 DASHBOARD_PROBE_INTERVAL 估算（对应 _probe_dashboard）
            return (
                False,
                f"dashboard 已 respawn，但 {port} 端口最坏 {DASHBOARD_PROBE_ATTEMPTS * (2 + DASHBOARD_PROBE_INTERVAL):.0f}s 内未恢复 HTTP 可服务",
            )
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

    def _action_webhook(
        self, cfg: dict, spec: str, from_status: Optional[str], to_status: str, entry: dict
    ) -> Tuple[str, str]:
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
        # 执行侧复检 scheme（校验只把守配置写入路径，直改 config.yaml 可绕过）
        scheme = urllib.parse.urlparse(url).scheme.lower()
        if scheme not in WEBHOOK_ALLOWED_SCHEMES:
            return STATUS_FAILURE, (
                f"webhook url scheme 非法: {scheme or '(缺失)'}"
                f"（仅允许 {list(WEBHOOK_ALLOWED_SCHEMES)}）"
            )
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
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
        detail = (
            _truncate(body.decode("utf-8", errors="replace"))
            if body
            else "webhook 已送达（空响应）"
        )
        return STATUS_SUCCESS, detail

    def _action_shell(
        self, cfg: dict, spec: str, from_status: Optional[str], to_status: str, entry: dict
    ) -> Tuple[str, str]:
        """bash -c <command>，注入事件环境变量，超时按进程组强杀。"""
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
            # start_new_session：bash 为新进程组首，超时可 killpg 连孙进程一并回收
            proc = subprocess.Popen(
                ["bash", "-c", command],
                cwd=str(self.project_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                out, err = proc.communicate()
                detail = f"shell 超时（>{timeout:.0f}s）已按进程组强杀"
                tail = _tail_combined(out or "", err or "")
                return STATUS_FAILURE, f"{detail}{('：' + tail) if tail else ''}"
        except OSError as e:
            return STATUS_FAILURE, f"shell 执行失败: {e}"
        if proc.returncode != 0:
            return STATUS_FAILURE, (
                f"退出码 {proc.returncode}: {_tail_combined(out, err)}"
            )
        tail = _tail_combined(out, err)
        return STATUS_SUCCESS, tail or "退出码 0"

    # ── 审计与告警（D5/D6） ─────────────────────────────────────────

    def _audit(
        self,
        spec: str,
        event: str,
        from_status: Optional[str],
        to_status: Optional[str],
        hook_id,
        action,
        scope: str,
        status: str,
        detail: str,
        duration_s: float,
    ) -> None:
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

    def _alert_failure(self, spec: str, event: str, action: str, scope: str, detail: str) -> None:
        """动作失败 → 站内告警（D5，signal_type=hook_failure，severity major）。"""
        try:
            store = (
                self.admin_store if self.admin_store is not None else AdminStore(self.project_root)
            )
            store.append(
                {
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
                }
            )
            self._log_warning(
                f"hook_failure: action={action} spec={spec} event={event} scope={scope}"
            )
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
