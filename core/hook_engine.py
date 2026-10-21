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
import http.client
import json
import math
import os
import shlex
import signal
import subprocess
import sys
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
from .proc_utils import guard_killpg

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
# 强杀后回收进程的兜底超时：守护化孙进程（setsid 脱离进程组）继承管道时
# killpg 收不掉，communicate 会因管道未关闭无限阻塞
SHELL_KILL_REAP_TIMEOUT_SECONDS = 5

# timeout_seconds 量级上限（code-review item afb00545e096）：bool/非正/非有限
# 值已有校验层与执行侧 _num 双层拦截，但有限大值（如毫秒语义误写
# 86400000≈1000 天）可穿透 v > 0 守卫，shell communicate(timeout) 会如实阻塞
# 该时长——在飞标记不释放、同 id hook 后续事件被在飞去重静默跳过、线程长期
# 泄漏。校验层超限按配置非法拒绝、执行层超限收敛到上限，分层防线口径对齐
# scenarios.MAX_STEP_TIMEOUT（量级取宽松一档：单次 hook 允许到小时级）。
MAX_HOOK_TIMEOUT_SECONDS = 3600  # 1 小时

# webhook url scheme 白名单：urlopen 支持 file://ftp:// 等 scheme，放行会把
# 本地/内网资源读入审计记录（响应体截 2KB 落 hook_audit.jsonl）——仅允许
# http/https，校验（validate_hook_entry）与执行侧（_action_webhook）双检。
WEBHOOK_ALLOWED_SCHEMES = ("http", "https")


class _WebhookRedirectGuard(urllib.request.HTTPRedirectHandler):
    """重定向前复查目标 scheme 的守卫 handler（口径对齐 WEBHOOK_ALLOWED_SCHEMES）。

    默认 opener 的重定向跟随不限制目标 scheme：webhook 端点返回 302 →
    file:///... 会被 FileHandler 跟随读取（响应体截 2KB 落审计），绕过白名单。
    此 handler 在每跳跟随前复查，越界（file://ftp:// 等）关流不跟随，按请求
    失败处置（URLError 走 _action_webhook 既有 except 分支）。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlparse(newurl).scheme.lower()
        if scheme not in WEBHOOK_ALLOWED_SCHEMES:
            try:
                fp.close()
            except OSError:
                pass
            raise urllib.error.URLError(
                f"webhook 重定向目标 scheme 非法: {scheme or '(缺失)'}"
                f"（仅允许 {list(WEBHOOK_ALLOWED_SCHEMES)}）"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# webhook 专用 opener（模块级复用，与 urlopen 内置全局 opener 同口径）：
# 守卫 handler 是 HTTPRedirectHandler 子类，build_opener 以其替换默认跟随
_WEBHOOK_OPENER = urllib.request.build_opener(_WebhookRedirectGuard())

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

# 审计 detail 截断（D6：≤2048 字符，按字符计而非 UTF-8 字节）
DETAIL_LIMIT = 2048

# 审计状态（D6）
STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"
STATUS_NOOP = "noop"
STATUS_SKIPPED = "skipped"

# 内置默认 hook 条目 id（dashboard-push-restart D1）：SPEC pushed 终态自动重启
# dashboard。由 hook_config() 读侧注入返回副本（零配置生效），不落 config 文件。
BUILTIN_PUSH_RESTART_DASHBOARD_ID = "builtin-push-restart-dashboard"

# restart-dashboard 动作去抖窗口（dashboard-push-restart D2）：push 批次常见
# 同窗口多笔 pushed（如同日多个 verification-report 入库），窗口内重复触发
# 幂等跳过。取值依据：dashboard 重启+端口就绪 ~3-5s，窗口远大于单次重启耗时。
DASHBOARD_RESTART_DEBOUNCE_SECONDS = 60.0

# 审计尾读参数（read_hook_audit）：审计文件 append-only 且无轮转，读取端
# 按块（64KB）从文件尾倒序回退，行数按 limit 的 8 倍超采样——过滤后仍可能
# 凑满 limit，避免全量读入随文件增长而开销失控。
AUDIT_TAIL_BLOCK_BYTES = 64 * 1024
AUDIT_TAIL_OVERSAMPLE = 8


def _utcnow_iso() -> str:
    """UTC ISO 时间戳（Z 后缀，与既有日志格式一致）。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate(text: str, limit: int = DETAIL_LIMIT) -> str:
    """截断到 limit 字符（D6 审计上限按字符计，非 UTF-8 字节），保留头部。"""
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…(截断)"


def _num(value, default: float) -> float:
    """数值兜底：非法/非正数回退缺省，超上限收敛到 MAX_HOOK_TIMEOUT_SECONDS。"""
    # 排除 bool（bool 是 int 子类，显式前判，对齐 _positive_int_or_default
    # 范式；否则 True 会被 float() 变 1.0 → 1 秒超时，False 被静默吞掉）
    if isinstance(value, bool):
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    # isfinite：排除 ±inf（YAML .inf、溢出字面量 1e400、字符串 "inf" 经
    # float() 变 inf，可穿透 v > 0 守卫），否则 shell/webhook timeout=inf
    # 永不超时、在飞标记不释放（对齐 config.py 的 .nan/.inf 守卫先例；
    # nan 已被 v > 0 排除，此处一并兜住）
    if not (v > 0 and math.isfinite(v)):
        return default
    # 量级上限（code-review item afb00545e096）：有限大值可穿透上方守卫，
    # communicate(timeout)/urlopen(timeout) 会如实阻塞该时长、在飞标记长期
    # 不释放——收敛到上限（收敛 ≠ 报错，直改 config.yaml 的存量配置不因
    # 执行侧硬失败）；超限留痕由 _action_webhook/_action_shell 记 debug 日志
    return min(v, MAX_HOOK_TIMEOUT_SECONDS)


def _tail_combined(stdout: Optional[str], stderr: Optional[str]) -> str:
    """合并 stdout+stderr 尾部（shell/commit 输出入审计）。"""
    parts = [s for s in (stdout, stderr) if s and s.strip()]
    if not parts:
        return ""
    return _truncate("\n".join(p.strip() for p in parts)[-DETAIL_LIMIT:], DETAIL_LIMIT)


def _terminate_proc_group(proc: subprocess.Popen) -> Tuple[str, str]:
    """超时强杀进程组并回收（_run_git 与 _action_shell 共享的收尾实现）。

    killpg(SIGKILL) 经自保护守卫连孙进程一并回收（守卫拒绝或组已不存在时
    静默返回，MUST NOT 再降级单 pid proc.kill）；复杀后 communicate 仍超时
    ——守护化孙进程（setsid 脱离进程组）继承管道且杀不掉——则关闭读端放弃
    读取，保证执行线程必然返回。返回已收集的 (out, err)，管道被放弃时为
    ("", "")。
    """
    # 击杀经自保护守卫（add-killpg-self-guard，resolve 型）：getpgid 内联点
    # 收口；守卫拒绝（自身组/非正 pgid）与组已不存在同样静默——MUST NOT
    # 降级单 pid proc.kill（pid=0 经 os.kill 折算同为调用者自身组广播）。
    guard_killpg(
        proc.pid, signal.SIGKILL, caller="hook_engine._terminate_proc_group", resolve=True
    )
    try:
        return proc.communicate(timeout=SHELL_KILL_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        for _stream in (proc.stdout, proc.stderr):
            try:
                if _stream:
                    _stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=SHELL_KILL_REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return "", ""


def _traverses_symlink_dir(root: Path, rel: str) -> bool:
    """词法相对路径 rel 的目录分量（不含末段）是否含软链。

    子项目布局中项目内 `.fenix/` 是指向框架主树的软链（fenix_session.
    _normalize docstring）：磁盘上 `.fenix/STATE.md` 经软链恒 exists()，但
    git 视 `.fenix` 为单个 symlink 文件、不沿目录软链枚举工作区——pathspec
    `.fenix/STATE.md` 恒「did not match any files」，单一坏 pathspec 即令
    整条 git add fatal。故磁盘存在性之外还需此类路径可被 git pathspec
    解析：逐段（不 resolve()，避免被软链牵回主树误判）检查目录分量是否
    软链，含软链即不可解析。实体目录形态不受影响（逐段均非软链）。
    """
    cur = root
    for comp in Path(rel).parts[:-1]:
        cur = cur / comp
        if cur.is_symlink():
            return True
    return False


def _run_git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """在项目根执行 git 子命令（统一超时 60s，不消费 hook 的 timeout_seconds 配置）。

    timeout_seconds 仅对 shell/webhook 生效（validate_hook_entry 已明示）；git
    动作按单一固定上限收口（commit-push 一条 hook 串行多个 git 子命令，逐段
    消费配置超时会使总时长无界）。

    有界 spawn 口径对齐 _action_shell：start_new_session 使 git 为新进程组首，
    超时经 _terminate_proc_group 强杀进程组回收（连项目级 hook / credential
    helper / gpg pinentry 等孙进程一并收掉，复杀仍超时再关流兜底）——否则孙
    进程继承 stdout/stderr 管道可致 hook 执行线程挂死、在飞标记永不释放。
    超时仍抛 TimeoutExpired（与 subprocess.run 同契约，调用方按
    SubprocessError 记失败）。
    """
    proc = subprocess.Popen(
        ["git"] + args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # 非 UTF-8 输出以替换符容错解码，不抛 UnicodeDecodeError：各动作的
        # 捕获口径为 (SubprocessError, OSError)，解码异常会穿到通用兜底、
        # 使审计归因降级为「hook 执行异常」而非具体 git 段失败
        errors="replace",
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        _terminate_proc_group(proc)
        raise
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def render_message_template(template: str, spec: str, event: str) -> str:
    """渲染提交信息模板（D4：未知变量原样保留，不致命）。

    支持的模板变量：{spec} / {event}。缺省模板 `[fenix] hook: {spec} {event}`。
    """
    if not template:
        return f"[fenix] hook: {spec} {event}"
    out = template.replace("{spec}", spec).replace("{event}", event)
    return out


def _builtin_push_restart_entry() -> dict:
    """内置默认条目（dashboard-push-restart D1）：pushed → restart-dashboard。

    global 作用域（对任意 SPEC 生效）；形态与用户手写条目一致，注入后经执行链
    validate_hook_entry 校验天然合法，_find_live_hook 经同一 hook_config 按 id
    找回执行，无需旁路。
    """
    return {
        "id": BUILTIN_PUSH_RESTART_DASHBOARD_ID,
        "enabled": True,
        "events": ["pushed"],
        "action": "restart-dashboard",
    }


def hook_config(config: dict) -> dict:
    """返回配置中的 hooks 段（缺省空结构，不修改入参）。

    dashboard-push-restart D1：返回副本在 global 段头部注入内置默认条目
    ``builtin-push-restart-dashboard``（pushed → restart-dashboard），新项目
    零配置即生效；逃生键 ``hooks.push_restart_dashboard: false`` 时跳过注入；
    用户 global 列表已有同 id 条目时用户条目优先（不重复注入）。

    注入作用于返回副本（重建 global 列表，条目引用原样共享；逃生键/同 id
    早退路径同样浅拷贝返回，全部返回路径与入参顶层脱钩），MUST NOT 原地
    mutate 入参：match_hooks/_find_live_hook 每次事件都重复调用本函数，原地
    注入会逐次堆叠重复条目；且入参引用若被任何 config 写链路序列化，内置条目
    会被持久化进 .fenix/config.yaml，此后逃生键置 false 也无法阻止重启（文件
    里已有实体条目），直接违背「读侧注入，不改 config 文件」。
    """
    hooks = config.get("hooks") if isinstance(config, dict) else None
    if not isinstance(hooks, dict):
        # 无 hooks 段：零配置默认也生效——返回含内置条目的新结构（不写回入参）
        return {"global": [_builtin_push_restart_entry()], "specs": {}}
    user_global = hooks.get("global")
    if not isinstance(user_global, list):
        user_global = []
    # 逃生键：bool 键缺省 true，仅显式 false 关闭（非法值按缺省开启，对齐
    # knowledge.enabled 等既有 bool 键口径）
    if hooks.get("push_restart_dashboard") is False:
        return dict(hooks)  # 浅拷贝脱钩：与注入路径同口径，返回值不回流入参
    if any(
        isinstance(h, dict) and h.get("id") == BUILTIN_PUSH_RESTART_DASHBOARD_ID
        for h in user_global
    ):
        return dict(hooks)  # 用户已有同 id 条目：用户条目优先，不重复注入；浅拷贝脱钩
    return {**hooks, "global": [_builtin_push_restart_entry(), *user_global]}


def validate_hook_entry(entry: Any) -> Optional[str]:
    """校验单条 hook 配置（tasks 1.1 / D7）。

    规则：
    - 必须为 dict；
    - id 缺省或字符串：非字符串（手改 config.yaml 写成 list/dict 等 unhashable
      值）会在执行线程在飞去重的集合操作处抛 TypeError，且该调用位于线程 try
      保护之外，异常将无审计终结线程，故在配置层按「配置非法（不执行）」拦截；
    - events 非空列表，取值 ∈ VALID_EVENTS（SpecStatus.ALL + 伪事件 all-done，
      后者仅全局作用域生效）；
    - action ∈ 七枚举；
    - action=webhook 必须 url 非空字符串；
    - action=shell 必须 command 非空字符串；
    - action=commit/commit-push 可选 paths：非空字符串数组（git pathspec，
      缺省仅 DEFAULT_COMMIT_PATHS 收口产物）；
    - action=commit/commit-push 可选 message：字符串（提交信息模板，支持
      {spec}/{event} 变量）——非字符串会在执行侧 render_message_template 的
      template.replace 处抛 AttributeError，被兜底误记为「hook 执行异常」major
      告警，故在配置层按「配置非法（不执行）」拦截；
    - action=restart-dashboard 可选 target：字符串（tmux 会话名，缺省
      fenix-dashboard）——非字符串（如手改 config.yaml 写成数字）会在执行
      侧 (target or "").strip() 抛 AttributeError，被兜底误记为「hook 执行
      异常」告警，故在配置层按「配置非法（不执行）」拦截；
    - 可选 timeout_seconds：正的有限数值（秒）且 ≤ MAX_HOOK_TIMEOUT_SECONDS，
      bool/非有限值（.inf 等非法，防手改 config.yaml 绕过执行侧 _num 守卫）
      与超上限的有限大值（执行侧会如实阻塞该时长、在飞标记不释放）均按配置
      非法——仅对 shell/webhook 生效；
      commit/push/commit-push 走 _run_git 固定 60s 超时，不消费该字段（给
      git 动作配更长超时不会被采纳，勿据此排期长耗时 git 操作）。

    Returns: 非法时返回错误描述（含字段路径），合法返回 None。
    """
    if not isinstance(entry, dict):
        return "hook 条目必须为对象"
    hook_id = entry.get("id")
    # 缺省/None 合法（无 id 手写 hook 为受支持形态），仅拦非字符串类型
    if hook_id is not None and not isinstance(hook_id, str):
        return f"id 必须为字符串（缺省允许），收到 {hook_id!r}"
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
    if action in ("commit", "commit-push") and entry.get("message") is not None:
        message = entry.get("message")
        # 缺省/None/空串 合法（执行侧 render_message_template 回退缺省模板），
        # 仅拦非字符串类型（口径对齐 restart-dashboard 的 target 拦截）
        if not isinstance(message, str):
            return (
                f"commit/commit-push 的 message 必须为字符串"
                f"（提交信息模板，支持 {{spec}}/{{event}} 变量），收到 {message!r}"
            )
    if action == "restart-dashboard":
        target = entry.get("target")
        # 缺省/None 合法（执行侧回退 DEFAULT_DASHBOARD_SESSION）；空串同样
        # 合法（执行侧 (target or "").strip() 等价缺省），仅拦非字符串类型
        if target is not None and not isinstance(target, str):
            return (
                f"restart-dashboard 的 target 必须为字符串（tmux 会话名，"
                f"缺省 {DEFAULT_DASHBOARD_SESSION}），收到 {target!r}"
            )
    timeout = entry.get("timeout_seconds")
    if timeout is not None:
        # 数值合法性（对齐 _num 语义）：非有限值（.inf/1e400/"inf"）会穿透
        # 执行侧 v > 0 守卫致超时永不触发；bool 同 _num 前判显式排除
        if isinstance(timeout, bool):
            return "timeout_seconds 必须为正的有限数值（秒），收到布尔值"
        try:
            timeout_v = float(timeout)
        except (TypeError, ValueError):
            return f"timeout_seconds 必须为正的有限数值（秒），收到 {timeout!r}"
        if not math.isfinite(timeout_v) or timeout_v <= 0:
            return f"timeout_seconds 必须为正的有限数值（秒），收到 {timeout!r}"
        # 量级上限（code-review item afb00545e096）：有限大值（如毫秒语义误写
        # 86400000≈1000 天）穿透上方守卫后，hook 线程会如实阻塞该时长、在飞
        # 标记不释放，同 id hook 后续事件被在飞去重静默跳过（执行侧 _num 同
        # 源收敛兜底，此处按配置非法拒绝）
        if timeout_v > MAX_HOOK_TIMEOUT_SECONDS:
            return (
                f"timeout_seconds 超过上限 {MAX_HOOK_TIMEOUT_SECONDS:g} 秒"
                f"（1 小时），收到 {timeout!r}"
            )
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
    # specs 段类型守卫：非 dict（如手改 YAML 写成非空列表）按空处理，与
    # validate_hooks_config 口径对齐；否则对 list 调 .get 抛 AttributeError，
    # 配置坏掉期间每条状态迁移事件都会刷一条「hook 匹配失败」error 日志。
    spec_hooks = hooks.get("specs")
    spec_hooks = spec_hooks if isinstance(spec_hooks, dict) else {}
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
    # ts 非字符串（手工编辑/外部写入数字）按 "" 参与排序：str 与 int 比较会抛
    # TypeError，且此处位于上方 try 保护之外，会令整个读取接口崩溃
    out.sort(
        key=lambda e: e.get("ts") if isinstance(e.get("ts"), str) else "",
        reverse=True,
    )
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
        # 在飞去重（按 hook_id）：状态短窗口连续迁移时同一 hook 不再并起执行
        # 线程——commit/push 类动作非幂等，并发执行会抢 git index.lock 产生
        # failure 审计+告警噪音，甚至重复提交；在飞时记 skipped 审计。
        # 与 all-done 去重共用 _all_done_lock（均为 dispatch 阶段纯内存去重，
        # 临界区仅集合读写，锁内无 IO、无嵌套获取）。
        self._inflight_hooks: set = set()
        # 非 dict hook 条目的审计去重（code-review item 1a975127db77）：按条目
        # 定位记「(scope, 定位) → 条目指纹」，同一条目仅首次发现或内容变化后
        # 落 failure 审计，重复迁移只记 debug 日志——保留「不静默蒸发」语义
        # （首次必留痕，重启后重新审计），抑制长期不修时 append-only 审计随
        # 状态迁移频率线性膨胀、刷屏审计尾读。
        self._malformed_hook_audited: Dict[Tuple[str, str], str] = {}
        # 框架目录：core/hook_engine.py → 框架根（bin/fenix_dashboard.py 所在）
        self._framework_root = Path(__file__).resolve().parent.parent
        self._project_name = None
        # restart-dashboard 去抖（dashboard-push-restart D2）：进程内最近一次
        # 成功重启的 monotonic 时间戳（0 = 从未成功）；失败不写、窗口内可重试。
        # 仅进程内存态（设计明确不做跨进程持久化：daemon 重启后首个 pushed
        # 多重启一次，无害）。动作在并发 hook 线程执行，读写以锁保护。
        self._dashboard_restart_ok_monotonic = 0.0
        self._dashboard_restart_lock = threading.Lock()
        # 并发认领标记：「去抖检查 + 标记重启中」在同一锁临界区一次完成，防止
        # 两条不同 id 的 restart-dashboard hook（内置 pushed 条目与用户自挂条目）
        # 并发通过入口检查后各自 respawn-window -k，dashboard 被连续弹两次——
        # 无认领标记的 check-then-act 形态下 D2「窗口内重复触发幂等跳过」对
        # 并发首跳不成立。动作本体仍锁外执行（对齐在飞去重「锁内纯内存读写」
        # 惯例），认领在动作收尾（含失败/跳过路径）必然释放。
        self._dashboard_restart_running = False
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
            # 非 dict 条目留痕（code-review item 5e0fb9aa037a）：这类条目无
            # events 可匹配、永远进不了执行链，若不在此显式审计将整条静默蒸发
            self._audit_malformed_hook_entries(spec, from_status, to_status)
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

    def _audit_malformed_hook_entries(
        self, spec: str, from_status: Optional[str], to_status: str
    ) -> None:
        """hooks 段形态损坏时按定位记 failure 审计（code-review item 5e0fb9aa037a）。

        手改 config.yaml 把 hooks.global/specs 条目写成字符串等非 dict 形态时，
        match_hooks 的 isinstance 守卫使其永远无法命中（无 events 可匹配），执行
        链 validate_hook_entry 也到不了——整条静默蒸发、无任何留痕，用户无从
        发现 hook 未生效。事件分发时对现存非对象条目记 failure 审计（按条目定位
        进程内去重：同一条目仅首次发现或内容变化后落审计，重复迁移只记 debug
        日志，防长期不修时审计文件随迁移频率线性膨胀）；口径与 _execute_one 对
        「配置非法（不执行）」一致：不执行、不告警、审计暴露。

        段级形态损坏（code-review item 72f28ce36fe1）：hooks.global 非列表 /
        hooks.specs 非对象在 match_hooks 同样被整段按空处理、蒸发面比条目级更大，
        一并记 failure 审计（validate_hooks_config 只覆盖 dashboard 保存路径，
        手改文件不经过该闸门）。枚举基于原始 self.config 的 hooks 段而非
        hook_config 注入视图（code-review item f28092ccd3bf）：注入会把内置条目
        插到 global[0]，按注入后视图编号会使定位符相对 config.yaml 偏移一位、
        去重键随之漂移（用户在坏条目前插入合法条目即重复落审计）；注入条目恒为
        dict、本就不参与该审计，直接读原始配置即可。
        """
        # isinstance 守卫对齐 hook_config：config/hooks 段非 dict 时视为无配置
        hooks = self.config.get("hooks") if isinstance(self.config, dict) else None
        malformed: List[Tuple[str, str, str]] = []  # (scope, 条目定位, 条目指纹)
        g = hooks.get("global") if isinstance(hooks, dict) else None
        if g is not None and not isinstance(g, list):
            # 段级：非列表 global 被按空处理、整段未执行，补审计留痕
            malformed.append(("global", "hooks.global", _truncate(repr(g), 512)))
        else:
            malformed.extend(
                ("global", f"hooks.global[{idx}]", _truncate(repr(h), 512))
                for idx, h in enumerate(g or [])
                if not isinstance(h, dict)
            )
        specs = hooks.get("specs") if isinstance(hooks, dict) else None
        if specs is not None and not isinstance(specs, dict):
            # 段级：非对象 specs 被按空处理、整段未执行，补审计留痕
            malformed.append(("spec", "hooks.specs", _truncate(repr(specs), 512)))
        else:
            for name, lst in (specs or {}).items():
                if not isinstance(lst, list):
                    continue
                malformed.extend(
                    ("spec", f"hooks.specs.{name}[{idx}]", _truncate(repr(h), 512))
                    for idx, h in enumerate(lst)
                    if not isinstance(h, dict)
                )
        for scope, where, fingerprint in malformed:
            key = (scope, where)
            if self._malformed_hook_audited.get(key) == fingerprint:
                # 同一条目同内容已审计过：只记 debug 不再重复写审计（抑制
                # append-only 审计随状态迁移频率线性膨胀、刷屏审计尾读）；
                # 条目内容变化或换位后仍会重新审计，「不静默蒸发」语义保留
                self._log_debug(f"hook 配置非法（同条目已审计过，不再重复记）: {where}")
                continue
            self._malformed_hook_audited[key] = fingerprint
            # 文案按形态区分：段级定位符无下标，口径对齐 validate_hooks_config
            section_reason = {
                "hooks.global": "必须为列表（非列表按空处理，整段未执行）",
                "hooks.specs": "必须为对象（非对象按空处理，整段未执行）",
            }.get(where)
            detail = (
                f"hook 配置非法（不执行）: {where} {section_reason}"
                if section_reason
                else f"hook 配置非法（不执行）: {where} 条目必须为对象（非对象条目不参与匹配，未执行）"
            )
            self._audit(
                spec,
                from_status,
                to_status,
                None,  # 非 dict 条目提取不到 id
                None,  # 同理提取不到 action
                scope,
                STATUS_FAILURE,
                detail,
                0.0,
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
            # 投递中断（match_hooks 异常 / 线程创建或 start 失败如线程数耗尽）：
            # 复位去重标志，下次成功终态迁移可重新收口触发——标志滞留 True 则
            # 剩余 hook 被静默错过，需等任一 spec 离开成功终态才可能再触发
            # （all-done→restart-daemon 即「安全重启点」被跳过）。代价：中断前
            # 已启动的 hook 在重触发时可能重复执行（动作按幂等设计，重复代价
            # 小于永久错过；带 id hook 另有在飞去重兜并发）。
            with self._all_done_lock:
                self._all_done_fired = False
            self._log_error(f"all-done hook 投递失败（不向调用方抛）: {type(e).__name__}: {e}")

    # ── 单条执行 ────────────────────────────────────────────────────

    def _inflight_begin(self, hook_id) -> bool:
        """在飞去重 check-and-set：该 hook 已有执行线程在飞则返回 False。

        仅带字符串 id 的 hook 参与去重（无 id 手写 hook 无法定位，保持并发旧行为）；
        锁窗口仅集合读写，hook 动作本体一律在锁外执行。
        """
        if not hook_id or not isinstance(hook_id, str):
            # 非字符串 id（手改 config.yaml 写出的 list/dict 等 unhashable 值）
            # 不参与集合去重：成员判断/add 会对 set 抛 TypeError，而本调用位于
            # 执行线程 try 保护之外，异常将无审计终结线程；放行交由执行链
            # validate_hook_entry 按「配置非法（不执行）」记 failure 审计。
            return True
        with self._all_done_lock:
            if hook_id in self._inflight_hooks:
                return False
            self._inflight_hooks.add(hook_id)
            return True

    def _inflight_end(self, hook_id) -> None:
        """释放在飞标记（执行线程 finally 调用；无 id/非字符串 id 无标记可释放）。"""
        if not hook_id or not isinstance(hook_id, str):
            return
        with self._all_done_lock:
            self._inflight_hooks.discard(hook_id)

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
            # specs 段类型守卫：与 match_hooks 同口径——非 dict（如手改 YAML
            # 写成非空列表）按空处理；否则对 list 调 .get 抛 AttributeError，
            # 在飞跳过路径本调用位于 try 保护之外，异常将无审计终结线程
            spec_hooks = hooks.get("specs")
            candidates = (
                (spec_hooks.get(spec) or []) if isinstance(spec_hooks, dict) else []
            )
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

        在飞去重：同一 hook 上一线程未结束时不再并起新执行，记 skipped 审计
        返回（避免状态快速连续迁移时非幂等动作并发执行）。
        单 hook 异常互不影响（线程级 try 全包裹，失败走 failure 审计+告警）。
        无 id 的手写 hook（validate_hook_entry 允许缺省 id 的受支持形态）无法
        按 id 重查实时配置，按投递时命中的原始配置 matched_cfg 执行并照常写
        审计；带 id 条目在投递与执行间隙被删除仍静默跳过（不写审计）。
        """
        if not self._inflight_begin(hook_id):
            live = self._find_live_hook(hook_id, scope, spec) or {}
            self._audit(
                spec,
                from_status,
                to_status,
                hook_id,
                live.get("action"),
                scope,
                STATUS_SKIPPED,
                (
                    "同一 hook 上一事件仍在执行（在飞去重，键为裸 hook_id、不含 spec 维度），"
                    f"本事件（spec={spec}）被丢弃且不排队补执行，待该 hook 空闲后的下一事件重触发"
                ),
                0.0,
            )
            return
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
        finally:
            self._inflight_end(hook_id)

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
            # dashboard-push-restart 1.2：动作改三态返回（success/failure/
            # skipped），去抖/无会话的 skipped 直接映射 skipped 审计，
            # 不再以 (True, "skipped: ...") 冒充 success
            status, detail = self._action_restart_dashboard(cfg)
        elif action == "webhook":
            status, detail = self._action_webhook(cfg, spec, from_status, to_status, entry)
        elif action == "shell":
            status, detail = self._action_shell(cfg, spec, from_status, to_status, entry)
        else:  # 校验已保证合法，防御兜底
            status, detail = STATUS_FAILURE, f"未知动作: {action}"

        duration = time.monotonic() - started
        self._audit(
            spec,
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
                        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                            ids = []  # 半截/损坏标记：重建即可
                    hid = str(hook_id or "")
                    if hid and hid not in ids:
                        ids.append(hid)
                    payload = {"ts": _utcnow_iso(), "hook_ids": ids}
                    tmp = path.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    try:
                        tmp.replace(path)
                    except OSError:
                        # rename 失败不残留半成品 tmp（对齐
                        # _remove_hook_ids_from_config_files 的 tmp 清理口径）
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise
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
        # UnicodeDecodeError（ValueError 子类）与 _mark_restart_cleanup /
        # _remove_hook_ids_from_config_files 同口径显式列出：非 UTF-8 字节的
        # 标记文件在 read_text 处抛出，按「标记损坏，跳过清扫」处理，而非穿到
        # __init__ 通用兜底被误归因为「清扫失败」
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
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

        # 读-改-写全程持 config_admin 的进程内 config 写锁（code-review item
        # 34488d84e084）：整文件替换式写回无锁时，同进程并发写回各持陈旧副本，
        # 后写者静默覆盖先写者（用户刚保存的 hook 丢失，或清扫结果被旧副本
        # 顶回）。该锁仅提供同进程互斥（admin_actions 裁决回写路径），
        # dashboard --serve 为独立进程，跨进程并发不在本锁覆盖范围（如需可
        # 叠加 flock，见 config_admin.py 注释；code-review item
        # a28282d49539）。按文件粒度短临界区、锁内不嵌套其他锁；config_admin
        # 不可导入时退化为无锁清扫并记警告（不因导入失败阻断清扫语义）。
        try:
            from core.dashboard.data.config_admin import _CONFIG_WRITE_LOCK
        except Exception as e:
            _CONFIG_WRITE_LOCK = None
            self._log_warning(f"config 写锁不可用，清扫退化为无锁读改写: {e}")

        changed = 0
        failed = 0
        for cfg_path in self._hook_config_paths():
            if _CONFIG_WRITE_LOCK is not None:
                _CONFIG_WRITE_LOCK.acquire()
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
            # UnicodeDecodeError（ValueError 子类）：非 UTF-8 字节的配置文件在
            # read_text 处抛出，不接住会穿出逐文件循环、剩余配置文件不再清扫
            # （code-review item f3778b44687e）——计入 failed 继续处理其余文件
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
                failed += 1
                self._log_warning(f"hook 清扫读改 {cfg_path} 失败: {e}")
            finally:
                if _CONFIG_WRITE_LOCK is not None:
                    _CONFIG_WRITE_LOCK.release()
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
        否则用 DEFAULT_COMMIT_PATHS 过滤——仅保留磁盘存在（且不穿越目录软链）
        或已有跟踪文件的路径，规避「pathspec matches nothing」令整条
        git add fatal（同 archive_commit 的处理）。
        """
        configured = cfg.get("paths")
        if isinstance(configured, list) and configured and all(
            isinstance(p, str) and p.strip() for p in configured
        ):
            return [p.strip() for p in configured]
        paths: List[str] = []
        for p in DEFAULT_COMMIT_PATHS:
            if (self.project_root / p).exists() and not _traverses_symlink_dir(
                self.project_root, p
            ):
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

    def _action_restart_dashboard(self, cfg: dict) -> Tuple[str, str]:
        """tmux respawn-window -k -t <target> 重启 dashboard 会话（三态返回）。

        固化启动命令（2026-09-06 从存活会话提取固化）：``env -u CLAUDE_PID
        <sys.executable> <framework>/bin/fenix_dashboard.py --serve``——env -u
        CLAUDE_PID 防 claude-watchdog 绑会话自杀；解释器取 daemon 当前
        sys.executable（venv/非系统解释器部署下 respawn 出的会话依赖仍可用，
        不受 tmux 环境 PATH 命中的裸 python3 影响）；保持 8787 端口（serve()
        内部解析配置端口，缺省 8787）与原工作目录。重启后以端口重新可服务为
        成功判据。

        dashboard-push-restart D2/D3 健壮化：
        - 去抖（D2）：入口检查进程内最近成功重启时间戳，60s 窗口内幂等跳过
          （skipped 审计留痕）；失败不写时间戳，窗口内可重试。检查与「标记
          重启中」在同一锁临界区一次完成：并发多条不同 id 的 restart-dashboard
          hook 命中时仅首个认领者执行动作，其余按 skipped 幂等跳过。
        - 无会话静默跳过（D3）：tmux 会话不存在是环境态而非操作失败（CI/容器
          本就无 dashboard），返回 skipped + debug 日志，不产 failure 审计与
          告警噪音；会话存在但 respawn/端口探测失败仍记 failure（真故障）。

        Returns: (status, detail)，status ∈ success/failure/skipped。
        """
        # 执行侧复检 target 类型（校验只把守配置写入路径，直改 config.yaml 可
        # 绕过）：非字符串会在下方 (target or "").strip() 抛 AttributeError、穿
        # 通用兜底致归因降级，按「配置非法（不执行）」记 failure，口径对齐
        # validate_hook_entry 与 _action_webhook 的 url 复检
        target = cfg.get("target")
        if target is not None and not isinstance(target, str):
            return STATUS_FAILURE, f"restart-dashboard target 配置非法（必须为字符串）: {target!r}"
        target = (target or "").strip() or DEFAULT_DASHBOARD_SESSION
        now = time.monotonic()
        # 临界区一次完成「去抖检查 + 认领重启中」：并发 hook 线程只有首个
        # 认领成功者继续执行动作，其余按 skipped 跳过——两段式 check-then-act
        # 会被并发首跳穿透（见 __init__ 认领标记注释）
        with self._dashboard_restart_lock:
            last_ok = self._dashboard_restart_ok_monotonic
            in_window = bool(last_ok) and (now - last_ok) < DASHBOARD_RESTART_DEBOUNCE_SECONDS
            if in_window or self._dashboard_restart_running:
                claim = False
                if in_window:
                    skip_detail = (
                        f"距上次成功重启 {now - last_ok:.0f}s，处于 "
                        f"{DASHBOARD_RESTART_DEBOUNCE_SECONDS:.0f}s 去抖窗口内，跳过重复重启"
                    )
                else:
                    skip_detail = "另一 restart-dashboard 正在重启（已认领未收尾），跳过并发重复重启"
            else:
                self._dashboard_restart_running = True
                claim = True
        if not claim:
            return STATUS_SKIPPED, skip_detail
        try:
            try:
                has = subprocess.run(
                    ["tmux", "has-session", "-t", target], capture_output=True, text=True, timeout=10
                )
            except (subprocess.SubprocessError, OSError) as e:
                # tmux 二进制缺失/不可执行同为「无 dashboard 环境」环境态：静默跳过
                self._log_debug(f"tmux has-session 失败（按无 dashboard 环境跳过）: {e}")
                return STATUS_SKIPPED, f"tmux has-session 失败（按无 dashboard 环境静默跳过）: {e}"
            if has.returncode != 0:
                self._log_debug(f"tmux 会话 {target} 不存在，restart-dashboard 静默跳过")
                return (
                    STATUS_SKIPPED,
                    f"tmux 会话 {target} 不存在（dashboard 未运行环境），静默跳过",
                )
            dash = self._framework_root / "bin" / "fenix_dashboard.py"
            if not dash.is_file():
                return STATUS_FAILURE, f"dashboard 启动脚本不存在: {dash}"
            # 解释器用 daemon 当前 sys.executable 而非裸 python3（后者解析的是
            # tmux 环境 PATH 命中项，venv/非系统解释器部署下 dashboard 依赖只在
            # daemon 环境装了，respawn 后起不来→探测必败记 failure）；
            # sys.executable 理论上可为空串（嵌入解释器），回退裸 python3 保持旧行为
            shell_cmd = (
                f"cd {shlex.quote(str(self.project_root))} && "
                f"env -u CLAUDE_PID {shlex.quote(sys.executable or 'python3')} "
                f"{shlex.quote(str(dash))} --serve"
            )
            try:
                respawn = subprocess.run(
                    ["tmux", "respawn-window", "-k", "-t", target, shell_cmd],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (subprocess.SubprocessError, OSError) as e:
                return STATUS_FAILURE, f"tmux respawn-window 失败: {e}"
            if respawn.returncode != 0:
                return (
                    STATUS_FAILURE,
                    f"tmux respawn-window 失败: {_tail_combined(respawn.stdout, respawn.stderr)}",
                )
            port = self._dashboard_port()
            if not self._probe_dashboard(port):
                # 上限按每轮 urlopen timeout=2s + 间隔 DASHBOARD_PROBE_INTERVAL 估算（对应 _probe_dashboard）
                return (
                    STATUS_FAILURE,
                    f"dashboard 已 respawn，但 {port} 端口最坏 {DASHBOARD_PROBE_ATTEMPTS * (2 + DASHBOARD_PROBE_INTERVAL):.0f}s 内未恢复 HTTP 可服务",
                )
            with self._dashboard_restart_lock:
                self._dashboard_restart_ok_monotonic = time.monotonic()
            return STATUS_SUCCESS, f"dashboard 会话 {target} 已重启（端口 {port} 恢复可服务）"
        finally:
            with self._dashboard_restart_lock:
                self._dashboard_restart_running = False

    def _dashboard_port(self) -> int:
        """dashboard 服务端口：config dashboard.port 合法则用之，否则 8787。"""
        try:
            from .config import ConfigLoader

            port = ConfigLoader.get(self.config, "dashboard.port", DEFAULT_DASHBOARD_PORT)
            # bool 前判排除（bool 是 int 子类，True→int(True)=1 会穿透下方
            # 0 < port < 65536 校验去探测端口 1 必败记 failure；对齐 _num 与
            # validate_hook_entry 的 bool 显式排除口径）
            if isinstance(port, bool):
                return DEFAULT_DASHBOARD_PORT
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
            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
                http.client.HTTPException,
            ):
                # HTTPException 家族（如 chunked 截断的 IncompleteRead）非
                # OSError：读响应体失败按本轮探测未通过处理，继续下一轮重试，
                # 不上抛给 _execute_one 通用兜底误报 hook 失败
                time.sleep(DASHBOARD_PROBE_INTERVAL)
        return False

    def _action_webhook(
        self, cfg: dict, spec: str, from_status: Optional[str], to_status: str, entry: dict
    ) -> Tuple[str, str]:
        """POST JSON 通知（含审计）；2xx = 成功，响应体截断 2KB 记审计。"""
        # 执行侧复检 url 类型（校验只把守配置写入路径，直改 config.yaml 可绕过）：
        # 非字符串会在下方 .strip() 抛 AttributeError、穿通用兜底致归因降级，按
        # 「配置非法（不执行）」记 failure，与 validate_hook_entry 口径一致
        url = cfg.get("url")
        if url is not None and not isinstance(url, str):
            return STATUS_FAILURE, f"webhook url 配置非法（必须为字符串）: {url!r}"
        url = (url or "").strip()
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
        # 超上限收敛留痕（afb00545e096）：_num 已收敛，此处仅对原始配置超限
        # 的形态记 debug（缺省值远低于上限，合法配置不命中；不产审计/告警）
        if timeout >= MAX_HOOK_TIMEOUT_SECONDS and cfg.get("timeout_seconds") != timeout:
            self._log_debug(
                f"timeout_seconds 超过上限 {MAX_HOOK_TIMEOUT_SECONDS:g} 秒，已收敛到上限"
            )
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
            # 专用 opener：重定向每跳前复查 scheme（默认 opener 会跟随
            # 302 → file:///... 把本地资源读入审计，绕过 scheme 白名单）
            with _WEBHOOK_OPENER.open(req, timeout=timeout) as resp:
                code = resp.status
                body = resp.read(DETAIL_LIMIT)
        except urllib.error.HTTPError as e:
            # 非 2xx 直接 return 前显式释放 HTTPError 持有的错误响应 fp/socket
            # （HTTPError 为 addinfourl 子类，close() 关闭底层连接；fp 缺省时
            # close 自身安全），对齐 _WebhookRedirectGuard 越界分支的 fp.close()
            # 口径——不关则连接释放依赖 GC，hook 高频失败时句柄短暂堆积
            try:
                e.close()
            except OSError:
                pass
            return STATUS_FAILURE, f"webhook 非 2xx: HTTP {e.code}"
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
        ) as e:
            # HTTPException 家族（如读响应体的 IncompleteRead）非 OSError：
            # 读体失败按请求失败处置（POST 可能已送达），口径对齐
            # _probe_dashboard——不上抛 _execute_one 通用兜底误报
            # 「hook 执行异常」
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
        # 超上限收敛留痕（afb00545e096）：_num 已收敛，此处仅对原始配置超限
        # 的形态记 debug（缺省值远低于上限，合法配置不命中；不产审计/告警）
        if timeout >= MAX_HOOK_TIMEOUT_SECONDS and cfg.get("timeout_seconds") != timeout:
            self._log_debug(
                f"timeout_seconds 超过上限 {MAX_HOOK_TIMEOUT_SECONDS:g} 秒，已收敛到上限"
            )
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
                # 非 UTF-8 输出以替换符容错解码（对齐 _run_git）：解码异常不被
                # 下方 except OSError 捕获，会穿到通用兜底、使审计归因降级为
                # 「hook 执行异常」而非具体 shell 失败
                errors="replace",
                start_new_session=True,
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # 强杀+回收兜底收敛到共享实现（含守护化孙进程关流兜底）
                out, err = _terminate_proc_group(proc)
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
        from_status: Optional[str],
        to_status: Optional[str],
        hook_id,
        action,
        scope: str,
        status: str,
        detail: str,
        duration_s: float,
    ) -> None:
        """带锁追加一条审计记录到 .fenix/hook_audit.jsonl。

        event 字段恒取 to_status（事件源即状态迁移的新状态，伪事件 all-done
        也以 to_status 传入），二者恒等故不设独立 event 参数。
        """
        rec = {
            "ts": _utcnow_iso(),
            "spec": spec,
            "event": to_status,
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
                            # 与 DisputeAuditStore/_trim_unlocked 落盘口径统一：
                            # SIGKILL/掉电时最新一条审计行不因页缓存未刷而丢失
                            os.fsync(f.fileno())
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

    def _log_debug(self, message: str) -> None:
        """debug 级日志（dashboard-push-restart D3 静默跳过用，不产审计/告警）。

        无 logger（单元测试/裸进程）时 debug 级别保持静默（对齐降噪口径，
        与 error/warning 的 print 兜底不同）。
        """
        if self.logger is not None:
            try:
                self.logger.debug("hook_engine", message)
            except Exception:
                pass
