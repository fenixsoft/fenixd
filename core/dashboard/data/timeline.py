"""core.dashboard.data.timeline — SPEC 生命周期时间轴（timeline 组）。

refactor-dashboard-data-module D3 分组：本模块承载时间轴重建职责域。
"""

import json
import re
from pathlib import Path

from core import timelib

# 生命周期序表（本模块私有副本，canonical 状态机在 core/state_machine.py 的
# SpecStatus/VALID_TRANSITIONS；单源上移属跨组改动，此处锚定同步纪律）：
# **state_machine 新增/更名生命周期状态必须同步此表（对齐 core/state_machine.py）**。
# 当前覆盖 SpecStatus.ALL 全集（含 0.5/2.5 半步与侧挂 blocked）。未登记状态由
# _lifecycle_backward 显式按前向处理，不依赖 .get(s, 9) 哨兵默认值的隐式语义
# ——否则新状态从其出发到已知状态的前向转移会因 frm=9 恒大于 to 被误判为
# 回退、时间轴误发「状态回退」文案（code-review item 91cde8241935）。
_LIFECYCLE_ORDER = {
    "drafted": 0,
    "reviewing": 0.5,
    "ready": 1,
    "implementing": 2,
    "bug-found": 2.5,
    "implemented": 3,
    "testing": 4,
    "verified": 5,
    "done": 6,
    "pushed": 7,
    # 侧挂暂停态（非链上生命周期步）：显式排全链之后（>pushed 7），逐转移位
    # 固化既有哨兵 9 语义——进入侧挂恒前向、侧挂退出到任一链上状态按回退
    # 呈现（tests/test_spec_timeline_name_isolation.py::
    # test_blocked_to_ready_still_backward 锁定的存量行为）
    "blocked": 8,
}


def _lifecycle_backward(frm: str, to: str) -> bool:
    """frm→to 是否为生命周期回退；frm/to 任一未登记状态显式按前向处理。

    废弃 .get(s, 9) 哨兵默认值的隐式判定：未登记状态不参与序比较、直接按
    前向返回 False——序表滞后于 state_machine 时方向不再误判（见
    _LIFECYCLE_ORDER 锚定注释）。
    """
    if frm not in _LIFECYCLE_ORDER or to not in _LIFECYCLE_ORDER:
        return False
    return _LIFECYCLE_ORDER[to] < _LIFECYCLE_ORDER[frm]


def _backtrack_reason(frm: str, to: str) -> str:
    """状态回退的规则兜底原因（Agent 记录的 error 优先，见 get_spec_timeline）。"""
    if to == "bug-found":
        return "验证发现 bug，退回修复"
    if frm == "testing" and to in ("implementing", "ready"):
        return "验证失败/中断，回退实现"
    if frm == "implemented" and to in ("implementing", "ready"):
        return "实现未通过，回退重做"
    # 不可达分支（防御保留）：仅有的两个调用点（get_spec_timeline 的 Transition
    # 路径与打回重建路径）均在 backward 守卫内，而 backward 按生命周期序严格
    # 小于判定，frm == to 时恒为 False——ready→ready 在时间轴数据流中到不了
    # 这里（该转移会被当作前向节点折叠、本文案不下发）。保留仅因本函数经
    # 门面公开导出、可被直接调用（特征测试锁定此返回值），非时间轴下发路径。
    if frm == "ready" and to == "ready":
        return "实现失败，重试"
    return "状态回退"


def _load_billing_config(project_root) -> dict:
    """从 llm.providers[i].billing 收集 per-provider 计价表（improve-provider-billing-config）。

    返回 {provider_name: {"enabled": bool, "prices": [...]}}——仅登记声明了 billing
    子对象且卡片开关开启的 provider（enabled 关闭的卡片不收集：表非空即等价于
    design D2 的「有任一开启卡片才进入计价分支」闸门，未开启卡片由匹配函数
    直接无表项 → None，计费关闭不下发 cost 字段）。读失败/旧形态（顶层
    llm.billing）/异常一律容错返回空表（fail-open 不计价不崩溃）。
    """
    try:
        # 跨组引用（config_admin 组的 read_effective_config）经门面延迟解析（D4）
        import core.dashboard.data as _facade

        _llm = _facade.read_effective_config(project_root).get("llm") or {}
        providers = _llm.get("providers") or []
    except Exception:
        return {}
    table: dict = {}
    for p in providers:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        billing = p.get("billing")
        if not isinstance(name, str) or not name or not isinstance(billing, dict):
            continue
        # 形态异常（enabled 非布尔等）容错：跳过该卡片，不计价不崩溃
        if (
            "enabled" in billing
            and billing["enabled"] is not None
            and not isinstance(billing["enabled"], bool)
        ):
            continue
        if not billing.get("enabled"):
            continue
        prices = billing.get("prices")
        table[name] = {
            "enabled": True,
            "prices": prices if isinstance(prices, list) else [],
        }
    return table


def _admin_events_for_spec(project_root, spec_name: str) -> list:
    """过滤当前 SPEC 关联的 admin 运维事件，输出 kind="admin" 时间轴节点。

    数据源复用 AdminStore.read_all()（既有带锁、容错读，缺失/损坏返回 []）：
    - 过滤：kind in {escalation, disposition} 且 spec 精确匹配目标 SPEC；
      缺 spec 字段（历史脏数据）跳过，不误挂到当前 SPEC。
    - 归并：同 admin_run_id 的 disposition 组内存在非 pending 最终处置时
      （result/status 非 pending），仅保留最新最终处置，避免时间轴出现
      「永久处置中」；无最终处置保留 pending；无 admin_run_id 的记录独立成节点
      （与运维记录页 best_by_run 归并语义一致，不引入置顶/_pin 页面概念）。
    - 输出节点字段：time=created、kind="admin"、record_kind、signal_type、
      severity、description；状态字段 escalation 取 handled、disposition 取 result。
    - 读取异常 fail-open 返回空列表，时间轴照常渲染 state/run 两类节点。
    """
    from core.admin_store import AdminStore, DISPOSITION, ESCALATION

    try:
        records = AdminStore(project_root).read_all()
    except Exception:
        return []
    if not records:
        return []
    spec_records = [
        r
        for r in records
        if r.get("kind") in (ESCALATION, DISPOSITION) and r.get("spec") == spec_name
    ]
    if not spec_records:
        return []

    # 按 admin_run_id 归并 disposition：委托共享 merge_dispositions_by_run
    # （与运维记录页 get_admin_activities 同源单点；非 pending 优先于
    # pending、同态取 created 最新、无 admin_run_id 独立成组）。
    import core.dashboard.data as _facade

    best_by_run = _facade.merge_dispositions_by_run(spec_records)

    nodes: list[dict] = []
    for rec in spec_records:
        if rec.get("kind") == DISPOSITION:
            rid = rec.get("admin_run_id") or f"run-{id(rec)}"
            if best_by_run.get(rid, (False, None))[1] is not rec:
                continue  # 该 pending 已被最终处置替代
        node = {
            "time": rec.get("created") or "",
            "kind": "admin",
            "record_kind": rec.get("kind"),
            "signal_type": rec.get("signal_type"),
            "severity": rec.get("severity"),
            "description": rec.get("description") or "",
        }
        if rec.get("kind") == ESCALATION:
            node["handled"] = bool(rec.get("handled"))
        else:
            node["result"] = rec.get("result") or rec.get("status")
        nodes.append(node)
    return nodes


def _ocr_lane_summary(project_root, run_id: str) -> str:
    """ocr 车道 run 转录 start 事件的 message（审查对象摘要，车道可见性 1.1）。

    start 是车道 jsonl 首事件（maintenance_runs._write_impl_ocr_run_events：
    ``ocr 车道启动: <branch> <from8>..<to8>``），头扫前 20 行命中即停（与
    _first_run_event_ts 同模式——run 通用尾读口 _read_run_lines 读不到头部）。
    转录缺失/无 start/message 为空返回 ""（调用方静默省字段，不报错）。
    """
    try:
        import core.dashboard.data as _facade

        path = _facade.resolve_run_file(project_root, run_id)
        with path.open("rb") as f:
            for _ in range(20):
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") == "start":
                    return str(ev.get("message") or "").strip()
    except OSError:
        pass
    return ""


_DAEMON_LOG_RE = re.compile(r"fenixd.*\.log(?:\.(\d+))?")
# 日期命名历史产物（fenixdYYYY-MM-DD.log，旧版 logger 非轮转命名）：
# 统一排到最旧端——code-review item 691c672d8ad5
_DATE_NAMED_LOG_RE = re.compile(r"fenixd\d{4}-\d{2}-\d{2}\.log$")
# 日期命名序位哨兵：轮转序号 |N| 有界（backupCount=5），取远小于其下界的
# 常量即恒排任何轮转备份之前；组内 (seq, name) 的 name 含 YYYY-MM-DD，
# 字典序即时间 旧→新。
_DATE_NAMED_SEQ = -(10**9)


def _rotated_log_files(logs_dir: Path) -> list:
    """按时间序（旧→新）枚举 daemon 日志文件（含轮转备份）。

    core/logger.py 用 FlockRotatingFileHandler（maxBytes=10MB、backupCount=5）
    轮转，产物命名 fenixd.log（最新）、fenixd.log.1（次新）… fenixd.log.N
    （最旧）——序号越大越旧。原 glob "fenixd*.log" 要求以 .log 结尾，轮转备份
    fenixd.log.1/.2 不命中：created 锚点早于最近一次轮转时刻的 spec，其创建至
    轮转点之间的 Transition/打回日志全部留在备份里不被读取，时间轴开段静默
    缺失。故按正则枚举全部轮转产物并按 旧→新 排序——跨文件拼接窗口保持时间
    单调，且「开始验证」行靠遍历序取最后一轮（verify_start_ts），旧→新遍历下
    最后赋值恰为时间最新。正则同时保留原 glob 的日期命名全集
    （fenixdYYYY-MM-DD.log 等非轮转历史产物，旧版 logger 命名），不使历史日志
    脱离枚举；其序位统一排最旧端（比任何轮转备份更旧，组内按文件名内日期
    旧→新）——旧实现与基底同序位（seq=0）时按文件名排序（'.'<'2'）排在基底
    之后，遍历序里被当「最新」文件，其中的陈旧「开始验证」行会按末次赋值
    覆盖 verify_start_ts（item 691c672d8ad5）。非日志命名（fenixd.log.lock
    等伴随文件）不命中正则，跳过。
    """
    out: list[tuple[int, str, Path]] = []
    for lf in logs_dir.iterdir():
        m = _DAEMON_LOG_RE.fullmatch(lf.name)
        if m is None:
            continue
        # 基底序 0（最新）；备份序号 N 越大越旧 → 取 -N 使升序即 旧→新；
        # 日期命名历史产物统一排最旧端（组内文件名日期字典序 旧→新）
        if m.group(1):
            seq = -int(m.group(1))
        elif _DATE_NAMED_LOG_RE.fullmatch(lf.name):
            seq = _DATE_NAMED_SEQ
        else:
            seq = 0
        out.append((seq, lf.name, lf))
    out.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in out]


def _spec_transition_patterns(spec_name: str):
    """SPEC 状态转移正则对 ``(Transition 前缀, Gate transition 前缀)``。

    timeline.get_spec_timeline 与 topology._scan_spec_log_events 的同源单点
    （code-review item 6b53202b854e）：两视图状态转移口径（前缀集 + from/to
    捕获组序）必须逐字一致，收敛于此防任一侧调整（如新增日志前缀）另一侧
    漏改。正则只依赖循环不变的 spec_name，调用方在文件循环外编译一次。
    """
    esc = re.escape(spec_name)
    pat = re.compile(r"Transition: " + esc + r"\s+([\w-]+)\s*→\s*([\w-]+)")
    # fix-observability-gaps 3.1：Gate transition（小写 t，state_machine
    # transition_gate 前缀）旧正则 `Transition: ` 不命中（`pat.search
    # ('Gate transition: fix-foo verified → testing')` → False）；结构化
    # 写侧两条前缀同判，正则兜底只覆盖 `Transition: `（旧格式无 Gate 行）。
    gate_pat = re.compile(r"Gate transition: " + esc + r"\s+([\w-]+)\s*→\s*([\w-]+)")
    return pat, gate_pat


def _parse_daemon_log_line(line: str):
    """daemon 日志 JSON 行 → ``(msg, ts, ctx)``；守卫梯队判跳过的行返回 None。

    timeline.get_spec_timeline 与 topology._scan_spec_log_events 共同的逐行
    防护梯队（同源单点，code-review item 6b53202b854e）：
    - JSON 解析失败 → None；合法 JSON 但非对象（裸字符串/数组等）的行取
      不到字段 → None，避免 AttributeError 令整个接口失败；
    - message 非字符串（数字/数组等异常 JSON 行）→ None（下游 pat.search
      会抛 TypeError）；
    - timestamp 非字符串归一为空串：节点 time 字段与下游排序键入参恒为
      字符串（空串走解析失败排末尾/解析失败的既定分支）；
    - context 非 dict 归一为 {}（下方 ctx.get 的防护口径）。

    内部事件字典命名 ``ev``（行级局部名）：MUST NOT 命名 ``entry``——
    get_spec_timeline 的函数参 entry 是 STATE 条目（注记块同参透传判据），
    遮蔽会让「不透传 entry」的调用点误附 ocr_gate。
    """
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    if not isinstance(ev, dict):
        return None
    msg = ev.get("message", "")
    if not isinstance(msg, str):
        return None
    ts = ev.get("timestamp", "")
    if not isinstance(ts, str):
        ts = ""
    ctx = ev.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    return msg, ts, ctx


def get_spec_timeline(
    project_root, spec_name: str, created: str = "", entry: "dict | None" = None
) -> list:
    """构建 SPEC 生命周期时间轴（按时间排序）。

    数据源：
    - 事件日志（fenixd.log 及轮转备份 fenixd.log.N）中的
      `Transition: <spec> from → to` → 状态节点
    - `.fenix/runs/` 运行产物 → 运行节点（可点击展开 LLM 对话）

    日志读取窗口按 created 锚定（_read_log_window_from）且覆盖轮转备份
    （_rotated_log_files 按 旧→新 逐文件拼接，序号越大越旧）：长周期 spec 的
    早期事件不再被尾部 1MB 尾窗或轮转边界静默截断；created 缺失（存量/归档
    条目）退化为全文件读取。单文件内时间戳单调，锚定在各文件内部同样成立；
    锚点早于某备份首行时该备份全文件读取（早期事件可回看所必需，量受
    backupCount 上界约束，仅低频 REST 详情页触达），锚点晚于备份全部内容时
    只读其尾块，冗余行由 spec 名过滤兜底。

    每条:
    - 状态: {time, kind:"state", from, to, reason}  （回退节点带 reason）
    - 运行: {time, kind:"run", run_id, agent_type, status}

    可选 ``entry``（STATE 条目，调用方 spec_detail 透传）：提供时最新的
    「→ testing」状态节点附 ``ocr_gate: {status, detail}``——ocr 门当前状态，
    经 quality_gates.parse_quality_gates 公开入口与门禁 Card 同参合成（同源
    硬约束：MUST NOT 复制第二套三态判定）；缺省时任何节点不附该字段。
    """
    # 跨组引用（log_index 组 / runs 组 / quality_gates 组）经门面延迟解析（D4）：
    # 函数体开头统一 import 一次，循环体内与后段复用 _facade 局部名
    import core.dashboard.data as _facade

    logs_dir = Path(project_root) / ".fenix" / "logs"
    events: list[dict] = []
    errors_at: list[tuple] = []  # (timestamp, error) —— Agent 记录的 error，作为回退原因
    # (timestamp, new_status, err) —— update_spec 直写的 status 变更（打回路径，
    # 无 Transition 行；add-agent-prompt-files 事故：时间轴上看不到打回与原因）
    status_updates: list[tuple] = []
    verify_start_ts = ""  # 最近一轮 verify_engine「开始验证」日志时刻（报告只有完成时刻）

    if logs_dir.is_dir():
        try:
            # 旧→新 枚举（含轮转备份 fenixd.log.N，_rotated_log_files 内注释
            # 说明 glob "fenixd*.log" 漏掉轮转产物导致开段缺失的根因）
            log_files = _rotated_log_files(logs_dir)
        except OSError:
            log_files = []
        # 状态转移正则对单源委托 _spec_transition_patterns（与
        # topology._scan_spec_log_events 同参同源，code-review item
        # 6b53202b854e）；正则只依赖循环不变的 spec_name，提到文件循环外
        # 只编译一次
        pat, gate_pat = _spec_transition_patterns(spec_name)
        for lf in log_files:
            try:
                # created 锚定窗口（原尾部 1MB 尾窗对早期事件静默截断）；
                # 锚点早于文件首行 → 整文件，锚点晚于文件尾 → 仅尾块，量均有限
                content = _facade.read_log_window_from(Path(project_root), lf, created).decode(
                    "utf-8", errors="replace"
                )
            except OSError:
                continue
            for line in content.split("\n"):
                if spec_name not in line:
                    continue
                # 逐行守卫梯队（JSON 解析→非 dict 跳过→message/timestamp 类型
                # 归一→ctx 归一）单源委托 _parse_daemon_log_line（与
                # topology._scan_spec_log_events 同参同源，code-review item
                # 6b53202b854e）；None 即守卫梯队判跳过的行
                parsed = _parse_daemon_log_line(line)
                if parsed is None:
                    continue
                msg, ts, ctx = parsed
                # ── 结构化优先（fix-observability-gaps 3.1）──
                # 写侧（state_machine.transition / transition_gate）已带
                # 结构化 context（channel 键 = 写侧升级标记）。同一条日志行
                # 有 context 走结构化解（含 Gate transition 前缀）、无 context
                # 走正则兜底（历史日志），逐行互斥——同一行不产出两个状态节点。
                m = pat.search(msg) or gate_pat.search(msg)
                if m:
                    frm, to = m.group(1), m.group(2)
                    # 方向单源：backward 按生命周期序判定（与打回重建路径
                    # 同式），Transition 回退判定复用为该字段来源；frm/to
                    # 任一未登记状态显式按前向处理（_lifecycle_backward）
                    backward = _lifecycle_backward(frm, to)
                    reason = _backtrack_reason(frm, to) if backward else ""
                    node = {
                        "time": ts,
                        "kind": "state",
                        "from": frm,
                        "to": to,
                        "reason": reason,
                        "backward": backward,
                    }
                    if ctx.get("channel") is not None:
                        # 结构化 context 落入节点（channel/trigger_run_id/
                        # agent_type），供前端展示转换来源
                        node["channel"] = ctx.get("channel")
                        node["trigger_run_id"] = ctx.get("trigger_run_id")
                        node["agent_type"] = ctx.get("agent_type")
                    events.append(node)
                    continue  # 本行已消费为状态节点，不再进入 Updated SPEC 分支
                # 带引号全匹配（写点唯一于 state_machine.update_spec 的
                # f"Updated SPEC '{spec_name}'"）：子串匹配会让前缀名 spec
                # （如 add-foo）吸收姊妹 spec（add-foo-ui）的状态更新
                if "Updated SPEC" in msg and f"'{spec_name}'" in msg:
                    # 复用上方已 isinstance 归一化的 ctx 取 updates（非 dict 视为缺失）
                    updates = ctx.get("updates", {}) or {}
                    # updates 为非 dict 真值（日志行被手改/部分写入/旧版本结构
                    # 漂移）时按缺失处理，对齐同函数 ctx 与 report.summary 的
                    # 防护口径：否则下方 updates.get 抛 AttributeError 沿时间轴
                    # 接口穿透 500
                    if not isinstance(updates, dict):
                        updates = {}
                    err = updates.get("error")
                    if err:
                        errors_at.append((ts, str(err)))
                    new_status = updates.get("status")
                    if new_status:
                        status_updates.append((ts, str(new_status), str(err) if err else ""))
                if "开始验证" in msg and f"'{spec_name}'" in msg:
                    # verify_engine 每轮开跑的唯一一行（多轮验证取最后一轮，
                    # 与每轮覆盖的 report.json 配对）
                    verify_start_ts = ts

    # 运行节点（含归档：SPEC 归档后运行节点随产物清理消失，归档前全程可回看
    # ——fix-run-cleanup-attach-spec-archive D5）。
    # improve-provider-billing-config（D2）：计价表非空（有任一声明 billing 的
    # 卡片）时进入计价分支，逐 run 按「实际网关卡片开关 + 行 model 匹配」现算
    # cost_usd（None 不下发）；表空时整条时间轴无成本字段（前端不渲染）。
    billing_table = _load_billing_config(project_root)
    runs = _facade.get_runs(project_root, spec_name, include_archive=True)
    for r in runs:
        insights = _facade.run_tail_insights(_facade.resolve_run_file(project_root, r["run_id"]))
        node = {
            "time": r["started"],
            "kind": "run",
            "run_id": r["run_id"],
            "agent_type": r["agent_type"],
            "status": r["status"],
            "spec": r.get("spec"),
            "duration_seconds": r.get("duration_seconds"),
            # add-harness-brand-projection 3.1：harness 随 runs 列表行透出到
            # 时间轴 run 节点——detail 页「查看运行记录」弹窗/内嵌 pane 的
            # 品牌投影数据源（缺省 claude 已在 get_runs 兜底）
            "harness": r.get("harness"),
            "summary": insights["summary"],
            "llm": insights["llm"],
            "reason": insights["reason"],
        }
        if r.get("agent_type") == "impl-ocr":
            # 车道可见性 1.1：审查对象摘要（转录 start 事件 message），缺失静默省字段
            lane_summary = _ocr_lane_summary(project_root, r["run_id"])
            if lane_summary:
                node["lane_summary"] = lane_summary
        if billing_table:
            model, provider = _facade.split_llm_marker(insights["llm"])
            cost = _facade.compute_run_cost(insights["usage"], model, provider, billing_table)
            if cost is not None:
                node["cost_usd"] = cost
        events.append(node)

    # ── 验证执行节点：verify_engine 是确定性引擎而非 agent run（不产生
    # runs/*.jsonl），时间轴原本不可见——full 模式 testing→verified 之间无节点
    # 打断折叠，观感是「实现完直接连跳已推送」（fix-provider-transient-backoff
    # 误读事故）。report.json 仅引擎验证写入（fast-track 的 agent 自验不产生），
    # 时间取日志「开始验证」行（引擎开始时刻，报告只有完成时刻）；日志行缺失
    # 退化用报告完成时刻（与 verified 转换同秒，靠 _timeline_sort_key 第三键
    # 精确时间排在 verified 之前）。多轮验证 report 每轮覆盖 → 只留最后一轮。
    report = _facade.parse_report(project_root, spec_name)
    if report.get("exists") and not report.get("error"):
        # summary 为非 dict 真值（report.json 被手改/部分写入）时按空处理，
        # 对齐 summary.py spec_detail 对 scenarios 的防护口径：否则下方
        # summary.get 抛 AttributeError 沿时间轴接口穿透 500。
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        rep_ts = str(report.get("timestamp", "") or "")
        # 时间优先取日志「开始验证」行（引擎开始时刻）；缺失退化报告完成时刻
        v_time = verify_start_ts or rep_ts
        if v_time:
            v_node: dict = {
                "time": v_time,
                "kind": "verify",
                "total": summary.get("total"),
                "passed": summary.get("passed"),
                "failed": summary.get("failed"),
                "warnings": summary.get("warnings"),
                "errors": summary.get("errors"),
            }
            if verify_start_ts and rep_ts:
                # 带符号差值：报告完成时刻早于「开始验证」时刻（时钟回拨等
                # 异常时序）时长为负，非负守卫真正生效——丢弃而不下发
                d = _ts_delta(rep_ts, verify_start_ts, signed=True)
                if d is not None and d >= 0:
                    v_node["duration_seconds"] = int(d)
            if report.get("env_error"):
                v_node["env_error"] = str(report["env_error"])[:200]
            events.append(v_node)

    # ── 打回节点重建：update_spec 直写 status 的变更（无 Transition 行）补建状态节点 ──
    # transition() 成对写的 Updated SPEC 行（与 Transition 节点 Δt<2s 且目标相同）去重跳过；
    # 未匹配的按时间与 Transition 节点合流推演 current status 得 from（窗口截断推不出 → "?"），
    # reason 取同行 error（精确）；无 error 时回退 _backtrack_reason 兜底（允许 errors_at 就近覆盖）。
    trans_states = [e for e in events if e.get("kind") == "state"]
    unmatched: list[tuple] = []
    for ts, new_status, err in status_updates:
        # [fenix-ignore:b10628549731] transition() 成对两行毫秒级间隔，仅时钟步进/回拨恰好跨写入瞬间才破 2s 去重窗（低概率边界，未证实部署环境存在步进时钟），维持现状不做结构化配对
        paired = any(
            (d := _ts_delta(t2["time"], ts)) is not None and d < 2 and t2["to"] == new_status
            for t2 in trans_states
        )
        if not paired:
            unmatched.append((ts, new_status, err))
    if unmatched:
        merged = sorted(
            [(e["time"], 0, "t", e["to"], "") for e in trans_states]
            + [(ts, 1, "u", ns, err) for ts, ns, err in unmatched],
            key=lambda x: (str(x[0]), x[1]),
        )
        current: "str | None" = None
        for ts, _, tag, to, err in merged:
            if tag == "t":
                current = to
                continue
            frm = current if current is not None else "?"
            # 方向按生命周期序判定（与 Transition 路径同式）。前向节点不落
            # 「状态回退」兜底文案：无同行 err 时 reason 置空（可被折叠链
            # 合并，与 Transition 前向节点行为一致）——从结构上消除前向节点
            # 被 errors_at 就近覆写传染的通道；有同行 err 时 reason=err
            # （_precise_reason 保护不被覆写）。回退节点维持现状。
            # frm 推演不出（"?"，窗口截断）时不做序比较："?" 未登记进
            # _LIFECYCLE_ORDER，_lifecycle_backward 显式按前向/未知处理，
            # 不会把前向直写（如 update_spec 直达 implemented/done）误渲染
            # 成「状态回退」（reason 同前向节点：同行 err 优先，无 err 置空
            # 可被折叠链合并；起始状态未知不落「状态回退」兜底文案）。
            backward = frm != "?" and _lifecycle_backward(frm, to)
            if backward:
                reason = err[:120] if err else _backtrack_reason(frm, to)
            else:
                reason = err[:120] if err else ""
            events.append(
                {
                    "time": ts,
                    "kind": "state",
                    "from": frm,
                    "to": to,
                    "reason": reason,
                    "backward": backward,
                    "_precise_reason": bool(err),
                }
            )
            current = to

    # admin 运维事件节点（escalation + disposition）：与 state/run 节点统一
    # 按事件时间排序（admin 在 _timeline_sort_key 中 rank=1，夹在 state/run 间）。
    # 折叠逻辑零改动：admin 节点非 state，天然打断连续前向状态折叠。
    events.extend(_admin_events_for_spec(project_root, spec_name))

    # 排序：解析时间戳 + 同秒内 state 先于 run（_timeline_sort_key 内注释说明根因）
    events.sort(key=_timeline_sort_key)

    # 连续的前向状态转换折叠为一次（回退/运行节点打断）
    events = _collapse_timeline(events)

    # ── 立项原话附着（add-timeline-origin-request 任务 2.1）──
    # 排序+折叠完成后，经门面 resolve_spec_dir 解析 spec 目录（活跃/归档通吃）
    # 读取 request.md（用户 /fenix-new 立项原话，写侧唯一入口 fenix-new SKILL
    # §3.1.3），非空时把原文附到首个 state 节点的 origin_request 字段（含折叠
    # 链节点），其余节点不携带。
    # fail-open 对齐 lane_summary 模式（design D2）：文件缺失、spec 目录解析
    # 不出、读取异常、内容 strip 后为空、时间轴无任何 state 节点均静默省字段
    # ——state 节点唯一来源是日志窗口（轮转 5×10MB 有界留存），超窗/归档清理
    # 后可为空，此况 MUST NOT 退化挂到 run/verify/admin 等其它 kind 节点；
    # request.md 本体随 spec 目录入库与归档迁移，原话始终可从 spec 目录直接
    # 追溯，展示层降级不丢数据。
    first_state = next((e for e in events if e.get("kind") == "state"), None)
    if first_state is not None:
        try:
            spec_dir = _facade.resolve_spec_dir(project_root, spec_name)
            origin = spec_dir.joinpath("request.md").read_text(encoding="utf-8") if spec_dir else ""
            if origin.strip():
                first_state["origin_request"] = origin
        except Exception:  # noqa: BLE001 —— 读取异常按缺失同口径静默省字段
            pass

    # ── testing 停等注记（add-timeline-ocr-lane-visibility 任务 1.2）──
    # 最新状态转移节点 to == "testing" 时附 ocr 门**当前**状态（表达进行时语义，
    # 非历史转移时刻状态）。同源硬约束：经 quality_gates.parse_quality_gates
    # 公开入口（MUST NOT import 私有 _code_review_status 绕过 entry/runs 解析），
    # entry/runs 与门禁 Card 同参透传——worktree 候选与指纹校验逐字同源，两处
    # 口径永不漂移。仅最新一个节点可携带（历史节点天然无注记）；entry 缺省
    # （既有调用点）与非 testing 节点不附字段；合成异常 fail-open 不影响时间轴。
    if entry is not None:
        latest_state = next((e for e in reversed(events) if e.get("kind") == "state"), None)
        if latest_state is not None and latest_state.get("to") == "testing":
            try:
                gates = _facade.parse_quality_gates(
                    project_root, spec_name, entry=entry, runs=runs
                )
                ocr = next(
                    (it for it in gates.get("items", []) if it.get("id") == "code-review"),
                    None,
                )
                if isinstance(ocr, dict):
                    latest_state["ocr_gate"] = {
                        "status": str(ocr.get("status") or ""),
                        "detail": str(ocr.get("detail") or ""),
                    }
            except Exception:  # noqa: BLE001 —— 注记缺失不影响时间轴渲染
                pass

    # 回退节点补充 Agent 记录的 error 作为原因（取时间最近的一条，10 分钟内）；
    # 打回重建节点（_precise_reason）reason 已是同行精确 error，不覆盖
    if errors_at:
        for e in events:
            if e.get("kind") != "state" or not e.get("reason") or e.get("_precise_reason"):
                continue
            deltas = [
                (d, err) for (ts, err) in errors_at if (d := _ts_delta(ts, e["time"])) is not None
            ]
            if deltas:
                d, err = min(deltas, key=lambda x: x[0])
                if d < 600:  # 10 分钟内匹配到 Agent 记录的 error
                    e["reason"] = err[:120]
    for e in events:
        e.pop("_precise_reason", None)  # 内部标记不外泄
    return events


def _collapse_timeline(events: list) -> list:
    """把连续的前向状态转换折叠为一次（from[首] → to[尾]）。

    规则：
    - 连续出现的「前向状态节点」（无 reason）合并为一个节点，展示整体跨度；
      如 drafted→ready / ready→implementing / … → 折叠为 drafted → implementing。
      折叠时携带 chain（完整状态序列，首尾与 from/to 一致）：前端展开渲染
      全部中间状态不省略（fast-track 连跳 implemented→testing→verified→
      done→pushed 若只显示一头一尾，会掩盖 testing/verified 等真实途经状态）。
    - 回退节点（带 reason，如 testing→bug-found）与运行节点保持独立，并打断合并。
    """
    out: list[dict] = []
    buf: list[dict] = []  # 待合并的前向状态节点缓冲

    def _flush() -> dict:
        # 折叠缓冲按构造只收前向节点（回退节点带 reason 天然打断），backward=false
        node = {
            "time": buf[0]["time"],
            "kind": "state",
            "from": buf[0]["from"],
            "to": buf[-1]["to"],
            "reason": "",
            "backward": False,
        }
        if len(buf) > 1:
            node["chain"] = [buf[0]["from"]] + [b["to"] for b in buf]
        # fix-observability-gaps 3.1：结构化 context（channel/trigger_run_id/
        # agent_type）随折叠链保留——取链上第一个非 None 的组成节点值
        # （混合窗口下链首可能是旧格式无 context 行，溯源到新格式行即保留）。
        for _ctx_key in ("channel", "trigger_run_id", "agent_type"):
            for _b in buf:
                if _b.get(_ctx_key) is not None:
                    node[_ctx_key] = _b[_ctx_key]
                    break
        return node

    for e in events:
        if e.get("kind") == "state" and not e.get("reason"):
            buf.append(e)
            continue
        # 遇到回退状态 / 运行节点 / 其它 → 先冲刷缓冲，再追加当前事件
        if buf:
            out.append(_flush())
            buf = []
        out.append(e)
    if buf:
        out.append(_flush())
    return out


def _parse_iso_ts(ts: str):
    """解析 ISO 时间戳（兼容 Z 后缀与 +00:00），失败返回 None。

    add-timelib-consolidation-layer 3.2：解析收拢至 timelib.parse_ts，**推翻**
    fix-deferred-findings D2 的「naive 补 tzinfo=utc」——naive 统一按本地
    解读（timelib 唯一策略，design D1）。该域写手验读
    （tests/test_timelib_readside.py）：admin_store/runner/verify_engine/
    logger 写手全部 aware（``Z`` 或 ``+00:00``），naive 仅历史/外部人工数据
    （实测多为本地 now()，含 code_review 剥时区链产出的 naive 本地）——
    切换后该类时间戳的排序/展示时刻平移一个时区偏移（修正而非回归）。
    """
    return timelib.parse_ts(ts)


def _timeline_sort_key(e: dict):
    """时间轴排序键：(秒截断时间, kind 次序, 精确时间)。

    不能直接对原始字符串排序：日志时间为微秒+Z（…31.212625Z），运行 started
    为秒级+00:00（…31+00:00），同一秒内 '+' < '.' 会把运行节点排到状态转移前。
    也不能只按解析后时间排序：run started 取自 run_id 的 int(time.time()) 秒
    截断，真实启动在该秒内、且必然晚于同秒发生的状态转移（先 transition 后
    spawn，见 pm_engine/dispatch.py），故同秒内 state 恒先于 run。
    admin 运维节点（add-timeline-admin-events）夹在中间：同秒内的真实时序是
    「状态转移（testing→bug-found）→ admin 处置完成 → 触发重派的 run 启动」，
    kind 次序显式映射为 state=0、admin=1、run=2（state/run 相对次序不变）。
    verify（验证执行节点）与 state 同 rank：退化场景（日志「开始验证」行缺失）
    节点取报告完成时刻、与 verified 转换同秒且真实次序在前（报告先落盘），
    须靠第三键精确时间排在 verified 之前；正常场景（引擎开始时刻）独占一秒，
    rank 不参与。
    解析失败的事件按原字符串排在末尾，保持稳定（fix-deferred-findings P0：
    `datetime.max` 的 tzinfo 参数必须是实例，无效时间戳事件不再抛 TypeError）。
    """
    dt = _parse_iso_ts(e.get("time", ""))
    if dt is None:
        from datetime import datetime as _dt, timezone as _tz

        return (_dt.max.replace(tzinfo=_tz.utc), 2, str(e.get("time", "")))
    kind_rank = {"state": 0, "verify": 0, "admin": 1, "run": 2}.get(e.get("kind"), 2)
    return (dt.replace(microsecond=0), kind_rank, dt)


def _ts_delta(a: str, b: str, signed: bool = False):
    """两个 ISO 时间戳的秒级差值（解析失败返回 None）。

    默认取绝对值（邻近度匹配/时长兜底场景）；signed=True 返回带符号差值
    a - b，供需区分先后方向的调用点（如验证节点时长：报告时刻早于开始
    时刻属异常时序，负值应丢弃而非被 abs 翻正下发）。
    """
    ta = _parse_iso_ts(a)
    tb = _parse_iso_ts(b)
    if ta is None or tb is None:
        return None
    delta = (ta - tb).total_seconds()
    return delta if signed else abs(delta)


def _timeline_with_retry(timeline: list, project_root, entry: dict) -> list:
    """把 spec 当前实现重试轮次附到时间轴最后一个运行节点（retry-display）。

    重派计数是 spec 级状态（STATE.md `_retry_count`），run 产物无逐节点历史
    快照——只在最新 run 节点呈现当前值（>0 时），历史节点不伪造。分母取
    有效配置 `agents.max_retries`（ConfigLoader.resolve_config 用户级+项目级
    深合并，与派发侧 runner._get_config 同口径；缺失/异常回退 3，与 dispatch
    取值默认一致；read_effective_config 是受管键白名单视图，不含 max_retries）。
    取值后按派发侧同构规则钳制（runner._execute_agent_inner：0/负数被
    max(1, ...) 收口到 1），展示口径与真实 attempt 循环一致。
    """
    try:
        count = int(entry.get("_retry_count") or 0)
    # OverflowError 同捕（STATE.md 为 YAML 方言、字段被手写成 .inf 时解析为
    # float inf，int() 抛溢出——与 summary._judge_stat_or_none/_int_or_zero
    # 同口径，code-review item 53612ac26ee4）
    except (TypeError, ValueError, OverflowError):
        count = 0
    if count <= 0 or not timeline:
        return timeline
    max_r = 3
    try:
        from core.config import ConfigLoader

        cfg = ConfigLoader.resolve_config(Path(project_root))
        # 下限钳制与派发侧 runner._execute_agent_inner 同构：0/负数会被
        # max(1, ...) 收口到 1。不写 `or 3`——那会把合法配置的 0 静默
        # 吞成 3、负数原样透传，展示与真实派发行为脱节。
        max_r = max(1, int(ConfigLoader.get(cfg, "agents.max_retries", 3)))
    except (TypeError, ValueError, OverflowError):
        # resolve_config 自兜底（文件缺失/解析失败降级空 dict），此处仅防
        # max_retries 配出非数值——回退默认 3，展示信号不阻断时间轴
        pass
    for e in reversed(timeline):
        if e.get("kind") == "run":
            e["retry_count"] = count
            e["retry_max"] = max_r
            break
    return timeline


def _cost_summary_from_timeline(timeline: list) -> dict:
    """汇总时间轴内可计价 run 的成本（add-model-billing-cost-display D4）。

    Returns: {"computed_usd": float|None, "priced_runs": int, "unpriced_runs": int}
    可计价 run 的成本求和；至少一个可计价 run 时 computed_usd 非 None（否则为
    None = 全部不可计价，界面展示「成本不可用」）。
    """
    total = 0.0
    priced = 0
    unpriced = 0
    for e in timeline:
        if e.get("kind") != "run":
            continue
        cost = e.get("cost_usd")
        if cost is None:
            unpriced += 1
        else:
            priced += 1
            total += cost
    return {
        "computed_usd": total if priced else None,
        "priced_runs": priced,
        "unpriced_runs": unpriced,
    }


# 公开访问面（code-review item 329a77d10a7e）：summary.py 跨组引用改用公开名
# （不跨组消费下划线私有名），与各私有实现同一函数对象单源绑定。
timeline_with_retry = _timeline_with_retry
load_billing_config = _load_billing_config
cost_summary_from_timeline = _cost_summary_from_timeline
# 公开访问面（code-review item 19f8899fac87）：runs.py 跨组消费改用公开名，
# 与 _parse_iso_ts 同一函数对象单源绑定。
parse_iso_ts = _parse_iso_ts
# 公开访问面（add-spec-topology-bigscreen）：topology 组跨组消费改用公开名，
# 不消费下划线私有名（同上方 329a77d10a7e 先例）——轮转日志枚举与 admin
# 运维事件均为拓扑派生的既有 timeline 数据源，同一函数对象单源绑定。
rotated_log_files = _rotated_log_files
admin_events_for_spec = _admin_events_for_spec
# 公开访问面（code-review item 6b53202b854e）：topology 组跨组消费改用公开名
# （同上方先例）——SPEC 状态转移正则对、daemon 日志逐行守卫梯队与时间差助手
# 为 timeline/topology 两视图共同单源，防第二份逐行副本口径漂移。
spec_transition_patterns = _spec_transition_patterns
parse_daemon_log_line = _parse_daemon_log_line
ts_delta = _ts_delta
