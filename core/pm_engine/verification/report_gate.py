"""core.pm_engine.verification.report_gate — 裁决读取与验证报告闸门（refactor-verification-module D2）。

从 VerificationPipeline 摘出的裁决读取 / 验证报告产物闸门 / 完成度门禁方法。
纯结构搬移，零行为变化（spec「拆分零行为变化」）。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。

模块级函数首参为 `pipeline`（VerificationPipeline 实例）—— `_context.logger` /
`_context.project_root` / `_context.state_machine` 等门面依赖经实例访问，实例
属性打桩不被绕过（D2b 规则 2：VerificationPipeline 内部调用点 MUST 保持
`self.<方法名>` 形式，本模块内在兄弟函数间也一律经 `pipeline.<方法名>` 或直接
模块级调用）。
"""

import json
import re
from pathlib import Path

# 裁决 status 白名单单源在 core.agent_runner.prompt_builder：verifier 裁决与
# planner 裁决共用同一状态集，PLANNER 前缀系历史命名，verifier 增删 status
# 亦改彼处（常量定义处有声明），本模块不另立词表。
from core.agent_runner.prompt_builder import PLANNER_RESULT_STATUS_WHITELIST


class VerdictReadResult:
    """verdict 结果文件读取三态结果（fix-verdict-read-failclosed D4）。

    - ok=True  → status 为白名单内合法裁决（verified/bug-found/plan-ready/
      scenario-repaired）。
    - ok=False → 结果文件**不可读**（missing/parse/io-error/unknown-status/
      foreign-stamp），reason 归因、detail 附解析错误原文。不可读**绝不**等价
      于 verified——历史 add-verify-contract-autodraft 事故：summary 裸换行致
      非法 JSON → 读侧按 None 处理 → else 分支 → verified → done → auto-push。
    """

    __slots__ = ("status", "reason", "detail")

    def __init__(self, status=None, reason: str = "", detail: str = ""):
        self.status = status
        self.reason = reason
        self.detail = detail

    @property
    def ok(self) -> bool:
        return self.status is not None

    @classmethod
    def success(cls, status: str) -> "VerdictReadResult":
        return cls(status=status)

    @classmethod
    def failure(cls, reason: str, detail: str) -> "VerdictReadResult":
        return cls(status=None, reason=reason, detail=detail)

    def __repr__(self):
        if self.ok:
            return f"<VerdictReadResult ok status={self.status}>"
        return f"<VerdictReadResult unreadable reason={self.reason} " f"detail={self.detail!r}>"


def _read_verify_report(pipeline, spec_name: str) -> dict:
    """读取 verify-progress/<spec>/report.json（尽力解析，失败返回空 dict）。

    哨兵差异（fix-code-review）：本函数失败返回 {}（空 dict 哨兵），而同一
    report.json 经 core.verdict_check.load_report 读取时失败返回 None（None
    哨兵）——同一产物两套读取器并存、判空口径不同，新增消费点须按各自哨兵
    取用（`if not report` 对 {} / None 双兼容，`is None` / `== {}` 判定互不
    兼容）。本函数消费方：infra_classify._scenario_classification_distribution
    / _failed_scenario_ids（经 pipeline 门面）；load_report 消费方：
    escalation._env_whitewash_gate 等。
    """
    path = pipeline._context.project_root / ".fenix" / "verify-progress" / spec_name / "report.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        # 哨兵语义不变（仍返回空 dict），但失败留 WARNING 痕，与同文件其余
        # 读取器（_read_verifier_result/_read_shared_result）的可观测口径
        # 一致——瞬时读错误时消费方拿到空分布/空失败清单仍有排障线索
        # （code-review item 248a9afad6af）。
        pipeline._context.logger.warning(
            "pm_engine",
            f"Failed to read verify report (best-effort): path={path}, err={e}",
        )
        return {}


def _ensure_verification_report(pipeline, spec_name: str) -> str | None:
    """验证报告产物闸门（add-verify-report-gate）。

    在验证裁决采纳处（verified / bug-found 即将推进）调用：校验
    spec/changes/<spec>/verification-report.md 存在；缺失时由框架从
    结构化数据确定性合成（不重跑验证、不覆盖既有文件）并发人工升级告警；
    结构化数据也不可用时 fail-closed。

    返回 None 表示放行（报告已存在或合成成功）；返回非空字符串为阻断原因，
    调用方须阻止状态推进并把原因写入 error 字段。

    evo-verification-report-closeout-single-commit：注入场景段渲染回调——
    闸门放行的单次提交同时含报告本体与「本轮场景集变更」小节，采纳流程内
    报告相关提交由两次收敛至多一次；pipeline._apply_verified / _apply_bug_found
    与 legacy 两个采纳调用点共用本函数，注入一处即全覆盖。末尾渲染点
    （pipeline 采纳尾段）保留为兜底，报告已含小节标题时按幂等判定零成本跳过。
    """
    from core.verify_report import ensure_verification_report

    def _render_scenario_section_pre_commit() -> None:
        # 函数内延迟导入为本包防循环导入惯例（本模块禁顶层 import 包内兄弟
        # 模块）；渲染函数自身已兜渲染/入库异常（仅 WARNING、不阻断），此处
        # 不再额外包装——闸门放行结论只由报告闸门数据决定。
        from core.pm_engine.verification.scenario_gate import (
            _render_scenario_change_section_to_report,
        )

        _render_scenario_change_section_to_report(pipeline, spec_name)

    try:
        result = ensure_verification_report(
            pipeline._context.project_root,
            spec_name,
            logger=pipeline._context.logger,
            pre_commit=_render_scenario_section_pre_commit,
        )
    except Exception as e:
        # 合成器自身异常等同数据不可用：fail-closed，不凭空放行
        return f"验证报告缺失且无法合成：闸门异常 {e}"
    if result.get("ok"):
        return None
    return result.get("error") or "验证报告缺失且无法合成"


def _check_verification_gate(pipeline, spec_name: str) -> str | None:
    """验证完成度放行闸门（verification-completion-gate）。

    返回 None 表示门禁通过（可推进到 done）；返回非空字符串表示未完成原因，
    此时应阻断 verified→done，把原因写入 error 字段供人工裁决。

    判定规则：
    - 无进度文件（.fenix/verify-progress/<spec>.json 缺失）→ 放行
      （验证流程未启动，维持原推进路径，不影响存量 spec）。
    - 进度文件存在但解析失败 / 字段缺失 / done < total → 阻断，
      返回「验证未完成：done/total（+最近 current）」。
    - done == total → 放行。
    """
    # fix-deferred-findings CYC-1：parse_verify_progress 已迁中性模块
    # core.signals（pm_engine 侧不再反向 import dashboard.data）
    from core.signals import parse_verify_progress

    vp = parse_verify_progress(pipeline._context.project_root, spec_name)
    if not vp.get("exists"):
        return None
    total = vp.get("total") or 0
    done = vp.get("done") or 0
    if vp.get("error") == "corrupt" or total <= 0 or done < total:
        current = vp.get("current") or ""
        tail = f"（当前：{current}）" if current else ""
        return f"验证未完成：{done}/{total}{tail}"
    if done > total:
        # 进度文件计数异常（场景集缩小后计数残留、半新半旧的写交叉）——
        # 异常计数本身说明进度文件不可信，不与正常完成同走静默放行路径：
        # WARNING 留痕 + 按未完成阻断（code-review item f146475ac4fa）。
        pipeline._context.logger.warning(
            "pm_engine",
            f"验证进度计数异常 '{spec_name}': done({done}) > total({total})，"
            f"进度文件不可信——按未完成阻断",
        )
        return f"验证进度计数异常：done({done}) > total({total})"
    return None


def _verifier_stamp_gate(data, spec_name: str, require_verifier_role: bool) -> tuple:
    """role/spec 戳校验唯一实现（evo-verifier-result-single-source R1）。

    fix-code-review DRY：``_verifier_result_is_stale`` 与
    ``_read_shared_result`` 原各自内联同一条规则（role 必须为 verifier、
    spec 戳为非空字符串时须与当前 spec 一致），收敛到本助手后规则演进
    （如新增戳字段/放宽容忍）只改此处。返回 (ok, reason)：ok=False 时
    reason ∈ foreign-role（role 缺失或 ≠ verifier，仅
    require_verifier_role=True 时参与判定）/ foreign-stamp（spec 戳不符）；
    失败处置差异（判陈旧 True vs 返回 failure）由调用侧各自表达。
    """
    role = data.get("role") if isinstance(data, dict) else None
    if require_verifier_role and role != "verifier":
        return False, "foreign-role"
    stamped = data.get("spec") if isinstance(data, dict) else None
    if isinstance(stamped, str) and stamped and stamped != spec_name:
        return False, "foreign-stamp"
    return True, ""


def _verifier_result_is_stale(pipeline, result, result_path: Path, spec_name: str) -> bool:
    """verifier 结果文件是否不可信（陈旧重放 / 异 spec 残留 / 缺失）。

    判据（任一命中即陈旧）：
    - role 闸门仅作用于主树共享回退文件：文件含 role 字段且 ≠ verifier，
      或 role 缺失（旧格式遗留 / implementer 残留）→ 来源不明一律不采信
      （evo-verifier-result-single-source R1：消除 run_id fail-open——旧行为
      在 run_id 不匹配 ``-\\d{10,}-a\\d+$`` 时直接返回 False 不判陈旧，导致
      implementer 残留 status=success 仍被采信判 blocked）。per-spec primary
      是 verifier/judge 的新式写入落点（``_read_verdict`` 对 primary 直接
      采信、不设 role 门），agent 直写的 primary 常缺 role 戳（judge_gate
      快道 D3 同款教训）——role 门套到 primary 会把本轮 verifier 现写的
      合法裁决判成 stale 触发永久重派（2026-09-28
      evo-fix-codefix-rollup-archive-read 死循环实证）；primary 的归属仍由
      spec 戳 + mtime + status 白名单三重护栏兜底（implementer 残留
      status=success 落 unknown-status → blocked，fail-closed 不变）；
    - run_id 内嵌 epoch 早于文件 mtime 之前 5 秒以上 → 本轮验证器
      未曾写回；
    - 文件缺失却宣称成功 → 判定来源不明；
    - 文件 spec 戳与当前 spec 不符 → 其它 spec 的残留。
    role/spec 戳先行校验，不依赖 run_id 可解析（向后兼容）。
    """
    if not result_path.exists():
        return True
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    # UnicodeDecodeError（非 UTF-8 字节/半截二进制）与 JSON 语法错同属内容
    # 损坏：不可读一律判陈旧（fail-closed），与 pipeline.py 读取点口径对齐。
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return True
    if not isinstance(data, dict):
        return True
    # ── role/spec 戳先行（evo-verifier-result-single-source R1）──
    # 消除 run_id fail-open：旧行为在 run_id 不匹配 -\d{10,}-a\d+$
    # 时直接 return False 跳过所有后续校验，implementer 残留 status=success
    # 被错误采信。新版先查 role 与 spec 戳（不依赖 run_id），role≠verifier
    # 或 role 缺失一律返回 True（不采信）。规则唯一实现在
    # _verifier_stamp_gate（fix-code-review DRY），陈旧处置在调用侧表达。
    # role 闸门作用域：仅主树共享回退文件要求 role=verifier（R1 原意针对
    # 「主树共享文件 role≠verifier/缺 role 一律不采信」）；primary 豁免
    # role 门（归属由 spec 戳 + mtime + status 白名单兜底，见函数 docstring）。
    _primary, _shared = _verify_progress_result_paths(pipeline, spec_name)
    try:
        require_role = result_path.resolve() == _shared.resolve()
    except OSError:
        # resolve 失败（如父目录被并发删除）→ 无法确认路径归属时按更严的
        # 共享文件口径要求 role=verifier（fail-closed，code-review item
        # c82fa3056ecc）：宽松豁免会让 role 门在异常路径整体失效，与 R1
        # 「共享文件 role≠verifier/缺 role 一律不采信」方向相反。
        require_role = True
    ok, _reason = _verifier_stamp_gate(data, spec_name, require_verifier_role=require_role)
    if not ok:
        return True
    raw_run_id = getattr(result, "run_id", "") or ""
    try:
        m = re.search(r"-(\d{10,})-a\d+$", raw_run_id)
        run_start = int(m.group(1)) if m else None
    except (TypeError, ValueError):
        run_start = None
    if run_start is None:
        # run_id 无法解析（格式漂移/非字符串）：mtime 陈旧护栏整体退化为
        # 直通（不判陈旧）。维持既有放行行为不变（向后兼容），但记 WARNING
        # 留痕——避免护栏无声失效无告警，格式漂移时可观测。
        pipeline._context.logger.warning(
            "pm_engine",
            f"Verifier result run_id unparsable, mtime stale guard degraded "
            f"to pass-through: path={result_path}, run_id='{raw_run_id}'",
        )
        return False
    try:
        if result_path.stat().st_mtime < run_start - 5:
            return True
    except OSError:
        return True
    return False


def _read_verifier_result(
    pipeline, result_path: Path, data=None, role_label: str = "Verifier"
) -> VerdictReadResult:
    """读取 verifier 写入的 .fenix-run-result.json，返回结构化三态结果。

    fix-verdict-read-failclosed（fail-closed 语义反转）：
    结果文件缺失 / 非法 JSON / IO 异常 / status 白名单外一律返回 ok=False 的
    不可读结果（reason ∈ missing / parse / io-error / unknown-status），
    **绝不**返回 None 表示
    「视为 verified」——裁决读不出来 = 按通过放行是历史事故根因
    （add-verify-contract-autodraft：裸换行非法 JSON → None → else 分支
    → verified → done → auto-push）。不可读的处置（重试/blocked）由调用方
    决定，本方法只负责如实归因。

    ok=True 时的 status 取值（词表出处 =
    core.agent_runner.prompt_builder.PLANNER_RESULT_STATUS_WHITELIST，
    PLANNER 前缀系历史命名，verifier 增删 status 亦改彼处）：
    - "verified" 表示全部通过；
    - "bug-found" 表示验证发现 Bug；
    - "plan-ready" 表示 Planner 已生成场景；
    - "scenario-repaired" 表示 judge 原地修复了场景文件（judge-scenario-repair）。

    调用方已完成读取及 role/spec 戳校验时可经 `data` 直传解析结果，本函数
    跳过二次 read_text（共享文件两次读取之间可能被其它 spec 覆写，绕过
    戳校验被误采信）。

    `role_label`：missing 日志的 agent 角色标注（fix-code-review）。非
    verifier 读取路径（如 `_read_planner_result` 的 planner-plan 结果兜底）
    复用本读取器时传入自身角色，避免缺失日志固定措辞「Verifier result
    file not found」误导排障方向（实际是 planner-plan run 未产出结果文件）。
    """
    if data is None:
        if not result_path.exists():
            pipeline._context.logger.warning(
                "pm_engine",
                f"{role_label} result file not found: {result_path}",
            )
            return VerdictReadResult.failure("missing", f"{result_path}")
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # UnicodeDecodeError（非 UTF-8 字节）属产物内容损坏而非 IO 失败：
            # 归 parse 分池（与 pipeline.py 读取点捕获口径对齐），不可读仍
            # fail-closed 返回 ok=False，绝不放行。
            pipeline._context.logger.warning(
                "pm_engine",
                f"Failed to read {role_label} result (fail-closed): {e}",
            )
            return VerdictReadResult.failure("parse", f"{e}")
        except OSError as e:
            # IO 失败（权限/设备错误等）≠ 产物格式损坏：独立 reason=io-error，
            # 与 json.JSONDecodeError 的 parse 分池，下游按 reason 排障不误读为
            # 格式损坏（调用方统一按不可读处置，不受新 reason 影响）。
            pipeline._context.logger.warning(
                "pm_engine",
                f"Failed to read {role_label} result (fail-closed): {e}",
            )
            return VerdictReadResult.failure("io-error", f"{e}")
    if not isinstance(data, dict):
        pipeline._context.logger.warning(
            "pm_engine",
            f"Unknown verifier result structure (fail-closed): {result_path}",
        )
        return VerdictReadResult.failure("parse", f"顶层非对象: {result_path}")
    status = data.get("status", "")
    if status not in PLANNER_RESULT_STATUS_WHITELIST:
        # fail-closed：白名单外 status（如 implementer 共享文件残留的
        # success/error）不得被当成 verified 放行（历史日志：
        # "Unknown verifier status: 'success', treating as verified"）。
        pipeline._context.logger.warning(
            "pm_engine",
            f"Unknown {role_label} status: '{status}' (fail-closed, not treating " "as verified)",
        )
        return VerdictReadResult.failure("unknown-status", f"status='{status}'")
    bugs = data.get("bugs", [])
    bug_count = len(bugs) if isinstance(bugs, list) else 0
    pipeline._context.logger.info(
        "pm_engine",
        f"Verifier result: status={status}, bugs={bug_count}",
    )
    return VerdictReadResult.success(status)


def _verify_progress_result_paths(pipeline, spec_name: str) -> tuple:
    """verifier 结果文件路径解析：per-spec primary 优先 + 主树共享 fallback。

    fix-deferred-findings 整洁类（零行为变化）：_read_planner_result /
    _read_verdict / legacy._run_legacy_verification 三处重复的
    「verify-progress/<spec>/.fenix-run-result.json → 共享文件」解析
    收敛到本助手。
    """
    primary = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / ".fenix-run-result.json"
    )
    fallback = pipeline._context.project_root / ".fenix" / ".fenix-run-result.json"
    return primary, fallback


# 公开别名（跨模块消费走公开名，不 import 私有符号；同 scenario_gate.atomic_write_text
# 先例，code-review item 7e0a1ea1daf5）
verify_progress_result_paths = _verify_progress_result_paths


def _read_shared_result(
    pipeline,
    path: Path,
    spec_name: str,
    require_verifier_role: bool,
    role_label: str = "Verifier",
) -> VerdictReadResult:
    """主树共享回退文件的统一读取（fix-code-review DRY）。

    收敛 `_read_planner_result` / `_read_verdict` 对同一共享回退路径重复的
    「read_text → json.loads → spec 戳不符记 WARNING 返回 foreign-stamp →
    委托 `_read_verifier_result`」骨架；role 校验差异以 require_verifier_role
    布尔参数表达，戳规则唯一实现在 `_verifier_stamp_gate`（fix-code-review
    DRY），后续护栏规则变更（如新增戳字段）只改该助手，本函数只表达失败
    处置。

    两入口历史行为逐字保留（勿合并归一）：
    - require_verifier_role=True（_read_verdict）：data 非对象直接返回
      failure("parse", "<path>: 顶层非对象")（不记日志）；role≠verifier
      记 WARNING 返回 foreign-role；foreign-stamp WARNING 用 shared 措辞。
    - require_verifier_role=False（_read_planner_result）：无 role 校验，
      非对象交由委托的 `_read_verifier_result` 按 fail-closed 归因 parse；
      foreign-stamp WARNING 沿用 stale 措辞。

    `role_label`：透传给委托的 `_read_verifier_result` 的 agent 角色标注，
    使 missing/parse/unknown-status 日志按调用车道归因（fix-code-review）；
    缺省 Verifier 保持 `_read_verdict` 既有行为不变。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # UnicodeDecodeError（非 UTF-8 字节）属产物内容损坏而非 IO 失败：归
        # parse 分池（与 pipeline.py 读取点捕获口径对齐），仍 fail-closed。
        return VerdictReadResult.failure("parse", f"{path}: {e}")
    except OSError as e:
        # IO 失败（权限/设备错误等）≠ 产物格式损坏：独立 reason=io-error，与
        # _read_verifier_result 主路径的分池口径对齐（code-review item
        # 6b02308f9192）——共享回退路径上的权限/设备错误不再被误读为格式
        # 损坏；下游按不可读 fail-closed 处置不变，仅 reason 文本分池。
        return VerdictReadResult.failure("io-error", f"{path}: {e}")
    if require_verifier_role and not isinstance(data, dict):
        return VerdictReadResult.failure("parse", f"{path}: 顶层非对象")
    # ── role/spec 戳校验唯一实现在 _verifier_stamp_gate（evo-verifier-result-
    # single-source R1，fix-code-review DRY）：主树共享文件只认 role=verifier
    # 的 legacy verifier 写入；role 缺失视为旧格式遗留、role≠verifier 视为
    # 其它 agent 残留（如 implementer 的 status=success），一律不作为验证
    # 裁决。本函数只表达失败处置（WARNING 措辞 + failure 归因）。
    ok, reason = _verifier_stamp_gate(data, spec_name, require_verifier_role)
    if not ok:
        stamped = data.get("spec") if isinstance(data, dict) else None
        if reason == "foreign-role":
            role = data.get("role")
            pipeline._context.logger.warning(
                "pm_engine",
                f"Ignoring shared result file {path}: role={role!r} != "
                f"'verifier'（implementer 残留/旧格式遗留，不作为验证裁决）",
            )
            return VerdictReadResult.failure("foreign-role", f"{path}: role={role!r}")
        stamp_log_label = "shared result file" if require_verifier_role else "stale result file"
        pipeline._context.logger.warning(
            "pm_engine",
            f"Ignoring {stamp_log_label} {path}: " f"spec='{stamped}' != '{spec_name}'",
        )
        return VerdictReadResult.failure("foreign-stamp", f"{path}: spec='{stamped}'")
    # 单次读取贯穿戳校验与采信（复用首次解析的 data，消除两次读取之间
    # 文件被其它 spec 覆写、绕过 spec 戳比对按白名单采信的 TOCTOU 窗口）。
    return _read_verifier_result(pipeline, path, data=data, role_label=role_label)


def _read_planner_result(pipeline, spec_name: str) -> VerdictReadResult:
    """读取 Planner 写入的结果文件，返回结构化三态结果（fail-closed）。

    优先读 verify-progress/<spec>/.fenix-run-result.json（Planner prompt 中
    指定的确定性产物路径），回退主树 .fenix/.fenix-run-result.json（兼容旧行为：
    planner 把结果写到 worktree 根、由 _execute_agent 复制到主树的情况）。

    背景：主树 .fenix/.fenix-run-result.json 是共享文件，implementer 成功时也会
    写入（status=success/error）。planner 若把 plan-ready/verified 写到别处，
    pm_engine 误读主树共享文件会看到 implementer 残留状态（不在
    verified/bug-found/plan-ready 白名单），误判「Planner 未生成有效场景」，
    进而降级旧版 verifier 导致验证反复失败（admin 处置根因）。

    fix-verdict-read-failclosed：不可读（含 fallback spec-stamp 拦截的
    foreign 残留）一律返回 ok=False，绝不以 None 等价 verified。
    """
    primary, fallback = _verify_progress_result_paths(pipeline, spec_name)
    if primary.exists():
        # planner 车道日志按 Planner 归因（fix-code-review）：missing/parse/
        # unknown-status 勿沿用读取器默认的 Verifier 措辞误导排障方向。
        return _read_verifier_result(pipeline, primary, role_label="Planner")
    # 共享结果文件护栏：主树共享文件携带的 spec 与当前 spec 不符时视为残留忽略
    # （与 _read_implementer_result 相同语义），避免误读其它 spec 的
    # implementer 残留状态。
    if fallback.exists():
        return _read_shared_result(
            pipeline, fallback, spec_name, require_verifier_role=False, role_label="Planner"
        )
    # 兜底缺失（primary/fallback 均无）：missing 日志按 planner 语境标注
    # （fix-code-review），勿沿用读取器默认的 Verifier 措辞误导排障方向。
    return _read_verifier_result(pipeline, fallback, role_label="Planner")


def _read_verdict(pipeline, spec_name: str) -> VerdictReadResult:
    """统一裁决读取入口（evo-verifier-result-single-source R1）。

    裁决读取仅以 verify-progress/<spec>/.fenix-run-result.json 为单一来源；
    主树共享 .fenix/.fenix-run-result.json 仅作兼容回退，且回退必须先过
    role/spec 戳校验（再交由调用方的陈旧护栏/状态机判据处置）。

    - 优先 verify-progress/<spec>/.fenix-run-result.json（per-spec 隔离的
      确定性产物路径，judge/verifier 新式写入落点，直接采信）；
    - 缺失时回退主树共享文件——但仅当 role=verifier（legacy verifier 的
      唯一采信角色）且 spec 戳匹配才继续读取；role≠verifier 或缺 role 的
      共享文件一律不采信（implementer 残留 status=success / 旧格式遗留），
      返回 failure("foreign-role")。该 role 校验**不依赖 run_id 可解析**，
      修复 _verifier_result_is_stale 的 run_id fail-open：旧实现在 run_id
      不匹配 ``-\\d{10,}-a\\d+$`` 时直接返回 False 不判陈旧，导致
      implementer 残留 status=success 仍落入 blocked 分支（add-web-ui
      误判链，两次复发）；
    - 仍无结果文件则返回 failure("missing")（unreadable 语义）。

    不可读（missing/parse/unknown-status/foreign-role/foreign-stamp）一律
    返回 ok=False 的 VerdictReadResult，**绝不**以 None 等价放行（fail-closed）。
    """
    primary, shared = _verify_progress_result_paths(pipeline, spec_name)
    if primary.exists():
        return _read_verifier_result(pipeline, primary)

    if not shared.exists():
        return VerdictReadResult.failure("missing", f"{shared}")
    return _read_shared_result(pipeline, shared, spec_name, require_verifier_role=True)
