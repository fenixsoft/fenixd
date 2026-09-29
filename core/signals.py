"""core.signals — pm_engine / dashboard.data 共用的信号/查询函数中性模块。

fix-deferred-findings CYC-1（设计 D3）：消除 pm_engine 侧对
core.dashboard.data 的反向 import（分层倒置）。pm_engine 子模块
（escalation / report_gate）late import 本模块而非 dashboard.data
门面。

当前已搬入的函数：
- request_admin_invoke（原 admin_actions.py）
- parse_verify_progress（原 artifacts.py）

NOT 搬入（登记为「不搬」，见 findings-ledger.md）：
- get_runs / record_project_event：pm_engine 唯一进口为 engine.py
  （已登记为转移清单），搬迁不减少非 engine.py 反向 import，
  且涉及 runs.py 的 _RUN_META_CACHE memo 语义（design D3 约定 2）。
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ADMIN_INVOKE_REQUEST 常量（信号文件路径）
ADMIN_INVOKE_REQUEST = ".fenix/admin_invoke_request.json"

# SCHEDULING_KICK_DIR 常量（scheduling kick 信号目录）。
# fix-scheduling-kick-single-slot：由单文件单槽位演进为「每 SPEC 一文件」目录形态
# ——不同 SPEC 写不同文件，无共享槽位即无跨 SPEC 冲突；同一 SPEC 重复清空幂等覆盖。
# 旧常量 SCHEDULING_KICK_REQUEST（.fenix/scheduling_kick_request.json）走向只读兼容：
# 消费侧仍识别并消费存量旧文件（消费后删除），新写入一律走本目录。
SCHEDULING_KICK_DIR = ".fenix/scheduling_kick"

# SPEC 名合法性判据：复制自 core/spec_gen.py 的 kebab-case 权威正则
# （^[a-z][a-z0-9]*(-[a-z0-9]+)*$）。core.signals 须为中性模块（不依赖
# core.dashboard.data / core.spec_gen），故在此复制而非导入——两份正则
# 保持字面一致，若 spec_gen 侧正则变更须同步更新此处。
_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def request_admin_invoke(
    project_root,
    spec: str,
    prompt: str | None = None,
    underlying_signal_type: str | None = None,
) -> dict:
    """写入手动唤起 Administrator 的文件信号（.fenix/admin_invoke_request.json）。

    校验 spec 须存在于项目 STATE.md，且当前不存在未消费的请求文件，否则返回
    对应拒绝状态（spec 不存在 → {found: False}；已有进行中 → {conflict: True}）。
    通过校验后原子写入 {spec, source: "manual", created: <ISO>} 返回 {ok: True}。

    prompt：用户在 Dashboard 处置弹窗输入的提示词，非空时写入请求文件，
    daemon 拾取后作为本次处置的任务描述（替代默认文案）传给 Administrator。

    underlying_signal_type：底层信号类型直传（fix-escalation-autoinvoke-
    passthrough），非空时写入请求文件，daemon 拾取后随信号透传给处置收尾
    自动复位判定门。自动呼叫路径（如 env 阻塞）的升级记录多为 warning 级
    降噪（写库即标 handled），消费侧基于 store 的未处置记录反查对此不可见，
    须由呼叫方自带类型；dashboard 纯人工唤起不传、仍走反查。

    文件信号模式与 restart_request 同构：server 进程不直接起 agent（绕过
    state_machine 与 token 预算），由 daemon 主循环下一轮扫描拾取并唤起。

    Returns:
        {"ok": bool, "found": bool, "conflict": bool,
         "file": str|null, "created": str|null, "error": str|null}
    """
    # parse_state：STATE.md 解析（纯函数，无 dashboard.data 内反向依赖）。
    # 延迟导入避免与 dashboard.data 门面的循环依赖（门面 artifacts 亦
    # re-export 本模块）。
    from core.dashboard.data.state import parse_state

    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {
            "ok": False,
            "found": False,
            "conflict": False,
            "file": None,
            "created": None,
            "error": f"spec not found: {spec}",
        }

    req_path = proot / ADMIN_INVOKE_REQUEST
    if req_path.exists():
        # 读既有 created 供返回（对齐同族 request_run_cancel /
        # request_spec_delete / request_spec_approve_push 冲突语义；
        # 读失败保持 None，不抛异常）
        existing_created = None
        try:
            existing = json.loads(req_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing_created = existing.get("created")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        return {
            "ok": False,
            "found": True,
            "conflict": True,
            "file": str(req_path),
            "created": existing_created,
            "error": "已有进行中的 Admin 处置",
        }

    created = datetime.now(timezone.utc).isoformat()
    payload = {"spec": spec, "source": "manual", "created": created}
    if prompt and prompt.strip():
        payload["prompt"] = prompt.strip()
    if underlying_signal_type and str(underlying_signal_type).strip():
        payload["underlying_signal_type"] = str(underlying_signal_type).strip()
    req_path.parent.mkdir(parents=True, exist_ok=True)
    # TOCTOU 修复（code-review item 546945dbaffb）：上方 exists() 检查与写入
    # 之间存在并发窗口——两个并发请求可能都通过检查，随后各自 os.replace 覆盖
    # 同一路径，后写者覆盖前写者（先返回 ok 的请求被静默丢弃、永不执行）。
    # 以 O_CREAT|O_EXCL 占位创建做原子「检查+占位」：占位失败即 conflict；
    # 内容随后经 tempfile+os.replace 原子换入。空占位窗口对消费侧
    # （fenixd._consume_request_file 先 rename 后读私有副本）无害：最坏
    # rename 走空占位、下一轮（1s 粒度）拾取换入的完整内容，请求不丢。
    # [fenix-ignore:c3d305a22fc2] 进程崩溃残留的零字节占位无需 TTL 自愈：消费侧 _consume_request_file 每轮主循环把它 rename 成私有副本，空文件 json.load 抛 JSONDecodeError 走清理分支照样 unlink（fenixd.py），占位随之从磁盘移除，通道不会被永久锁死。
    try:
        placeholder_fd = os.open(
            req_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
        )
        os.close(placeholder_fd)
    except FileExistsError:
        # 冲突时同样回读既有 created（对齐同族冲突语义）；并发空占位或
        # 读失败保持 None，不抛异常
        existing_created = None
        try:
            existing = json.loads(req_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing_created = existing.get("created")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        return {
            "ok": False,
            "found": True,
            "conflict": True,
            "file": str(req_path),
            "created": existing_created,
            "error": "已有进行中的 Admin 处置",
        }
    fd, tmp_path = tempfile.mkstemp(
        dir=str(req_path.parent), prefix=".admin_invoke_request.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, req_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        # 写失败时尽力清掉自己占的位（仅当仍是空占位，避免误删他人请求）
        try:
            if req_path.stat().st_size == 0:
                req_path.unlink()
        except OSError:
            pass
        raise
    return {
        "ok": True,
        "found": True,
        "conflict": False,
        "file": str(req_path),
        "created": created,
        "error": None,
    }


def validate_scheduling_kick_spec(spec: str) -> str | None:
    """校验 SPEC 名可否作 scheduling kick 信号文件名。

    判据复用 core/spec_gen.py 的 kebab-case 权威正则（^[a-z][a-z0-9]*(-[a-z0-9]+)*$）：
    SPEC 名已被 fenix_spec.py new 约束为该形态，可安全作文件名。黑名单式拒绝
    （仅查空串 / `/` / `\` / `..`）会放过 `.`、前导点、含 `:` 或非 ASCII 等
    「能当文件名但不合规」的输入——正则白名单与之等价且无遗漏。

    Returns:
        合法返回 None；不合法返回非空错误描述。
    """
    if not isinstance(spec, str):
        return f"spec 名必须为字符串（当前类型 {type(spec).__name__}）"
    if not spec:
        return "spec 名为空"
    if not _KEBAB_RE.match(spec):
        return (
            f"spec 名不合法（须为 kebab-case，如 'fix-foo-bar'）：{spec!r}"
        )
    return None


def write_scheduling_kick(project_root, spec: str) -> dict:
    """写「清空 start_after 触发即时派发」的唤醒信号到每 SPEC 一文件的目录。

    fix-scheduling-kick-single-slot：载体由单文件单槽位
    （.fenix/scheduling_kick_request.json）演进为每 SPEC 一个文件
    （.fenix/scheduling_kick/<spec>.json）。同一 SPEC 重复清空幂等覆盖自身文件；
    不同 SPEC 互不阻塞——从根上消除跨 SPEC 的「槽位冲突导致静默丢弃」。

    写入原子性：tempfile.mkstemp 在目标同目录建临时文件 → os.fsync → os.replace
    覆盖目标。临时文件名不以 `.json` 结尾（<spec>.json.tmp.<rand>），避免被消费侧
    「只扫 *.json」的谓词命中并发写入中的临时文件。

    Returns:
        {"ok": bool, "file": str|null, "error": str|null}
        任何异常不外抛，一律转为 ok:false + 非空 error。
    """
    name_err = validate_scheduling_kick_spec(spec)
    if name_err is not None:
        return {"ok": False, "file": None, "error": name_err}

    proot = Path(project_root)
    req_dir = proot / SCHEDULING_KICK_DIR
    req_path = req_dir / f"{spec}.json"
    created = datetime.now(timezone.utc).isoformat()
    payload = {"spec": spec, "action": "clear-start-after", "created": created}

    try:
        req_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(req_dir), prefix=f".{spec}.json.tmp."
        )
    except OSError as exc:
        return {"ok": False, "file": None, "error": f"无法创建信号目录/临时文件: {exc}"}
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, req_path)
    except Exception as exc:  # 任何异常不外抛，转为 ok:false
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return {"ok": False, "file": None, "error": f"写入 scheduling kick 信号失败: {exc}"}
    return {"ok": True, "file": str(req_path), "error": None}


def parse_verify_progress(project_root, spec_name) -> dict:
    """解析 .fenix/verify-progress/<spec>.json；损坏/非对象以 error 字段标记。

    进度文件缺失时回退 fast-track 裁决结果文件（fix-verify-progress-fasttrack）：
    调 parse_run_result_scenarios 取 verification.scenarios 合成进度——total=场景数、
    done=含 status 条目数、current 在 done == total 时为终态文案
    「验证完成: N通过, M失败, K错误」（对齐 verify_engine 终态格式），
    done < total（存在无 status 场景，运行中/中断）时为进行中文案
    「验证中: D/T」，并标记 source: "run-result" 区分来源
    （进度文件路径返回 source: "file"）。两者皆缺维持 exists: False 空态语义。
    """
    # 与写路径（write_scheduling_kick）同口径：spec 名过 kebab-case 白名单才拼
    # 文件路径，不合法语义等同「文件不存在」，返回空态（防路径穿越读任意 json）。
    if validate_scheduling_kick_spec(spec_name) is not None:
        return {"exists": False, "total": 0, "done": 0, "current": ""}
    pf = Path(project_root) / ".fenix" / "verify-progress" / f"{spec_name}.json"
    if pf.exists():
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"exists": True, "error": "corrupt", "total": 0, "done": 0, "current": ""}
            return {
                "exists": True,
                "total": int(data.get("total", 0) or 0),
                "done": int(data.get("done", 0) or 0),
                "current": data.get("current", "") or "",
                "step": data.get("step"),
                "error": data.get("error"),
                "source": "file",
            }
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return {"exists": True, "error": "corrupt", "total": 0, "done": 0, "current": ""}
    # 进度文件缺失：fast-track 回退合成（场景为空维持空态，不抛异常）
    from core.dashboard.data.artifacts import parse_run_result_scenarios

    scenarios = parse_run_result_scenarios(project_root, spec_name)
    if not scenarios:
        return {"exists": False, "total": 0, "done": 0, "current": ""}
    passed = failed = errors = done = 0
    for sc in scenarios:
        status = sc.get("status")
        if not status:
            continue
        done += 1
        if status in ("pass", "passed"):
            passed += 1
        elif status in ("fail", "failed"):
            failed += 1
        elif status == "error":
            errors += 1
        # warning/exempt 豁免类不入三桶（与裁决链豁免语义一致）
    # done < total 说明有场景尚无 status（运行中/中断），不得输出终态文案
    # 误标完成；仅 done == total 对齐 verify_engine 终态格式。
    total = len(scenarios)
    if done == total:
        current = f"验证完成: {passed}通过, {failed}失败, {errors}错误"
    else:
        current = f"验证中: {done}/{total}"
    return {
        "exists": True,
        "total": total,
        "done": done,
        "current": current,
        "source": "run-result",
    }
