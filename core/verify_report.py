"""verify_report.py — 验证报告产物闸门与共享合成器（add-verify-report-gate）。

保障 ``spec/changes/<spec>/verification-report.md`` 在验证裁决放行时
必然存在于磁盘：

  - 裁决 Agent 主动写入的报告优先——文件已存在且**与本轮裁决一致**时闸门直接
    放行，MUST NOT 覆盖或改写（含 mtime）。
  - 文件缺失时由框架从结构化数据（``.fenix/verify-progress/<spec>/report.json``
    与 ``.fenix-run-result.json``）确定性合成——纯本地渲染，零 LLM 成本。
    （judge 效率治理 2026-09-06：judge prompt 已删「写 md」步骤，合成由此
    转正为常规路径；裁决 Agent 主动写入仍优先兼容。）
  - 文件存在但属**上一轮残留**时重新合成覆盖——报告是「每轮裁决产物」，
    陈旧报告会让仪表盘与下游修复引用读到已失效的结论（见
    ``_report_is_superseded``）。
  - 结构化数据也不可用时 fail-closed：不写空报告、阻断状态推进，
    并发 human-escalation-alerts 告警（此时才代表真异常）。

合成格式与 ``core/dashboard/data.py`` 的 ``parse_verdict`` 兼容：
``## 结论：`` 标题行（内联 ✅/❌ 状态）、``**状态：...**`` 详情行、
``| 通过 | N |`` 形式的汇总表格、bug-found 时的「真实产品 Bug」章节。

单一实现（design D2）：闸门（pm_engine 裁决放行路径）是本模块的唯一新调用方，
下游（如修复任务注入）复用 ``synthesize_verification_report`` /
``ensure_verification_report``，禁止第二套渲染逻辑。
"""

import fcntl
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from core.fs_utils import atomic_write_text
# verify-progress 路径成分净化（读取侧与写侧 engine._safe_component 同口径，
# code-review item f19f580d2734）：spec_name 含分隔符或纯点成分时，读侧裸拼
# 会与写侧净化后路径错位，闸门恒判 report.json 缺失。仅收敛 verify-progress
# 拼接点；spec/changes/<spec_name> 侧路径须与既有 spec 目录名逐字一致，不净化。
from core.verify_engine.path_safety import safe_component

# 告警 signal_type（human-escalation-alerts 能力，.fenix/admin_alerts.json）
SIGNAL_MISSING = "verify_report_missing"

# 升级告警写入节流（分钟）：同 spec 同类信号冷却期内不重复落库，
# 防止多轮重验反复刷屏。独立固定值，不读取配置——与
# admin.escalation_cooldown_minutes（缺省 60 分钟）无关，两者数值也不同。
_ALERT_COOLDOWN_MINUTES = 15

# 合成报告携带的「合成源轮次指纹」标记：报告属哪一轮裁决的机器可读留痕。
# 人读行内标记，取值为无空格无标点的 token（见 current_round_fingerprint）。
_FINGERPRINT_MARKER = "合成源轮次指纹："
_FINGERPRINT_RE = re.compile(re.escape(_FINGERPRINT_MARKER) + r"([^\s，。）|]+)")

# 存量报告无指纹时的兜底判据：解析 md 声明的结论行与汇总计数（与
# dashboard.data.parse_verdict 同款语法，两处必须同源演进）。
_MD_CONCLUSION_RE = re.compile(r"^#{2,4}\s*(?:判定)?结论\s*(?:摘要)?\s*[：:]?\s*(.*)$", re.M)
_MD_COUNT_RE = re.compile(r"^\|\s*(通过|失败|错误)\s*\|\s*([^|]+?)\s*\|", re.M)

# 报告入库 git 子进程超时（秒）：照 core/archive_commit.py 惯例，探测最快、
# add 居中、commit 最慢（锁冲突等待窗口更长）。
_REPORT_PROBE_TIMEOUT = 30
_REPORT_ADD_TIMEOUT = 60
_REPORT_COMMIT_TIMEOUT = 120


def _atomic_write(path: Path, content: str) -> None:
    """mkstemp 唯一临时文件 + fsync + os.replace 原子写（core.fs_utils 单一实现）。

    权限口径（item 8b26fd7980ce 收口两份拷贝，本模块原语义不变）：替换**既有**
    文件时继承其原权限——运维若刻意把产物（verification-report.md /
    report.json / verdict_stability.json）收紧为 0600，「Agent 手写 → 框架重
    合成覆盖」一轮不应被静默放宽；**新**文件放宽到 0644，与常规 write_text
    的 umask 缺省一致。与 verify_scenarios 版「恒 0644」的差异由
    ``atomic_write_text(inherit_existing_mode=...)`` 参数显式表达，不再各持
    一份拷贝各自漂移（截断防护/收尾纪律见 core/fs_utils.py docstring）。
    """
    atomic_write_text(path, content, inherit_existing_mode=True)


# ── 结构化数据读取 ────────────────────────────────────────────────


def _load_report_json(project_root, spec_name):
    """读取验证引擎 report.json；不可用返回 None（不抛出）。"""
    path = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / "report.json"
    )
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    def _summary_usable(summary):
        """summary 可采信门槛（列表/键缺失两分支共用，勿单侧漂移）：total>0
        且显式声明 failed/errors 键（引擎 _build_report 恒写全套计数键，合法
        截断报告必满足）；total 缺失/为 0/不可解析或缺声明一律 False，按占位
        报告拒收（fail-closed）。"""
        try:
            return (
                int(summary.get("total") or 0) > 0
                and "failed" in summary
                and "errors" in summary
            )
        except (TypeError, ValueError):
            return False

    scenarios = data.get("scenarios")
    summary = data.get("summary")
    # 有效性判据（fail-closed，勿放宽为「list 或 dict 即可用」）：scenarios 须为
    # **非空**列表（且至少含一个 dict 元素），或 summary 为带计数键的 dict。
    # 「scenarios: []」且 summary 缺失/为空是截断/写坏形态——采信它会经「空场景
    # 集 + 无失败证据」一路推导出 verified，合成出「全部场景通过」的假通过报告，
    # 与模块 fail-closed 哲学（不写空报告、阻断推进）相反。纯非 dict 元素列表
    # （如 ["x", "y"]）同按写坏形态拒收（code-review 2a8e50608531）：summary
    # 缺失时 _derive_status 的场景计数兜底循环对非 dict 元素 isinstance 全部
    # 跳过、循环后落到 return "verified"，同样为损坏报告合成「全部场景通过」
    # 的假通过——与 03296ed3a49e/cbea2bb63e40/c0bc338cd2ea 同族 fail-closed。
    if (
        isinstance(scenarios, list)
        and scenarios
        and any(isinstance(sc, dict) for sc in scenarios)
    ):
        return data
    if isinstance(summary, dict) and any(
        key in summary for key in ("total", "passed", "failed", "errors")
    ):
        # summary-present 变体同样要防：引擎验收失败/Runner 初始化失败路径写下
        # 的占位报告（_build_report([])）正是「scenarios=[] + summary 带全套
        # 计数键（total=0/failed=0）」形态，采信它会经「failed=0 且声明了
        # failed 键」推出 verified——即上面注释防住的假通过形态换了变体。
        # 故 scenarios 为空列表时要求 summary.total > 0 才可用（total>0 说明
        # 确有场景跑过，scenarios 明细缺失属截断而非占位）；total 缺失/为 0/
        # 不可解析一律按占位报告拒收（fail-closed）。
        # 且须 summary 显式声明 failed 与 errors 键（引擎 _build_report 恒写
        # 全套计数键，合法截断报告必满足）：仅带 total 的 summary 携带零失败
        # 证据，_derive_status 的 summary 分支因未声明失败键落到场景计数兜底，
        # 空场景集推不出 bug-found，最终仍推出 verified——「total>0 即放行」
        # 的假通过漏网变体（code-review 03296ed3a49e），同按 fail-closed 拒收。
        if isinstance(scenarios, list):
            if _summary_usable(summary):
                return data
            return None
        # scenarios 为非列表形态（dict/str/int 等写坏形态）同按 fail-closed
        # 拒收：此处无条件放行会绕过上面 total>0 与 failed/errors 键门，
        # 采信「scenarios=0 + summary 全 0」这类损坏形态后 _derive_status 经
        # summary 分支推出 verified、verdict_failed_ids 对非列表 scenarios
        # 迭代得空失败集，合成「全部场景通过」的假通过报告
        # （code-review cbea2bb63e40）。
        if scenarios is not None:
            return None
        # scenarios 键缺失（None，合法旧形态）分支同口径收口（code-review
        # item c0bc338cd2ea）：键缺失不等于豁免——「scenarios 缺失 + summary
        # 声明 failed/errors=0（total 缺失/为 0）」的截断/占位报告同样可经
        # _derive_status 的 summary 分支推出 verified、合成「全部场景通过」
        # 的假通过报告，与上方两个相邻变体同按 fail-closed 拒收：仅 total>0
        # 且显式声明 failed/errors 键（与列表分支同门槛）才采信。
        if _summary_usable(summary):
            return data
        return None
    return None


def _sum_verify_chain_tokens(project_root, spec_name):
    """从验证链 token 侧车求和本链（planner/judge）增量 token（add-cost-observability 2.2）。

    读取 ``.fenix/verify-progress/<spec>/tokens.json``，累加各 run 的 input/output。
    input 已含 cache_creation/cache_read（侧车写入时已计入）。文件缺失/不可解析返回 None。
    """
    if not project_root or not spec_name:
        return None
    path = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / "tokens.json"
    )
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    total_in = 0
    total_out = 0
    for r in runs:
        if not isinstance(r, dict):
            continue
        try:
            total_in += int(r.get("input_tokens", 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            total_out += int(r.get("output_tokens", 0) or 0)
        except (TypeError, ValueError):
            pass
    return {"input": total_in, "output": total_out}


# code-review 6c9af9ec3805：跨模块（pm_engine.verification.verdict_evidence 等）复用
# 统一走公开名，模块边界不依赖下划线私有符号；私有名保留给模块内既有调用点。
# 别名直引同一实现，签名与行为随本体，无任何包装差异。
sum_verify_chain_tokens = _sum_verify_chain_tokens


def _iter_run_result_candidates(project_root, spec_name):
    """按统一候选序逐个产出可采信的 run-result ``(path, data, shared)``。

    「采信谁就盯谁」契约的单点实现：``_load_run_result``（采信侧）与
    ``current_round_fingerprint``（盯侧）共同消费本迭代器，候选序、可用性
    判据与归属口径只此一份维护，不再靠注释约定两侧同步（该重复已有单侧
    漂移史：code-review 9e616773371c 与 ad0ebe488d64 均只修了单点后再次
    对齐，f0d377a32021 收口为共用 helper）。

    候选序与口径：
      - verify-progress 专属副本（shared=False）优先，主树共享文件
        （shared=True）回退；
      - 解析成功且为 JSON 对象才可用（code-review 9e616773371c）：专属副本
        在场但空 JSON/损坏时跳过、继续回退共享文件，指纹不得只盯在场文件的
        mtime，否则后续轮次仅共享文件更新（fast-track 全绿只写 run-result）
        时指纹不变，上一轮合成报告被误判本轮 present 放行；
      - 专属副本 status/bugs 均空 → 不可采信，同款跳过、回退共享文件；
      - 共享文件仅 spec 戳显式归属本 spec 才产出（严格口径，代价不对称的
        取舍见 ``_load_run_result`` docstring；code-review ad0ebe488d64）。
    """
    primary = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / ".fenix-run-result.json"
    )
    fallback = Path(project_root) / ".fenix" / ".fenix-run-result.json"
    for path, shared in ((primary, False), (fallback, True)):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if shared:
            # 无 spec 戳的共享文件不可归属本 spec（异常写入/其它 spec 残留），
            # 只有显式戳匹配才采信
            stamped = data.get("spec")
            if not (isinstance(stamped, str) and stamped == spec_name):
                continue
        elif not (data.get("status") or data.get("bugs")):
            continue
        yield path, data, shared


def _load_run_result(project_root, spec_name):
    """读取裁决 .fenix-run-result.json（verify-progress 优先，主树 .fenix/ 回退）。

    项目根为共享文件：仅采信 spec 戳**显式等于**当前 spec 的内容；无戳/缺戳
    视为不可归属（可能为其它 spec 残留或异常写入）一律忽略。

    口径差异说明（有意为之，勿单方面「对齐」）：dashboard/data/artifacts.py
    同名函数与 fastlane.has_dispute_signal 对无戳共享文件按「缺 spec 戳的旧
    格式文件仍采信」的宽松口径读取。本模块产出闸门放行依据的合成报告，误
    归属会把其它 spec 的结果渲染成本 spec 的验证结论并影响状态推进放行，故
    取严格口径；展示/信号探测侧误采信的代价仅是显示错或 fail-open，两侧代价
    不对称。排障时同一结果文件在两处「采信与否」结论不同属预期。

    候选序/可用性/归属判据单点在 ``_iter_run_result_candidates``，本函数返回
    首个可采信候选的数据（无可采信候选返回 None）。
    """
    for _path, data, _shared in _iter_run_result_candidates(project_root, spec_name):
        return data
    return None


def _load_degrade_context(project_root, spec_name):
    """读取降级上下文 .fenix/verify-progress/<spec>/degrade_context.json。

    add-planready-artifact-gate D3：pm_engine 阶段1 降级判定点落盘（reason/
    run_id/duration_seconds/cost_usd/degraded_at）；合成报告路径读取后注入
    降级标注（G3）。文件缺失/损坏 → 返回 None（零注入零渲染，正常报告不含
    该字段）。
    """
    path = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / "degrade_context.json"
    )
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("reason") and not data.get("run_id"):
        return None
    return data


def _persist_degrade_annotation(project_root, spec_name, annotation) -> None:
    """把降级标注注入 report.json 顶层并落盘（持久化，D3/D4）。

    降级合成报告必须随 report.json 持久化（非仅日志），后续读取报告（时间轴/
    报告页/CLI）能还原降级事实与代价。写入失败静默跳过（annotation 是纯观测量，
    不得阻断报告合成主流程）。

    读-改-写在伴生 ``.lock`` 的 fcntl 排他锁内完成（record_verdict_round 同款
    范式）：_atomic_write 只保证文件不撕裂，不保证读-改-写原子；验证引擎同窗
    重写 report.json（每轮刷新 timestamp 属常规路径）时，无锁读改写会以读到的
    旧底稿覆盖引擎新写的报告，丢掉新报告的场景明细/计数。锁文件不可用、或
    flock 本身抛 OSError（特殊文件系统不支持等）时降级为无锁读改写——
    annotation 是纯观测量，尽力而为不阻断合成主流程。
    """
    report_path = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / "report.json"
    )
    try:
        # 伴生锁文件（record_verdict_round 同款）：每次新开 fd 的 flock 在
        # 同进程跨 fd 亦互斥，单文件锁即覆盖跨进程与跨线程并发
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            lf = open(report_path.parent / f".{report_path.name}.lock", "w")
        except OSError:
            lf = None
        try:
            if lf is not None:
                try:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                except OSError:
                    # flock 本身不可用（特殊文件系统不支持等）：降级前先 close
                    # 原 fd 再置 None（只置 None 不 close 会让 fd 等 GC 才回收，
                    # record_verdict_round 对 code-review 002ddf629f96 同款处置）
                    lf.close()
                    lf = None
            data = {}
            if report_path.is_file():
                try:
                    loaded = json.loads(report_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    # 文件在场但不可读（权限抖动/读取窗口异常等暂态）：跳过本次
                    # 持久化，绝不用仅含标注的空底稿原子覆盖——那会把可能完整的
                    # 既有报告永久替换成空壳，时间轴/报告页从此拿不到场景明细。
                    # annotation 是纯观测量（见 docstring），丢弃不阻断合成主流程。
                    return
                if not isinstance(loaded, dict):
                    # 合法 JSON 但非对象（写坏形态）：同属「存在但不可用作报告
                    # 底稿」，同上跳过、保留原文件，不覆盖。
                    return
                data = loaded
            data["degrade_annotation"] = annotation
            # mkstemp 唯一临时文件原子写（_atomic_write）：进程中途崩溃不会留下
            # 截断的 report.json；固定 .tmp 名并发写会互相截断后 replace
            _atomic_write(report_path, json.dumps(data, ensure_ascii=False, indent=2))
        finally:
            if lf is not None:
                # LOCK_UN 失败不掩盖原始异常（close 即隐式释放 flock）
                try:
                    fcntl.flock(lf, fcntl.LOCK_UN)
                except OSError:
                    pass
                lf.close()
    except (OSError, TypeError, ValueError):
        pass


# ── 渲染 ─────────────────────────────────────────────────────────


def _derive_status(run_result, report) -> str:
    """从结构化数据推导终局判定：'verified' 或 'bug-found'。

    run_result.status 按白名单正向匹配：已知成功裁决（``verified``/
    ``bug-found``）原样返回；已知失败/未完成取值（``error``/``partial``，
    fast-track 结果文件 status 白名单 success/error/partial 中的非成功终态）
    判 bug-found（fail-closed 方向）。其余非空未知取值（如 implementer/
    planner 收工票据残留的 ``success``/``plan-ready``，或未来写手新增的
    timeout 等未收录词）同判 bug-found——与读侧 verdict status 白名单
    （``core/agent_runner/prompt_builder.PLANNER_RESULT_STATUS_WHITELIST``）
    同口径：语义错位/未收录取值若落到报告分支，会经「无法判定 → 默认
    verified」的宽松兜底为实际并非成功裁决的验证轮合成出 ✅ 通过报告，与
    结构化数据语义及模块 fail-closed 哲学相反。status 缺失/为空仍属「无
    状态信息」（``_load_run_result`` 允许仅携带 bugs 的合法结果文件），交由
    下方报告分支判定。
    """
    if run_result:
        status = run_result.get("status")
        if status in ("verified", "bug-found"):
            return status
        if status in ("error", "partial"):
            return "bug-found"
        # code-review 07a30ddd0bae：白名单外的非空未知取值 fail-closed，
        # 不再落报告分支经宽松兜底合成 verified 报告（取舍见 docstring）
        if status:
            return "bug-found"
    if isinstance(report, dict):
        summary = report.get("summary")
        if isinstance(summary, dict):
            try:
                if (int(summary.get("failed", 0) or 0) + int(summary.get("errors", 0) or 0)) > 0:
                    return "bug-found"
            except (TypeError, ValueError):
                pass
            else:
                # 显式声明过 failed/errors 键且值非 0 已被上分支拦截 → 判定有据
                if "failed" in summary or "errors" in summary:
                    return "verified"
        # summary 缺失/非 dict/不可解析/未声明失败键时退化为按场景计数兜底：
        # 存在非 pass/passed 场景即 bug-found（与 _resolve_scenarios 的场景级
        # 数据源回退同向）
        for sc in _resolve_scenarios(report, run_result) or []:
            if isinstance(sc, dict) and str(sc.get("status") or "") not in ("pass", "passed"):
                return "bug-found"
    return "verified"


def _summary_counts(report):
    """提取 (passed, failed, errors, total)；缺键/空值/不可转换的字段为 None。

    report/summary 为 truthy 非 dict（如非空列表）时按缺失处理置空 dict，与
    _derive_status 的 isinstance(summary, dict) 守卫同口径——``or {}`` 只回退
    falsy 值，拦不住 truthy 非 dict，随后 summary.get 会抛 AttributeError
    （code-review a6b5b1d045f9）。
    """
    summary = (report if isinstance(report, dict) else {}).get("summary")
    if not isinstance(summary, dict):
        summary = {}

    def _num(key):
        val = summary.get(key)
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    return _num("passed"), _num("failed"), _num("errors"), _num("total")


# ── 报告时效（陈旧报告识别）────────────────────────────────────────


def current_round_fingerprint(project_root, spec_name):
    """当前轮结构化数据的指纹（轮次身份）。无结构化数据时返回 None。

    联合指纹：report.json 成分 + run-result 成分，任一结构化数据更新即整枚
    指纹变化。report.json 的 ``timestamp`` 由验证引擎每轮重写，是轮次身份的
    第一来源；字段缺失时退化为文件 mtime。run-result mtime 同时纳入组成——
    某轮验证可能**只重写 .fenix-run-result.json 不重写 report.json**（全绿
    快道即只写 run-result，见 judge_gate._all_green_fast_path），指纹若只看
    report.json 会保持不变，上一轮残留报告被以 present 放行（2026-09-12
    事故同型）——不再单点依赖「引擎每轮重写 report.json」的跨模块契约。

    run-result 成分与 ``_load_run_result`` 消费同一候选迭代器
    ``_iter_run_result_candidates``（候选序/可用性/归属口径单点维护）：
    采信谁就盯谁——共享文件仅在 spec 戳显式归属本 spec 时才纳入指纹，非本
    spec 内容不参与本 spec 的轮次身份（否则其它 spec 每轮重写共享文件都翻转
    本 spec 指纹，触发无谓重合成）。全部成分皆不可得返回 None——此时无从判定
    新旧，闸门维持「既有报告不改动」的保守行为。
    """
    parts: list[str] = []
    report_path = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / "report.json"
    )
    report = _load_report_json(project_root, spec_name)
    if isinstance(report, dict):
        ts = report.get("timestamp")
        if isinstance(ts, str) and ts.strip():
            parts.append(f"report.json@{ts.strip()}")
        else:
            # code-review 62075248138d：读内容（_load_report_json）与取 mtime
            # 是两步 IO，文件在两步之间被引擎重写时，这里 stat 到的是新文件的
            # mtime。窗口极窄且偏差方向保守：timestamp 与 mtime 两成分经
            # if/else 互斥取用，不会拼成混合指纹；极端失配只会让稍后重算的
            # 指纹不同而多做一次合成（误判为上一轮残留），不产生错误放行。
            # 判已知良性，不引入同 fd fstat+read 的额外复杂度。
            try:
                parts.append(f"report.json@mtime{report_path.stat().st_mtime_ns}")
            except OSError:
                pass
    for run_result_path, _data, _shared in _iter_run_result_candidates(project_root, spec_name):
        try:
            parts.append(f"run-result@mtime{run_result_path.stat().st_mtime_ns}")
        except OSError:
            # stat 抖动（权限/窗口异常等）：跳过该候选、继续回退下一候选，
            # 与既有「逐候选 try/except OSError 后继续」行为一致
            continue
        break
    if not parts:
        return None
    return "+".join(parts)


def _report_fingerprint(content):
    """既有报告记录的合成源轮次指纹；Agent 手写/存量报告无标记时返回 None。"""
    m = _FINGERPRINT_RE.search(content or "")
    return m.group(1) if m else None


def _md_declared_verdict(content):
    """解析 md 自己声明的 (verdict, failed, errors)；解析不出为 None。

    与 ``core/dashboard/data.py`` 的 ``parse_verdict`` 同款语法：结论标题行
    「## 结论：…」+ 汇总表格行「| 失败 | N |」。Agent 自由叙述（无结论标题、
    无汇总表）→ 全部为 None，视作「不可判定」而非「矛盾」。
    """
    verdict = None
    m = _MD_CONCLUSION_RE.search(content or "")
    if m:
        head = m.group(1)
        # 顺序敏感：「未通过」含「通过」子串，必须先判不通
        if "未通过" in head or "❌" in head or "bug-found" in head:
            verdict = "bug-found"
        elif "通过" in head or "✅" in head or "verified" in head:
            verdict = "verified"
    counts = {}
    for label, raw in _MD_COUNT_RE.findall(content or ""):
        try:
            counts[label] = int(raw)
        except (TypeError, ValueError):
            continue
    return verdict, counts.get("失败"), counts.get("错误")


def _report_is_superseded(project_root, spec_name, content) -> bool:
    """既有报告是否为上一轮残留（须重新合成）。

    事故背景（2026-09-12 add-framework-self-evolution）：第 1 轮 bug-found 时
    闸门合成 ❌ 报告；打回后第 2 轮走「全绿快道」（跳过 judge、不产 md），闸门
    见文件已存在即放行 → spec 已 pushed 而报告仍是上一轮的 ❌。

    判据一（精确，框架合成报告）：报告携带的合成源轮次指纹 ≠ 当前轮指纹。
    判据二（兜底，存量 md 无指纹）：md 声明的裁决结论与当前结构化数据矛盾
    （状态不一致，或失败/错误计数不一致）。

    Agent 手写叙述、无结论行、或结论与本轮一致的报告一律维持原样——「Agent
    报告优先、不覆盖」的原策略不回归。
    """
    current = current_round_fingerprint(project_root, spec_name)
    declared_fp = _report_fingerprint(content)
    if current and declared_fp:
        return declared_fp != current

    run_result = _load_run_result(project_root, spec_name)
    report = _load_report_json(project_root, spec_name)
    if run_result is None and report is None:
        # 无结构化数据可比对：无法判残留，既有报告按 present 放行（有报告总
        # 比 fail-closed 阻断好；判 True 走重新合成也无数据可用、只会阻断）
        return False
    declared_verdict, declared_failed, declared_errors = _md_declared_verdict(content)
    if declared_verdict is None and declared_failed is None and declared_errors is None:
        return False  # 解析不出结论（Agent 自由叙述）→ 不判矛盾
    if declared_verdict is not None and declared_verdict != _derive_status(run_result, report):
        return True
    # 已知边界（item 7a55e645a08c）：下方计数兜底只读 report.json 顶层 summary；
    # fast-track 形态（report.json 缺失、场景明细在 .fenix-run-result.json 的
    # verification.scenarios）下 failed/errors 恒为 None，两条计数比对被跳过，
    # 仅剩上方 verdict 标题行比对生效。方向保守（不会误判残留、只可能漏判后
    # 维持 present），且 _load_run_result 的 status 比对通常已覆盖；若未来
    # fast-track 残留误放行出现，须在此对 _resolve_scenarios 的场景计数做同款
    # 比对（同步消费 run_result 侧计数），不能只扩 report.json 侧。
    _passed, failed, errors, _total = _summary_counts(report)
    if declared_failed is not None and failed is not None and declared_failed != failed:
        return True
    if declared_errors is not None and errors is not None and declared_errors != errors:
        return True
    return False


def _failed_assertion_count(scenario) -> str:
    """场景失败断言数「x/y」，无断言数据返回 '-'。"""
    ars = scenario.get("assertion_results")
    if not isinstance(ars, list) or not ars:
        return "-"
    failed = sum(1 for a in ars if isinstance(a, dict) and not a.get("pass", True))
    return f"{failed}/{len(ars)}"


def _render_evidence(evidence) -> list:
    """把 bug 证据渲染为 Markdown 行（dict/list/str 尽力展开）。"""
    lines = []
    if isinstance(evidence, dict):
        for key, val in evidence.items():
            if isinstance(val, (dict, list)):
                rendered = json.dumps(val, ensure_ascii=False)
            else:
                rendered = str(val)
            lines.append(f"  - {key}: {rendered}")
    elif isinstance(evidence, list):
        for item in evidence:
            rendered = (
                json.dumps(item, ensure_ascii=False)
                if isinstance(item, (dict, list))
                else str(item)
            )
            lines.append(f"  - {rendered}")
    elif evidence is not None:
        lines.append(f"  - {evidence}")
    return lines


def _render_bugs_section(bugs, scenario_evidence=None) -> list:
    """「真实产品 Bug」章节：description / root_cause / evidence 逐条渲染。

    scenario_evidence: {scenario_id: evidence_dict}（来自 report.json 增强后的
    结构化证据，add-verdict-evidence-taxonomy）；命中时优先引用该证据，
    不重复渲染 judge 运行结果的稀疏证据（spec Scenario: 「引用该证据而非重复渲染」）。
    """
    scenario_evidence = scenario_evidence or {}
    lines = ["", "## 真实产品 Bug", ""]
    for i, bug in enumerate(bugs, 1):
        if not isinstance(bug, dict):
            continue
        severity = bug.get("severity") or "unspecified"
        assertion = bug.get("assertion_type") or "-"
        lines.append(f"### BUG-{i:02d}（severity={severity}）· {assertion}")
        lines.append("")
        scenario_ids = bug.get("scenario_ids")
        if isinstance(scenario_ids, list) and scenario_ids:
            lines.append("- 关联场景：" + "、".join(str(s) for s in scenario_ids))
        description = bug.get("description")
        if description:
            lines.append(f"- 描述：{description}")
        root_cause = bug.get("root_cause")
        if root_cause:
            lines.append(f"- 根因：{root_cause}")
        # 优先引用 report.json 的场景结构化证据（引用而非重复渲染）
        referenced = False
        for sid in scenario_ids if isinstance(scenario_ids, list) else []:
            ev = scenario_evidence.get(sid)
            if isinstance(ev, dict):
                lines.append(f"- 证据（场景 {sid} 结构化证据，引用）：")
                lines.extend(_render_evidence(ev))
                referenced = True
                break
        if not referenced:
            ev_lines = _render_evidence(bug.get("evidence"))
            if ev_lines:
                lines.append("- 证据：")
                lines.extend(ev_lines)
        lines.append("")
    return lines


def _md_cell(v, max_len=None) -> str:
    """Markdown 表格单元格统一转义口径：竖线与换行转义（可选超长截断）。

    场景结果表与断言级豁免清单共用：status/classification 等列源自裁决
    自由文本，含竖线时会撑破 Markdown 表格列，故所有插值列同口径转义；
    换行（\\r\\n/\\r/\\n）折叠为空格，保证单元格永不跨行。
    max_len 仅承载豁免清单证据列的既有截断行为（>160 截为 157+"..."），
    其余列不引入新截断。
    """
    text = (
        str(v)
        .replace("\r\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("|", "\\|")
    )
    if max_len is not None and len(text) > max_len:
        # code-review ce2d416b701d：max_len <= 3 时 max_len-3 非正，负切片会
        # 从尾部删字符再追加省略号（结果仍可能超长且丢错位置）——短上限直接
        # 硬切，省略号无处安放即不追加
        if max_len <= 3:
            text = text[:max_len]
        else:
            text = text[: max_len - 3] + "..."
    return text


def _render_assertion_exempt_section(report) -> list:
    """「断言级豁免清单」小节（add-interaction-contract-and-per-assert-triage 2.3）。

    从 report.json 的 assertion_triage 汇总：逐条列出被豁免的失败断言（场景、
    断言内容、归类、证据、豁免理由），供人工快速复核豁免是否吞掉了真实缺陷。
    历史报告无 assertion_triage 字段时小节缺省（design D4，向后兼容）。
    """
    from core.verdict_check import exempted_assertions, triage_entries

    if not isinstance(report, dict):
        return []
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return []
    # 旧报告：全部场景均无 assertion_triage → 小节缺省（不渲染空壳）
    if not any(triage_entries(sc) for sc in scenarios if isinstance(sc, dict)):
        return []

    rows = exempted_assertions(report)
    # 场景 id → 同窗并行上下文在位性（evo-add-verify-scenario-resource-mutex
    # 2.2）：豁免条目缺该上下文 → 归类列落「证据不全」标记。历史报告（字段
    # 上线前）全部条目都会带标记——旧豁免确无并行证据，如实呈现而非粉饰。
    ctx_missing: dict[str, bool] = {}
    for sc in scenarios:
        if isinstance(sc, dict):
            sid = str(sc.get("scenario_id") or sc.get("id") or "-")
            ctx_missing[sid] = not _has_parallel_context(sc)
    lines = ["", "## 断言级豁免清单", ""]
    lines.append(
        "以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核"
        "豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。"
    )
    lines.append("")
    if not rows:
        lines.append("无非 product-bug 的被豁免失败断言。")
        lines.append("")
        return lines
    lines.append("| 场景 | 断言 | 归类 | 豁免理由 | 证据 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in rows:
        assertion = _md_cell(r["assertion"])
        evidence = _md_cell(r["evidence"], max_len=160)
        reason = _md_cell(r["reason"])
        scenario_id = _md_cell(r["scenario_id"])
        classification = _md_cell(r["classification"])
        if ctx_missing.get(str(r["scenario_id"]), True):
            classification += "（证据不全）"
        lines.append(
            f"| {scenario_id} | {assertion} | {classification} "
            f"| {reason} | {evidence} |"
        )
    lines.append("")
    return lines


def _has_parallel_context(sc) -> bool:
    """场景结果是否附引擎侧同窗并行上下文（evo-add-verify-scenario-resource-mutex 2.2）。

    引擎对每个执行的场景附 ``parallel_context``（batch/peers/observed_parallel）；
    字段上线前的历史报告、以及被依赖失败传播跳过的场景（未执行、无同窗概念）
    均缺该字段——豁免条目引用场景时据此落「证据不全」标记。
    """
    if not isinstance(sc, dict):
        return False
    ctx = sc.get("parallel_context")
    if not isinstance(ctx, dict):
        return False
    return (
        isinstance(ctx.get("peers"), list)
        and type(ctx.get("observed_parallel")) is int
    )


def _render_scenarios_table(report) -> list:
    scenarios = (report or {}).get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return []
    lines = ["", "## 场景结果", ""]
    lines.append("| 场景 | 描述 | 状态 | 失败断言 | 分类 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = _md_cell(sc.get("scenario_id") or sc.get("id") or "-")
        desc = _md_cell(sc.get("description") or "-")
        status = _md_cell(sc.get("status") or "-")
        # 采纳处强制重写的场景标注「已修正」(add-verdict-evidence-taxonomy D3)
        if sc.get("status_corrected"):
            status += "（已修正）"
        classification = _md_cell(sc.get("classification") or "-")
        # 豁免条目（flaky/env 分类）缺同窗并行上下文 → 落「证据不全」标记
        # （evo-add-verify-scenario-resource-mutex 2.2 确定性实现路径：提示词
        # 层要求豁免附并行清单，报告合成层对缺证据者可复核标记）
        if classification in ("flaky", "env") and not _has_parallel_context(sc):
            classification += "（证据不全）"
        lines.append(
            f"| {sid} | {desc} | {status} | {_failed_assertion_count(sc)} | {classification} |"
        )
    lines.append("")
    return lines


def render_verification_report(
    spec_name,
    run_result,
    report,
    now=None,
    project_root=None,
    degrade_annotation=None,
    source_fingerprint=None,
) -> str:
    """把结构化数据渲染为人读报告 Markdown。

    纯函数：不做 IO、不写文件，便于测试与下游复用。project_root 用于读取验证链
    token 侧车（add-cost-observability 2.2），缺失时跳过「本链增量 token」行。

    add-planready-artifact-gate D4：degrade_annotation 为可选降级标注 dict
    （reason/run_id/duration_seconds/cost_usd/degraded_at，源自 degrade_context.json），
    存在时在报告头部追加「⚠️ 降级说明」引用块；缺省 None 时零渲染（正常报告
    不含该标注，与无降级时逐字节一致）。

    source_fingerprint：本轮结构化数据的轮次指纹（``current_round_fingerprint``），
    非空时写入头部「合成源轮次指纹：」标记，供闸门判定报告是否属上一轮。
    """
    # code-review 9aba8609cddc：run_result 为 truthy 非 dict（list/str 等）时
    # 统一归一为 None，与 _resolve_scenarios 的 isinstance 守卫同口径——本函数
    # 是公开复用的纯函数，下方 _derive_status / .get("bugs") / .get("summary")
    # 均对 run_result 直接 .get，非 dict truthy 值会抛 AttributeError。
    if not isinstance(run_result, dict):
        run_result = None
    status = _derive_status(run_result, report)
    passed, failed, errors, total = _summary_counts(report)
    bugs = []
    if run_result:
        raw_bugs = run_result.get("bugs")
        if isinstance(raw_bugs, list):
            bugs = [b for b in raw_bugs if isinstance(b, dict)]

    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"# 验证报告：{spec_name}", ""]
    lines.append(
        f"> ⚠️ 本报告由框架于 {ts} 自动合成"
        f"（裁决 Agent 未写报告，已由框架合成），"
        f"内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。"
    )
    if isinstance(source_fingerprint, str) and source_fingerprint.strip():
        lines.append(
            f"> 报告时效标记（判定本报告是否属上一轮）："
            f"{_FINGERPRINT_MARKER}{source_fingerprint.strip()}"
        )
    lines.append("")

    # ── 降级说明引用块（add-planready-artifact-gate D4，G3 留痕）──
    # 新验证流程 planner 阶段失败降级 legacy verifier 时，合成报告须标注降级
    # 原因与被降级轮次代价（不再静默合成）。
    if isinstance(degrade_annotation, dict):
        reason = str(degrade_annotation.get("reason") or "未知原因")
        run_id = str(degrade_annotation.get("run_id") or "未知 run")
        duration_s = degrade_annotation.get("duration_seconds")
        cost_usd = degrade_annotation.get("cost_usd")
        if isinstance(duration_s, (int, float)):
            minutes = f"{float(duration_s) / 60:.1f}min"
        else:
            minutes = "时长未知"
        cost_part = ""
        if cost_usd is not None:
            try:
                cost_part = f"/${float(cost_usd):.2f}"
            except (TypeError, ValueError):
                cost_part = ""
        lines.append(
            f"> ⚠️ 降级说明：本报告由框架合成（新验证流程 planner 阶段失败："
            f"{reason}；被降级轮次 {run_id} 烧 {minutes}{cost_part}）"
        )
        lines.append("")

    # ── 结论标题（内联状态，parse_verdict 的 status 来源）──
    if status == "bug-found":
        head = "❌ 未通过（Bug Found）"
        if bugs:
            count_note = f"{len(bugs)} 个真实产品 Bug"
        else:
            # code-review ecfc5b50f951：列表缺失时「0 个真实产品 Bug」与
            # 「未通过」标题并读自相矛盾，改中性表述（下方说明块指向明细）
            count_note = "结构化 bug 列表缺失（见下方失败场景明细）"
    else:
        head = "✅ 通过（verified）"
        # count_note 须与状态详情行（detail_parts）一致：豁免失败（flaky/test-defect
        # 豁免场景合法保留失败计数而终局 verified）时再写「全部场景通过」会自相矛盾
        if (failed or 0) + (errors or 0) > 0:
            count_note = "其余失败场景已豁免（见分类列）"
        else:
            count_note = "全部场景通过"
    lines.append(f"## 结论：{head}")
    lines.append("")

    # ── 状态详情行（parse_verdict 的 status_detail 来源）──
    detail_parts = []
    if passed is not None and total is not None:
        detail_parts.append(f"{passed}/{total} 场景通过")
    if failed is not None:
        detail_parts.append(f"{failed} 失败")
    if errors is not None:
        detail_parts.append(f"{errors} 错误")
    detail = (
        status + (" — " + "，".join(detail_parts) if detail_parts else "") + f"（{count_note}）"
    )
    lines.append(f"**状态：{detail}**")
    lines.append("")

    # ── 结论正文（parse_verdict 的 conclusion 来源）──
    judge_summary = (run_result or {}).get("summary")
    if isinstance(judge_summary, str) and judge_summary.strip():
        lines.append(judge_summary.strip())
        lines.append("")

    # ── 汇总表格（parse_verdict 的 summary 来源）──
    lines.append("| 指标 | 数量 |")
    lines.append("| --- | --- |")
    # add-cost-observability（2.2）：本链增量 token 行（从 verify-progress 侧车求和）
    chain_tokens = _sum_verify_chain_tokens(project_root, spec_name)
    for label, val in (
        ("通过", passed if passed is not None else "N/A"),
        ("失败", failed if failed is not None else "N/A"),
        ("错误", errors if errors is not None else "N/A"),
        ("产品 Bug", len(bugs)),
        (
            "本链增量 Token（输入）",
            f"{chain_tokens['input'] / 1_000_000:.2f}M" if chain_tokens else "N/A",
        ),
        (
            "本链增量 Token（输出）",
            f"{chain_tokens['output'] / 1_000_000:.2f}M" if chain_tokens else "N/A",
        ),
    ):
        lines.append(f"| {label} | {val} |")
    lines.append("")

    # ── 真实产品 Bug（bug-found 时必备章节）──
    if status == "bug-found":
        if bugs:
            # 从 report.json 摘取每个场景的结构化证据，供 bug 章节引用（不重复渲染）
            scenario_evidence = {}
            for sc in (report or {}).get("scenarios", []) or []:
                if not isinstance(sc, dict):
                    continue
                sid = str(sc.get("scenario_id") or sc.get("id") or "")
                ev = sc.get("evidence")
                if sid and isinstance(ev, dict):
                    scenario_evidence[sid] = ev
            lines.extend(_render_bugs_section(bugs, scenario_evidence))
        else:
            lines.append("## 真实产品 Bug")
            lines.append("")
            lines.append(
                "> 判定为 bug-found 但结果文件未携带结构化 bug 列表，"
                "以下为 report.json 中的失败场景明细。"
            )
            lines.append("")

    # ── 场景明细 ──
    lines.extend(_render_scenarios_table(report))

    # ── 断言级豁免清单（add-interaction-contract-and-per-assert-triage 2.3）──
    lines.extend(_render_assertion_exempt_section(report))
    return "\n".join(lines).rstrip() + "\n"


# ── 合成与闸门 ────────────────────────────────────────────────────


def _resolve_scenarios(report, run_result):
    """解析场景明细数据源（fix-verify-report-fasttrack-scenarios）。

    优先级：
      1. report.json 顶层 `scenarios` 非空列表 → 使用之（full 模式 tester 路径不变）
      2. 顶层缺失/为空/非法 → 回退 `.fenix-run-result.json` 的
         `verification.scenarios`（fast-track schema，`core/fast_track_result.py`）
      3. 两者皆不可得 → 返回 None（场景表留空，不阻断合成）

    数据读取在入口合成层完成、归一为场景列表返回；渲染层仍收纯参数（`.get` 链
    已按缺省容错，scene 无 classification/assertion_results 等字段时原样显示）。
    """
    report_scenarios = (report or {}).get("scenarios")
    if isinstance(report_scenarios, list) and report_scenarios:
        return report_scenarios
    verification = run_result.get("verification") if isinstance(run_result, dict) else None
    if isinstance(verification, dict):
        fast_scenarios = verification.get("scenarios")
        if isinstance(fast_scenarios, list) and fast_scenarios:
            return fast_scenarios
    return None


def synthesize_verification_report(project_root, spec_name, now=None) -> dict:
    """从结构化数据合成 verification-report.md 并写入磁盘。

    返回 {"ok": True, "path": <str>}；结构化数据缺失/不可解析时返回
    {"ok": False, "error": <文案>}，且不写任何文件（不产出空报告）。

    add-planready-artifact-gate D3：合成路径读取 degrade_context.json，存在时
    degrade_annotation 注入渲染 **并持久化到 report.json 顶层**（后续读取报告
    ——时间轴/报告页/CLI——能还原降级事实与代价，G3）。无 degrade_context.json
    时零注入零渲染（正常报告不含该字段）。
    """
    report = _load_report_json(project_root, spec_name)
    run_result = _load_run_result(project_root, spec_name)
    if report is None and run_result is None:
        return {
            "ok": False,
            "error": (
                f"验证报告缺失且无法合成：'{spec_name}' 的 report.json 与 "
                f".fenix-run-result.json 均缺失或不可解析"
            ),
        }

    # fast-track 场景数据源回退：report.json 顶层 scenarios 缺失/为空/非法时，
    # 归一 .fenix-run-result.json 的 verification.scenarios 注入 report 后传入
    # 渲染层（渲染函数保持纯函数无 IO、签名不变）。
    resolved_scenarios = _resolve_scenarios(report, run_result)
    if resolved_scenarios is not None:
        report = dict(report or {})
        report["scenarios"] = resolved_scenarios

    degrade_annotation = _load_degrade_context(project_root, spec_name)
    if degrade_annotation is not None:
        # 持久化到 report.json 顶层（design D3：随报告结构持久化，非仅日志）
        _persist_degrade_annotation(project_root, spec_name, degrade_annotation)
        if report is not None:
            report = dict(report)
        else:
            report = {}
        report["degrade_annotation"] = degrade_annotation

    content = render_verification_report(
        spec_name,
        run_result,
        report,
        now=now,
        project_root=project_root,
        degrade_annotation=degrade_annotation,
        source_fingerprint=current_round_fingerprint(project_root, spec_name),
    )
    out_path = Path(project_root) / "spec" / "changes" / spec_name / "verification-report.md"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp 唯一临时文件原子写（_atomic_write）：进程中途崩溃不会留下截断
        # 的 md；固定 .tmp 名并发合成会互相截断——截断残留的指纹仍等于本轮
        # 指纹，会被闸门以 present 放行，违背「放行时报告必然完整在盘」的本职
        _atomic_write(out_path, content)
    except OSError as e:
        return {"ok": False, "error": f"验证报告写入失败: {e}"}
    return {"ok": True, "path": str(out_path)}


def _append_alert(
    project_root,
    spec_name,
    signal_type,
    severity,
    description,
    evidence,
    recommended_action=None,
    logger=None,
) -> None:
    """落一条 human-escalation-alerts 告警（节流：同 spec 同类信号冷却期内不重复）。

    recommended_action 缺省沿用「Agent 未写报告」的劣化提示——只适配报告缺失
    路径；报告在场但不可读/上一轮残留重合成失败等调用点须按各自故障形态传入
    （根因是读取/编码/时效问题，非 Agent 未写报告），避免把人工排障引向
    「催 Agent 重写报告」的错误方向。
    """
    try:
        from .admin_store import AdminStore, ESCALATION

        store = AdminStore(project_root, logger)
        if store.latest_signal(spec_name, signal_type, _ALERT_COOLDOWN_MINUTES) is not None:
            return
        if recommended_action is None:
            recommended_action = (
                "留意验证裁决 Agent 未遵守 prompt 步骤 6（写 verification-report.md）"
                "的劣化信号；合成报告内容以结构化 JSON 为准，无叙述性分析"
            )
        store.append(
            {
                "kind": ESCALATION,
                "signal_type": signal_type,
                "spec": spec_name,
                "severity": severity,
                "description": description,
                "evidence": evidence,
                "recommended_action": recommended_action,
            }
        )
    except Exception as e:  # 告警失败不阻断主流程（闸门结论已定）
        if logger is not None:
            logger.warning(
                "verify_report",
                f"验证报告闸门告警写入失败 '{spec_name}': {e}",
            )


def _commit_verification_report(project_root, spec_name, logger=None) -> None:
    """报告落盘即入库（evo-add-verification-report-commit-on-write）。

    对 ``spec/changes/<spec>/verification-report.md`` 做 pathspec 精确的
    git add + commit（add 与 commit 同 pathspec，--only 语义），使「落盘」
    与「入库」同步，不再依赖归档兜底；subprocess 惯例照 core/archive_commit.py。

    第二消费方（evo-add-push-closeout-verification-report-commit）：done→pushed
    收口（engine.approve_push，_push_lock 内、归档收口之前）经函数内延迟导入
    复用本函数，对本 spec 报告做同款 pathspec 精确入库，闭合「报告落盘晚于
    实现 merge、早于 pushed」的入库窗口；幂等与失败语义同下（push 场景不加
    前缀），任何失败仅 WARNING、不阻断 pushed 落定。

    - pathspec 严格单文件：禁用 ``git add -A -- spec`` 整目录（会卷入其它
      spec 在途草案，engine.py 同款警示），也不吞索引中无关 staged 内容；
    - 失败语义：非 git 仓库（被管项目可能无 git）静默跳过；其余失败
      （git 不可用、index.lock 争用等）只落 WARNING（附 stderr 摘要），
      绝不影响验证主流程与报告写盘结果；
    - 幂等：报告已入库且内容无变化时静默跳过（探测式：add 后与 HEAD 逐字
      节比对，不解析 git 各版本漂移的 nothing-to-commit 文案）——闸门在同
      一 spec 多轮验证中反复进入（pipeline/legacy 四调用点），重复放行不
      得反复落 WARNING 制造告警噪声。
    """
    proot = Path(project_root)
    rel_path = f"spec/changes/{spec_name}/verification-report.md"

    def _warn(msg: str) -> None:
        if logger is not None:
            logger.warning("verify_report", f"验证报告入库失败 '{spec_name}': {msg}")

    try:
        # 非 git 仓库：入库机制不适用，静默跳过（每轮验证都进闸门，
        # 对无 git 的被管项目逐轮刷 WARNING 纯属噪声）
        # 显式 UTF-8：text=True 缺省按 locale strict 解码，stdout/stderr 含
        # 非 ASCII 字节（如 index.lock 争用信息引用中文路径、非 C locale 的
        # 本地化文案）时抛 UnicodeDecodeError（ValueError 子类），逃逸下方
        # except、击穿「任何失败仅 WARNING」契约（同包 repair_site.py 同款
        # 惯例；code-review b7a5e058f945）。下方全部 git 子进程同此。
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_REPORT_PROBE_TIMEOUT,
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return
        add = subprocess.run(
            ["git", "add", "--", rel_path],
            cwd=str(proot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_REPORT_ADD_TIMEOUT,
        )
        if add.returncode != 0:
            _warn(f"git add 失败: {add.stderr.strip() or f'exit {add.returncode}'}")
            return
        # 幂等主判定：add 后暂存内容与 HEAD 一致（报告已入库且内容无变化）
        # 即静默跳过——用探测式判定而非解析 nothing-to-commit 文案：git 各
        # 版本文案漂移（"nothing to commit, working tree clean" 与
        # "nothing added to commit but untracked files present" 并存），
        # 单一文案匹配会在重复放行时误落 WARNING。
        unchanged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "HEAD", "--", rel_path],
            cwd=str(proot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_REPORT_PROBE_TIMEOUT,
        )
        if unchanged.returncode == 0:
            return
        commit = subprocess.run(
            [
                "git", "commit",
                "-m", f"[fenix] {spec_name}: verification-report 入库",
                "--", rel_path,
            ],
            cwd=str(proot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_REPORT_COMMIT_TIMEOUT,
        )
        if commit.returncode != 0:
            output = (commit.stdout + "\n" + commit.stderr).strip()
            if (
                "nothing to commit" in output
                or "nothing added to commit" in output
            ):
                return  # 探测到提交之间他人已入库同内容（并发窗口）：静默跳过
            # code-review 1ae6ca68e2b9：add 已成功而 commit 失败（index.lock
            # 争用/hook 拒绝等）时回滚本次 add——spec/changes 的 staged 残留
            # 会转嫁成后续 merge-back/归档流水线的「内容冲突/DRY 拒绝」阻塞。
            # reset 失败只追加告警，不掩盖原 commit 失败日志。
            reset = subprocess.run(
                ["git", "reset", "-q", "--", rel_path],
                cwd=str(proot),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_REPORT_PROBE_TIMEOUT,
            )
            _warn(f"git commit 失败: {output or f'exit {commit.returncode}'}")
            if reset.returncode != 0:
                _warn(
                    f"git reset 回滚暂存失败（报告仍以 staged 态残留索引）: "
                    f"{reset.stderr.strip() or f'exit {reset.returncode}'}"
                )
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as e:
        _warn(f"git 入库异常: {e}")


# code-review 14bc75c819c6：跨模块（pm_engine.verification.scenario_gate 等）复用
# 本提交器统一走公开名，模块边界不依赖下划线私有符号；私有名保留给模块内
# 既有调用点。别名直引同一实现，签名与行为随本体，无任何包装差异。
commit_verification_report = _commit_verification_report


def ensure_verification_report(project_root, spec_name, logger=None, pre_commit=None) -> dict:
    """验证报告产物闸门：裁决放行前调用。

    返回 {"ok": True, "action": "present"|"synthesized"|"resynthesized"} 表示放行；
    返回 {"ok": False, "error": <文案>} 表示 MUST 阻止状态推进（fail-closed）。

    放行时（含 present——Agent 已自写报告、框架未落盘）报告文件同步入库
    （``_commit_verification_report``，pathspec 精确）；git 失败只落 WARNING，
    不改变放行结论。本动作只做 git 入库，不触碰 spec_has_content 内容认可
    判定（verification-report.md 保持不计入名单）。

    pre_commit（evo-verification-report-closeout-single-commit）：可选无参
    callable，三个放行出口（present/resynthesized/synthesized）均在
    ``_commit_verification_report`` 之前执行——供闸门消费方（report_gate）
    把「本轮场景集变更」小节渲染合并进同一次提交，采纳流程内报告相关提交
    由两次收敛至多一次。回调异常仅落 WARNING、不阻断放行与后续提交（对齐
    「git 失败仅 WARNING」失败语义）；默认 None 时行为与无回调逐字等价
    （push 收口等未传回调的调用方零影响）。

    action=resynthesized：既有报告属上一轮残留（``_report_is_superseded``），
    已用本轮结构化数据重新合成覆盖。既有报告在场但不可读（OSError/
    UnicodeDecodeError）或可读但为空白（0 字节/纯空白，如 agent 写报告
    截断后崩溃）时同样走重新合成——残缺报告不得以 present 放行。
    """
    out_path = Path(project_root) / "spec" / "changes" / spec_name / "verification-report.md"

    def _run_pre_commit() -> None:
        # pre-commit 挂点：仅回调异常兜底（渲染/入库自身的降级由回调内建），
        # 放行结论只由报告闸门数据决定，挂点绝不反向阻断。
        if pre_commit is None:
            return
        try:
            pre_commit()
        except Exception as e:
            if logger is not None:
                logger.warning(
                    "verify_report",
                    f"验证报告 pre-commit 回调失败 '{spec_name}': {e}",
                )

    unreadable = False
    if out_path.exists():
        try:
            existing = out_path.read_text(encoding="utf-8")
            if not existing.strip():
                # 报告在场但为空白（0 字节/纯空白，如 agent 写报告工具截断后
                # 崩溃）：空串解析不出任何结论会被 _report_is_superseded 判
                # 「非残留」而 fail-open，与不可读同款改走重新合成兜底。
                unreadable = True
        except (OSError, UnicodeDecodeError):
            # 报告在场但读不出（权限/编码损坏）：空串解析不出任何结论会被
            # _report_is_superseded 判「非残留」而 fail-open，故改走重新合成，
            # 合成失败再 fail-closed 告警。
            existing = ""
            unreadable = True
        if not unreadable and not _report_is_superseded(project_root, spec_name, existing):
            # Agent 已写报告且与本轮裁决一致：原样保留，不覆盖、不改 mtime；
            # 文件既已在盘，落盘即入库（present 是验证 Agent 自写报告的主路径）
            _run_pre_commit()
            _commit_verification_report(project_root, spec_name, logger)
            return {"ok": True, "action": "present"}
        result = synthesize_verification_report(project_root, spec_name)
        if result.get("ok"):
            if logger is not None:
                if unreadable:
                    logger.warning(
                        "verify_report",
                        f"验证报告闸门：'{spec_name}' 既有报告不可读或为空白"
                        f"（权限/编码损坏/截断），已重新合成覆盖",
                    )
                else:
                    logger.warning(
                        "verify_report",
                        f"验证报告闸门：'{spec_name}' 报告属上一轮残留"
                        f"（本轮裁决已变更），已重新合成覆盖",
                    )
            _run_pre_commit()
            _commit_verification_report(project_root, spec_name, logger)
            return {"ok": True, "action": "resynthesized"}
        error = result.get("error") or "验证报告缺失且无法合成"
        if unreadable:
            # 与缺失路径同一 fail-closed 承诺：阻断推进并发升级告警
            _append_alert(
                project_root,
                spec_name,
                SIGNAL_MISSING,
                "major",
                (
                    f"'{spec_name}' 验证报告在场但不可读或为空白且无法合成——"
                    "验证裁决放行被阻断，等待人工裁决"
                ),
                error,
                recommended_action=(
                    "报告文件在场但不可读/空白（权限、编码损坏或写入截断）且框架"
                    "重新合成失败：排查报告文件完好性与结构化数据"
                    "（.fenix-run-result.json）可用性——读取/编码/暂态问题，"
                    "非 Agent 未写报告"
                ),
                logger=logger,
            )
        else:
            # 残留报告重合成失败同样 fail-closed：与缺失/不可读路径告警对齐，
            # 人工可见性一致（不阻断则只会放行上一轮陈旧结论）
            _append_alert(
                project_root,
                spec_name,
                SIGNAL_MISSING,
                "major",
                (
                    f"'{spec_name}' 验证报告属上一轮残留且重新合成失败——"
                    "验证裁决放行被阻断，等待人工裁决"
                ),
                error,
                recommended_action=(
                    "报告属上一轮残留、框架用本轮结构化数据重新合成失败：排查"
                    "报告文件完好性与结构化数据（.fenix-run-result.json）可用性"
                    "——本轮数据是否就绪/可读（读取/编码/时效问题），"
                    "非 Agent 未写报告"
                ),
                logger=logger,
            )
        return {"ok": False, "error": error}

    result = synthesize_verification_report(project_root, spec_name)
    if result.get("ok"):
        # 2026-08-29 用户决策：合成兜底静默化——只记框架日志，不发人工升级告警
        if logger is not None:
            logger.warning(
                "verify_report",
                f"验证报告闸门：'{spec_name}' 报告缺失，已由框架合成",
            )
        _run_pre_commit()
        _commit_verification_report(project_root, spec_name, logger)
        return {"ok": True, "action": "synthesized"}

    error = result.get("error") or "验证报告缺失且无法合成"
    _append_alert(
        project_root,
        spec_name,
        SIGNAL_MISSING,
        "major",
        f"'{spec_name}' 验证报告缺失且无法合成——验证裁决放行被阻断，等待人工裁决",
        error,
        logger=logger,
    )
    if logger is not None:
        logger.error("verify_report", f"验证报告闸门阻断 '{spec_name}': {error}")
    return {"ok": False, "error": error}


# ── verdict 稳定性缓存（judge-rerun-stability R1）────────────────────────
# 持久化最近两轮 verdict（status + 失败场景 id 集 + spec 戳 + report.json mtime），
# 供 judge 派发前置守卫判定：连续两轮 verdict 一致时复用上次结果，不重派 judge。
# 文件名为 verdict_stability.json，**不得复用 verdict_cache.json**（后者已被
# core/verdict_check.py 的场景级指纹缓存占用，同路径写入会互相覆盖并破坏
# prompt_builder 的场景指纹注入）。
#
# judge_rerun_count（单 spec judge 重跑计数）为 STATE.md 字段（_judge_rerun_count，
# 与 _verify_fail_rounds 正交），不在本文件重复记账——本文件只持久化 verdict 轮次。
#
# schema:
# {
#   "stamp": "<sha256(spec content)[:16]>",
#   "report_mtime_ns": <int>,
#   "rounds": [
#     {"status": "...", "failed_ids": [...], "at": "..."},
#     ...
#   ],
#   "updated_at": "..."
# }

VERDICT_STABILITY_FILENAME = "verdict_stability.json"
# 连续两轮一致的最小轮数要求（<=此值即视为可复用）
_STABILITY_MIN_ROUNDS = 2


def _verdict_stability_path(project_root, spec_name) -> Path:
    """verdict_stability.json 路径（verify-progress/<spec>/）。"""
    return (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / VERDICT_STABILITY_FILENAME
    )


def compute_spec_stamp(project_root, spec_name) -> str | None:
    """spec 戳：spec 内容与场景集内容的 sha256 前 16 位（同 scenario_fingerprint 风格）。

    组成：
      - ``spec/changes/<spec>/specs/**/spec.md`` 全部内容（按路径排序，若有多个
        capability spec 文件则拼接后一次性哈希）；
      - ``.fenix/verify-progress/<spec>/scenarios.json`` 内容（场景集冻结文件，
        _apply_scenario_freeze 每轮重写）。

    两路全部不可读返回 None（调用方按「无法判定」保守不复用）；任一路可用
    即按可得内容哈希（部分可得）。场景集变更或 spec.md 修改即改变 spec 戳
    → 缓存失效重新验证。
    """
    import hashlib as _hashlib

    parts: list[bytes] = []

    # 1) spec.md 全部内容（多 capability 按路径排序保证确定性）
    changes_dir = Path(project_root) / "spec" / "changes" / spec_name
    spec_files = sorted(changes_dir.glob("specs/**/spec.md"))
    for p in spec_files:
        try:
            parts.append(p.read_bytes())
        except OSError:
            pass

    # 2) scenarios.json 内容
    scenarios_path = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / "scenarios.json"
    )
    try:
        parts.append(scenarios_path.read_bytes())
    except OSError:
        pass

    if not parts:
        return None
    digest = _hashlib.sha256(b"\x00".join(parts)).hexdigest()[:16]
    return digest


def report_mtime_ns(project_root, spec_name) -> int | None:
    """report.json mtime 纳秒；缺失返回 None（用于稳定性缓存判据）。"""
    report_path = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / "report.json"
    )
    try:
        return report_path.stat().st_mtime_ns
    except OSError:
        return None


def verdict_failed_ids(report) -> list:
    """从 report.json 提取失败场景 id 集（status 非 pass/passed），排序去重。

    返回排序后的列表（方便跨轮一致比较）；report 为 None 或无场景时返回 []。
    缺 scenario_id/id 的失败场景以序号占位（``__index_<i>``）计入失败集——
    静默跳过会让无 id 失败场景在 failed_ids 集合上不可见，is_verdict_stable
    误判稳定而复用裁决（防御性：引擎产物正常都带 id，位置或数量一变集合
    即不同 → 保守不复用）。
    """
    scenarios = (report or {}).get("scenarios") or []
    ids: set = set()
    for i, sc in enumerate(scenarios):
        if not isinstance(sc, dict):
            continue
        st = str(sc.get("status") or "")
        if st not in ("pass", "passed"):
            sid = sc.get("scenario_id") or sc.get("id")
            # 真值判空：空串 id 同样以序号占位，多个缺 id 失败场景不坍缩
            ids.add(str(sid) if sid else f"__index_{i}")
    return sorted(ids)


def read_verdict_stability(project_root, spec_name) -> dict | None:
    """读取 verdict_stability.json；缺失/损坏返回 None（fail-open）。

    返回顶层 dict（含 stamp / report_mtime_ns / rounds / updated_at）。
    """
    p = _verdict_stability_path(project_root, spec_name)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_verdict_stability(project_root, spec_name, data) -> None:
    """原子写 verdict_stability.json（失败静默：缓存缺失只导致下轮重裁）。"""
    p = _verdict_stability_path(project_root, spec_name)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp 唯一临时文件原子写（_atomic_write）：固定 .tmp 名并发写会
        # 互相截断后 replace 出截断缓存
        _atomic_write(p, json.dumps(data, ensure_ascii=False, indent=1, default=str))
    except OSError:
        pass


def record_verdict_round(
    project_root,
    spec_name,
    status,
    failed_ids,
    stamp: str | None = None,
    report_mtime: int | None = None,
) -> dict:
    """追加一轮裁决到 verdict_stability.json（保留最近两轮）；返回更新后数据。

    stamp / report_mtime 为 None 时自动从当前状态推导。
    首轮写入 rounds=[round]；第二轮起保留最近两轮用于一致比较。

    读-改-写在单次跨进程排他锁内完成（serving_registry / admin_store 的
    fcntl 伴生 ``.lock`` 范式）：同 spec 双活跃 run（manual-intervention 与
    blocked_stuck 各一）几乎同时采纳裁决时，两步无锁读改写会让后写者覆盖
    前写者丢一轮，稳定性判据退化（多跑一次 judge）。_atomic_write 只保证
    文件不撕裂，不保证读-改-写原子。锁文件不可用、或 open 成功而 flock 本身
    抛 OSError（特殊文件系统不支持等）时，同样降级为无锁读改写——缓存属
    尽力而为（同 write_verdict_stability 静默语义），不阻断裁决。
    """
    if stamp is None:
        stamp = compute_spec_stamp(project_root, spec_name)
    if report_mtime is None:
        report_mtime = report_mtime_ns(project_root, spec_name)

    now = datetime.now(timezone.utc).isoformat()
    current_round = {
        "status": status or "unknown",
        "failed_ids": list(failed_ids or []),
        "at": now,
    }

    # 伴生锁文件（serving_registry._lock 同款）：每次新开 fd 的 flock 在
    # 同进程跨 fd 亦互斥，单文件锁即覆盖跨进程与跨线程并发
    stability_path = _verdict_stability_path(project_root, spec_name)
    try:
        stability_path.parent.mkdir(parents=True, exist_ok=True)
        lf = open(stability_path.parent / f".{stability_path.name}.lock", "w")
    except OSError:
        lf = None
    try:
        if lf is not None:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX)
            except OSError:
                # flock 本身不可用（特殊文件系统不支持等）同样降级为无锁读
                # 改写（docstring 契约：缓存尽力而为，不阻断裁决采纳流程），
                # 不向上传播中断调用方。降级前先 close 原 fd 再置 None：只置
                # None 不 close 会让 fd 等 GC 才回收，此路径每次调用泄漏一个
                # （长期运行 daemon 在特殊文件系统上累积，code-review
                # 002ddf629f96）；finally 的 ``lf is not None`` 守卫保证不会
                # 对已关闭对象重复 close/LOCK_UN。
                lf.close()
                lf = None
        data = read_verdict_stability(project_root, spec_name) or {}
        rounds = data.get("rounds") or []
        if not isinstance(rounds, list):
            rounds = []

        rounds.append(current_round)
        # 保留最近两轮（_STABILITY_MIN_ROUNDS），更早的轮次出清
        if len(rounds) > _STABILITY_MIN_ROUNDS:
            rounds = rounds[-_STABILITY_MIN_ROUNDS:]

        # 刷新 stamp 前先留存上一记录轮的 spec 戳（item e1db54f39158）：单槽
        # 每轮覆盖会抹掉 round1 的出处——spec 在两轮之间变更时，round2 记录
        # 把 stamp 刷新为最新值，is_verdict_stable 的顶层比对因此通过、两轮
        # 比较横跨 spec 变更仍判稳定复用，违背 compute_spec_stamp「spec 变更
        # 即缓存失效重新验证」契约。prev_stamp + stamp + 当前戳三方一致才复用
        # （is_verdict_stable 侧检查）。
        data["prev_stamp"] = data.get("stamp")
        data["stamp"] = stamp
        data["report_mtime_ns"] = report_mtime
        data["rounds"] = rounds
        data["updated_at"] = now

        write_verdict_stability(project_root, spec_name, data)
        return data
    finally:
        if lf is not None:
            # LOCK_UN 失败不掩盖原始异常（close 即隐式释放 flock）
            try:
                fcntl.flock(lf, fcntl.LOCK_UN)
            except OSError:
                pass
            lf.close()


def is_verdict_stable(project_root, spec_name) -> bool:
    """复用判据：spec 戳未变（当前 + 上一记录轮）&& report.json mtime 未变
    && 最近两轮 verdict 一致。

    无缓存/单轮/两轮不一致/任一关键输入不可得 → False（保守不复用）。
    符合复用条件时 judge 派发前置守卫可跳过 run_planner。
    """
    data = read_verdict_stability(project_root, spec_name)
    if data is None:
        return False

    # 两轮以上一致性检查
    rounds = data.get("rounds") or []
    if len(rounds) < _STABILITY_MIN_ROUNDS:
        return False

    last_two = rounds[-_STABILITY_MIN_ROUNDS:]
    prev = last_two[0]
    curr = last_two[1]
    if not isinstance(prev, dict) or not isinstance(curr, dict):
        return False

    # verdict 一致性（status + failed_ids）
    if prev.get("status") != curr.get("status"):
        return False
    prev_failed = prev.get("failed_ids")
    curr_failed = curr.get("failed_ids")
    # 脏值容错：failed_ids 损坏成非列表，或元素类型不可互比（混合类型如
    # [1, "a"]，sorted 在 Python 3 下抛 TypeError）时，与缓存损坏同判 →
    # 保守不复用（False），不让脏值沿 judge_gate 调用链炸掉派发前置守卫
    # （code-review a5774bb9ee03）
    if not isinstance(prev_failed, list) or not isinstance(curr_failed, list):
        return False
    try:
        if sorted(prev_failed) != sorted(curr_failed):
            return False
    except TypeError:
        return False

    # spec 戳未变
    current_stamp = compute_spec_stamp(project_root, spec_name)
    if current_stamp is None:
        return False
    if current_stamp != data.get("stamp"):
        return False
    # 上一记录轮的 spec 戳（item e1db54f39158）也须与当前一致：仅比顶层 stamp
    # 时，spec 在两轮之间变更会让 round2 记录把 stamp 刷新为最新值，两轮比较
    # 横跨 spec 变更仍判稳定复用。prev_stamp 缺席（本字段上线前的存量缓存，
    # 两轮出处已无从考证）沿用原顶层判据不否决——任一新记录轮即回填该字段
    # 自愈，此后两轮出处均可验证。
    prev_stamp = data.get("prev_stamp")
    if prev_stamp is not None and prev_stamp != current_stamp:
        return False

    # report.json mtime 未变
    current_mtime = report_mtime_ns(project_root, spec_name)
    if current_mtime is None:
        return False
    if current_mtime != data.get("report_mtime_ns"):
        return False

    return True
