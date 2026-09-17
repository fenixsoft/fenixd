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
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ADMIN_INVOKE_REQUEST 常量（信号文件路径）
ADMIN_INVOKE_REQUEST = ".fenix/admin_invoke_request.json"


def request_admin_invoke(project_root, spec: str, prompt: str | None = None) -> dict:
    """写入手动唤起 Administrator 的文件信号（.fenix/admin_invoke_request.json）。

    校验 spec 须存在于项目 STATE.md，且当前不存在未消费的请求文件，否则返回
    对应拒绝状态（spec 不存在 → {found: False}；已有进行中 → {conflict: True}）。
    通过校验后原子写入 {spec, source: "manual", created: <ISO>} 返回 {ok: True}。

    prompt：用户在 Dashboard 处置弹窗输入的提示词，非空时写入请求文件，
    daemon 拾取后作为本次处置的任务描述（替代默认文案）传给 Administrator。

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
        return {
            "ok": False,
            "found": True,
            "conflict": True,
            "file": str(req_path),
            "created": None,
            "error": "已有进行中的 Admin 处置",
        }

    created = datetime.now(timezone.utc).isoformat()
    payload = {"spec": spec, "source": "manual", "created": created}
    if prompt and prompt.strip():
        payload["prompt"] = prompt.strip()
    req_path.parent.mkdir(parents=True, exist_ok=True)
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
        raise
    return {
        "ok": True,
        "found": True,
        "conflict": False,
        "file": str(req_path),
        "created": created,
        "error": None,
    }


def parse_verify_progress(project_root, spec_name) -> dict:
    """解析 .fenix/verify-progress/<spec>.json；损坏/非对象以 error 字段标记。

    进度文件缺失时回退 fast-track 裁决结果文件（fix-verify-progress-fasttrack）：
    调 parse_run_result_scenarios 取 verification.scenarios 合成进度——total=场景数、
    done=含 status 条目数、current=终态文案「验证完成: N通过, M失败, K错误」
    （对齐 verify_engine 终态格式），并标记 source: "run-result" 区分来源
    （进度文件路径返回 source: "file"）。两者皆缺维持 exists: False 空态语义。
    """
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
        if status == "pass":
            passed += 1
        elif status in ("fail", "failed"):
            failed += 1
        elif status == "error":
            errors += 1
        # warning/exempt 豁免类不入三桶（与裁决链豁免语义一致）
    return {
        "exists": True,
        "total": len(scenarios),
        "done": done,
        "current": f"验证完成: {passed}通过, {failed}失败, {errors}错误",
        "source": "run-result",
    }
