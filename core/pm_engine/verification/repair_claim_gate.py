"""修复申报指纹门（judge-repair-claim-gate / evo-add-repair-claim-fingerprint-gate）。

三块职责（design D1-D3）：

1. **派单侧（随单附指纹）**：bug-found 派修复（fastlane 轻量修复 / fix SPEC
   派生与原地打回）时，把被修场景失败指纹（场景 id + 失败签名 hash，读裁决面
   既有指纹口径 ``scenario_fingerprint``，不新造指纹体系）持久化到 STATE
   （``_repair_dispatch_fingerprint``）并注入两路派发上下文；无基线置 null
   不阻断派发。

2. **受理侧（指纹门）**：product 类修复申报受理点（fix SPEC 完成消费点
   ``engine._on_spec_done`` fix-* 分支、fastlane 子集重验消费点
   ``fastlane._fastlane_reverify_and_converge``）前置比对被修场景新鲜侧指纹
   与派单指纹。新鲜侧指纹源优先级（design D1）：①实现者申报内探针标注（主，
   ``.fenix-run-result.json`` ``verification.repair_probe``）→ ②盘面
   post-fix 新鲜轮指纹（fastlane 子集重验 / fix SPEC 自验产出，仅当受理时点
   确有新鲜轮）→ ③两者皆缺按「缺探针标注」拒收。MUST NOT 以受理时点
   verdict_cache 缓存条目直接作新鲜侧——受理时点重验回注未发生，缓存仍为
   派单同轮数据，以其比对恒等、必致无条件拒收死锁（save_verdict_cache 每轮
   采纳后整体重写）。本模块全程不读 verdict_cache。

3. **拒收分支**：复用 judge-repair-scenario-writeback-gate 已验证接线形态
   （error 留痕含「失败指纹未变化」与双方指纹值、``_record_repair_claim
   (rejected=True)``、不重入执行、不穿透调用方守卫），拒收信息经既有重派
   上下文回传下轮。指纹已变化、场景已转 pass 或无派单基线时照常受理。

既有 test-defect 场景修复通道三处 ``_record_repair_claim`` 调用点
（pipeline._handle_scenario_repaired）不在本门比对范围、行为零变化。
"""

import json
import time

# 派单指纹 STATE 字段（bug-found 派发写点持久化、受理点消费基线）。
# 值为 JSON 串（显式 json.dumps 落盘、显式 json.loads 回读，不依赖 STATE
# 解析层的类型往返）：{"fps": {sid: fp}, "at": <epoch>, "run": <judge run_id>}。
REPAIR_DISPATCH_FINGERPRINT_FIELD = "_repair_dispatch_fingerprint"

# 实现者申报约定字段（design D3）：.fenix-run-result.json
# ``verification.repair_probe`` = {"scenario_id", "fingerprint",
# "matches_dispatch"}。字段缺失 = 「缺探针标注」，受理门按指纹门同语义拒收。
REPAIR_PROBE_FIELD = "repair_probe"

# 受理记账指纹留痕 STATE 字段（观测审计，_record_repair_claim 写点维护；
# 仅在受理点显式传入指纹时写，缺省不写、与既有调用点行为零变化）。
JUDGE_REPAIR_LAST_DISPATCH_FP_FIELD = "_judge_repair_last_dispatch_fp"
JUDGE_REPAIR_LAST_FRESH_FP_FIELD = "_judge_repair_last_fresh_fp"

# 门裁决枚举
VERDICT_ACCEPT = "accept"
VERDICT_REJECT_UNCHANGED = "reject-unchanged"
VERDICT_REJECT_MISSING_PROBE = "reject-missing-probe"


class CollectedFingerprints(dict):
    """collect_failed_fingerprints 返回表：dict 键值语义与裸 dict 完全一致
    （键值面仍仅含非 PASS 场景失败指纹），外挂 ``covered_sids`` 覆盖面标记，
    供 coverage="report" 门区分「缺席＝已转 pass」与「缺席＝未被执行」。

    ``covered_sids``（frozenset，可为空）：裁决报告内实际在场且结论可判定的
    场景 id 面（scope 内）——PASS 场景与取到指纹的非 PASS 场景均在面内；
    报告缺席或指纹计算 fail-open 落空的场景不在面内。受理门凭「sid 在覆盖
    面、不在失败指纹表」确认该场景已转 pass（collect 键值面只收非 PASS，
    单看缺席无法与「未执行/被跳过」区分，item 787dd73fd615）；裸 dict
    （探针路径/旧调用方直构表）getattr 取不到该属性 → 门按覆盖面不可知
    保守处理。
    """

    def __init__(self, *args, covered_sids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.covered_sids = frozenset(covered_sids)

    def __bool__(self):
        # 空指纹表但覆盖面在册（被修面全部转 pass 的成功修复常态）仍按
        # 「有新鲜轮在盘」为真：调用方 `fresh_fps or {}` 形态不会把覆盖面
        # 标记挤掉。无覆盖面标记的空表保持裸 dict falsy 既有语义。
        return dict.__len__(self) > 0 or bool(self.covered_sids)


def collect_failed_fingerprints(report, scope=None, logger=None) -> dict:
    """从裁决产物 report dict 收集非 PASS 场景失败指纹（{sid: fingerprint}）。

    指纹口径与 verdict_cache 同源（``core.verdict_check.scenario_fingerprint``：
    scenario_id + status + 失败断言/失败步骤稳定 hash），不新造指纹体系。
    scope 非空时仅收集该场景 id 集合（fastlane 子集重验新鲜轮只覆盖子集，
    子集外场景不在本轮被修面内）。空指纹（产物异常 fail-open 值）不入表。
    logger 可选（调用方零改动容缺）：收集异常 fail-open 返回空表时留痕
    异常类型与摘要，区分「空表因全绿」与「空表因产物异常」。

    返回 CollectedFingerprints（dict 子类）：键值面与裸 dict 同形（仅非
    PASS 场景入表），另附 covered_sids 覆盖面标记（见类注释）。
    """
    try:
        from core.verdict_check import scenario_fingerprint

        fps = CollectedFingerprints()
        covered: set = set()
        for sc in (report or {}).get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("scenario_id") or sc.get("id") or "")
            if not sid:
                continue
            if scope is not None and sid not in scope:
                continue
            if str(sc.get("status") or "") in ("pass", "passed"):
                # PASS 场景只入覆盖面、不入指纹表：键值面保持「仅非 PASS」
                # 既有契约（派单基线/审计摘要消费方零变化），「已转 pass」
                # 的确认交由受理门凭覆盖面标记作出。
                covered.add(sid)
                continue
            fp = scenario_fingerprint(sc)
            if fp:
                fps[sid] = fp
                covered.add(sid)
        fps.covered_sids = frozenset(covered)
        return fps
    except Exception as e:  # noqa: BLE001 — 指纹收集失败按无基线处理（fail-open）
        if logger is not None:
            try:
                logger.info(
                    "pm_engine",
                    f"失败指纹收集异常（按空表＝无基线 fail-open 处理，"
                    f"与真实全绿同形）: {type(e).__name__}: {e}",
                )
            except Exception:  # noqa: BLE001 — 留痕自身失败不穿透 fail-open
                pass
        # 异常分支同样返回 CollectedFingerprints（空表+空覆盖面）而非裸 dict：
        # attach_dispatch_fingerprint 会对返回值写 covered_sids 属性，裸 dict
        # 无 __dict__ 会 AttributeError 漂移进外层「附单失败」清字段路径——
        # 终态语义虽同为无基线，但日志失真且跳过 envelope 写入（item
        # b38101d97690）；受理门侧 getattr(covered_sids) 由 None 变空面，
        # 「缺席不推断进展」保守裁决两形态同 verdict，行为零变化。
        return CollectedFingerprints(covered_sids=frozenset())


def fingerprint_brief(fps, max_items: int = 4, fp_chars: int = 12) -> str:
    """指纹 dict 的人类可读截断摘要（「sid=fp12ab34cd」形态），空 dict 返回空串。"""
    if not fps:
        return ""
    parts = [
        f"{sid}={str(fp)[:fp_chars]}"
        for sid, fp in list(fps.items())[:max_items]
    ]
    tail = f" 等共{len(fps)}项" if len(fps) > max_items else ""
    return "、".join(parts) + tail


def attach_dispatch_fingerprint(pipeline, spec_name, *, dispatch_run_id: str = ""):
    """bug-found 派发写点：收集被修场景失败指纹并持久化为受理比对基线。

    Returns:
        指纹 dict（非空）或 None（无基线——报告缺失/无失败场景）。无论成败
        MUST 覆写 STATE 字段：成功写 envelope（fps 可为空表＝本轮无基线），
        异常显式置 None 清除旧轮残留——防上一轮 envelope 在本轮报告不可读时
        被误当本轮派单指纹（陈旧基线假拒收）。失败不阻断派发（fail-open）。
    """
    try:
        from core.verdict_check import load_report

        report = load_report(pipeline._context.project_root, spec_name) or {}
        fps = collect_failed_fingerprints(report)
        # 派单基线只消费失败指纹表：覆盖面标记是新鲜轮受理门专属语义，基线
        # 不携带（复位为空面）——派单侧行为（含「报告无失败场景 → 无基线
        # 置 null」分支与返回值）零变化。
        fps.covered_sids = frozenset()
        envelope = {
            "fps": fps,
            "at": int(time.time()),
            "run": str(dispatch_run_id or ""),
        }
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                REPAIR_DISPATCH_FINGERPRINT_FIELD: json.dumps(
                    envelope, ensure_ascii=False, separators=(",", ":")
                )
            },
        )
        try:
            if fps:
                pipeline._context.logger.info(
                    "pm_engine",
                    f"派单指纹已附 '{spec_name}': {fingerprint_brief(fps)}"
                    f"（随单附被修场景失败指纹，受理点比对基线）",
                )
            else:
                pipeline._context.logger.info(
                    "pm_engine",
                    f"派单指纹无基线 '{spec_name}'（报告缺失或无失败场景）"
                    "— 置 null，受理门跳过比对，不阻断派发",
                )
        except Exception:  # noqa: BLE001 — 纯观测日志失败不得误触发下方清字段路径
            pass
        return fps or None
    except Exception as e:  # noqa: BLE001 — 指纹附单失败不阻断派发主路径
        try:
            # 显式清字段：残留旧轮 envelope 会被受理点误当本轮基线（假拒收）
            pipeline._context.state_machine.update_spec(
                spec_name, {REPAIR_DISPATCH_FINGERPRINT_FIELD: None}
            )
        except Exception:  # noqa: BLE001 — 清理失败静默（主路径已 WARNING）
            pass
        try:
            pipeline._context.logger.warning(
                "pm_engine",
                f"派单指纹附单失败 '{spec_name}'（置 null 不阻断派发）: "
                f"{type(e).__name__}: {e}",
            )
        except Exception:  # noqa: BLE001 — 告警自身失败不得穿透 fail-open 契约
            pass
        return None


def load_dispatch_fingerprint(state_machine, spec_name):
    """读取派单指纹 envelope；缺失/损坏返回 None（＝无基线，受理门跳过比对）。"""
    try:
        raw = (state_machine.read_one(spec_name) or {}).get(
            REPAIR_DISPATCH_FINGERPRINT_FIELD
        )
        if isinstance(raw, str) and raw.strip():
            env = json.loads(raw)
            if isinstance(env, dict) and isinstance(env.get("fps"), dict):
                return env
    except (json.JSONDecodeError, TypeError, ValueError, OSError, AttributeError):
        pass
    return None


def envelope_fps(envelope) -> dict:
    """取 envelope 内指纹表（空表＝本轮派单无基线）。"""
    if not isinstance(envelope, dict):
        return {}
    fps = envelope.get("fps")
    return fps if isinstance(fps, dict) else {}


def dispatch_fingerprint_detail(state_machine, spec_name) -> dict:
    """派发上下文指纹注入键值（随单附指纹，code-fix detail 顶层键）。

    detail 顶层键不受 ``prompt_builder._CODE_FIX_ITEM_FIELDS`` 白名单约束
    （该白名单只约束 items 条目），注入可序列化直达 code-fix 车道申报自检。
    无基线时 ``repair_fingerprint`` 置 null（不阻断派发）。
    """
    fps = envelope_fps(load_dispatch_fingerprint(state_machine, spec_name))
    return {
        "repair_fingerprint": fps or None,
        "repair_fingerprint_brief": fingerprint_brief(fps) or "无基线",
    }


def probe_claim_from_result(impl_result):
    """从实现者结果 dict 提取申报探针标注（design D3 约定字段）。

    Returns:
        归一化 {"scenario_id", "fingerprint", "matches_dispatch"} 或 None
        （字段缺失/形状非法＝「缺探针标注」）。
    """
    if not isinstance(impl_result, dict):
        return None
    verification = impl_result.get("verification")
    if not isinstance(verification, dict):
        return None
    probe = verification.get(REPAIR_PROBE_FIELD)
    if not isinstance(probe, dict):
        return None
    sid = str(probe.get("scenario_id") or "")
    fp = probe.get("fingerprint")
    if not sid or not isinstance(fp, str) or not fp.strip():
        return None
    # matches_dispatch 仅为实现者申报契约字段（观测面）：受理门不采信该
    # 自报旗标，一律以 evaluate_fingerprint_gate 重算指纹比对为准。
    matches = probe.get("matches_dispatch")
    return {
        "scenario_id": sid,
        "fingerprint": fp.strip(),
        "matches_dispatch": matches if isinstance(matches, bool) else None,
    }


def evaluate_fingerprint_gate(dispatch_fps, fresh_fps, *, coverage: str,
                              scope=None):
    """比对派单指纹与新鲜侧指纹，返回 (verdict, detail)。

    - 无派单基线（dispatch_fps 空）→ accept（放行，不比对）；
    - fresh_fps 为 None（缺探针标注且无盘面新鲜轮）→ reject-missing-probe；
    - coverage="probe"（探针标注覆盖）：遍历探针表全部条目（多项探针表
      不只取首项），任一场景与派单基线同指纹即拒收；探针场景无基线也
      放行；探针表为空（{}）与 None 同语义按「缺探针标注」拒收；
    - coverage="report"（新鲜轮报告覆盖）：scope 限定被修场景面（子集重验
      新鲜轮只覆盖子集，子集外场景不视为「已转 pass」）；被修面内任一场景
      指纹变化或已确认转 pass（在新鲜轮覆盖面内而失败指纹表缺席）＝ 有进展
      → accept；全部原样复现 → reject-unchanged。新鲜轮未覆盖（缺席）的
      场景不推断进展、单列注记（缺席 ≠ 已转 pass，item 787dd73fd615）；
      全部缺席且无复现证据时保守放行（无证据拒收会楔死 fix 链）。
    """
    if coverage not in ("probe", "report"):
        # 值域校验：非法取值（含拼写失误如 "probes"）不得静默落入 report
        # 分支改变比对语义，第一时间暴露调用方笔误。
        raise ValueError(
            f"coverage 取值非法: {coverage!r}（仅支持 'probe'/'report'）"
        )
    if not dispatch_fps:
        return (
            VERDICT_ACCEPT,
            "无派单基线（首轮修复或裁决产物缺失），跳过指纹比对（放行）",
        )
    if fresh_fps is None:
        return (
            VERDICT_REJECT_MISSING_PROBE,
            "缺探针标注且无盘面 post-fix 新鲜轮指纹（D1 优先级①②皆缺）",
        )
    if coverage == "probe":
        if not fresh_fps:
            return (
                VERDICT_REJECT_MISSING_PROBE,
                "缺探针标注（探针覆盖模式无探针场景，无新鲜侧指纹可比对）",
            )
        # 遍历探针表全部条目：任一场景与派单基线同指纹即拒收。只取首项
        # 比对会让多项探针表中其余零进展场景静默通过受理。
        unchanged_sids: list = []
        changed_sids: list = []
        no_baseline_sids: list = []
        for sid, fp in fresh_fps.items():
            base = dispatch_fps.get(sid)
            if base is None:
                no_baseline_sids.append(sid)
            elif base == fp:
                unchanged_sids.append(sid)
            else:
                changed_sids.append(sid)
        if unchanged_sids:
            return (
                VERDICT_REJECT_UNCHANGED,
                f"失败指纹未变化（场景 {'、'.join(unchanged_sids[:4])}，"
                "同一失败签名原样复现）",
            )
        if changed_sids:
            return (
                VERDICT_ACCEPT,
                f"探针指纹已变化（场景 {'、'.join(changed_sids[:4])}）",
            )
        return (
            VERDICT_ACCEPT,
            f"探针场景 {'、'.join(no_baseline_sids[:4])} 无派单基线，"
            "跳过比对（放行）",
        )
    # coverage == "report"
    target_sids = set(scope) if scope is not None else set(dispatch_fps)
    unchanged: list = []
    progressed: list = []
    uncovered: list = []
    no_baseline: list = []
    covered = getattr(fresh_fps, "covered_sids", None)
    for sid in target_sids:
        base = dispatch_fps.get(sid)
        if base is None:
            # 被修面内场景无派单基线（指纹收集时产物异常等）——该场景不比对
            no_baseline.append(sid)
            continue
        fresh = fresh_fps.get(sid)
        if fresh is None:
            # collect_failed_fingerprints 键值面只收非 PASS 场景：缺席在语义
            # 上混合「已转 pass」与「未被执行/被资源互斥跳过」。仅当覆盖面
            # 标记在册（该场景确在新鲜轮报告内）才确认转 pass；报告未覆盖
            # 的缺席不得推断进展（item 787dd73fd615）——不计入 progressed，
            # 也不计入 unchanged（无原样复现正证据），单列注记。
            if covered is not None and sid in covered:
                progressed.append(sid)
            else:
                uncovered.append(sid)
        elif fresh == base:
            unchanged.append(sid)
        else:
            progressed.append(sid)
    if unchanged and not progressed:
        unchanged_brief = fingerprint_brief(
            {sid: dispatch_fps[sid] for sid in unchanged}
        )
        return (
            VERDICT_REJECT_UNCHANGED,
            f"失败指纹未变化（{unchanged_brief}，同一失败签名原样复现）",
        )
    if progressed:
        uncovered_note = ""
        if uncovered:
            uncovered_note = (
                f"；缺席未判定: {'、'.join(uncovered[:4])}"
                f"{' 等共%d项' % len(uncovered) if len(uncovered) > 4 else ''}"
                "（新鲜轮未覆盖，不计进展）"
            )
        # 混合受理（任一场景有进展即放行）时原样复现场景单列注记：与缺席
        # 注记同口径保证可观测性，放行不掩盖仍有场景零进展的事实。
        unchanged_note = ""
        if unchanged:
            unchanged_brief = fingerprint_brief(
                {sid: dispatch_fps[sid] for sid in unchanged}
            )
            unchanged_note = f"；原样复现: {unchanged_brief}（失败签名未变化）"
        return (
            VERDICT_ACCEPT,
            f"被修场景指纹已变化或已转 pass（进展场景: "
            f"{'、'.join(progressed[:4])}{uncovered_note}{unchanged_note}）",
        )
    # 保守回退口径（缺席占比异常＝新鲜轮可能整轮未执行被修面）：全部缺席/
    # 无基线时既无进展证据也无原样复现证据，拒收会把 fix 链楔死在无证据
    # 猜疑上——放行，由后续整轮重验如实裁决，注记显式声明进展未判定。
    return (
        VERDICT_ACCEPT,
        f"新鲜轮未覆盖被修面可比对场景（缺席: "
        f"{'、'.join(uncovered[:4]) if uncovered else '无'}；"
        f"无基线: {'、'.join(no_baseline[:4]) if no_baseline else '无'}），"
        "进展未判定——保守放行，以后续整轮重验结论为准",
    )


def record_claim_with_fingerprints(target, spec_name, *, rejected: bool,
                                   dispatch_fps=None, fresh_fps=None) -> None:
    """受理记账（``_record_repair_claim``）+ 双方指纹留痕。

    target：pipeline 本体或 engine 侧 ``SimpleNamespace(_context=...)`` 适配器
    （两者同形暴露 _context.state_machine/_context.logger/_context.project_root）。
    """
    from core.pm_engine.verification.pipeline import _record_repair_claim

    try:
        _record_repair_claim(
            target, spec_name, rejected=rejected,
            dispatch_fingerprint=dispatch_fps, fresh_fingerprint=fresh_fps,
        )
    except Exception as e:  # noqa: BLE001 — 记账失败不阻断受理/拒收主路径
        logger = getattr(getattr(target, "_context", None), "logger", None)
        if logger is not None:
            try:
                logger.warning(
                    "pm_engine",
                    f"修复申报记账失败 '{spec_name}'（不阻断）: "
                    f"{type(e).__name__}: {e}",
                )
            except Exception:  # noqa: BLE001
                pass


def reject_repair_claim(pipeline, spec_name, *, verdict_detail: str,
                        dispatch_fps=None, fresh_fps=None,
                        as_pipeline=None, expect_status=None) -> None:
    """拒收分支（复用 writeback-gate 接线形态）：rejected 记账 + error 留痕。

    error 含「失败指纹未变化」/「缺探针标注」文案与双方指纹值，经既有重派
    上下文回传下轮；调用方 MUST 据返回语义终止本轮消费（不重入执行、不穿透
    守卫）。留痕全程容错（观测/留痕失败不改变拒收决定）。engine 侧调用点传
    ``as_pipeline`` 适配器（SimpleNamespace(_context=...)），pipeline 侧
    不传。

    ``expect_status``：error 落盘前的写点状态判据（str 或状态集，None＝
    不复核）。与 pipeline 侧 ``_discard_if_not_testing`` 同防「受理判定到
    写盘」TOCTOU 窗口：窗口内 spec 被人工复位/冻结接管/并发推进出处置状
    态面时 DEBUG 丢弃、error 不落盘，防覆写较新状态（item 42e5edeac7c8；
    rejected 记账与拒收 WARNING 先行落盘，不受丢弃影响）。判据由调用方传
    而非硬编码 testing——本门三个写点的受理语境均为 bug-found 处置面
    （engine fix 消费点入口守卫 bug-found；fastlane 承接/分流经
    family 原地打回三状态面放行），testing 判据会错杀全部合法写点。
    """
    target = as_pipeline if as_pipeline is not None else pipeline
    record_claim_with_fingerprints(
        target, spec_name, rejected=True,
        dispatch_fps=dispatch_fps, fresh_fps=fresh_fps,
    )
    dispatch_brief = fingerprint_brief(dispatch_fps) or "无基线"
    fresh_brief = (
        fingerprint_brief(fresh_fps) if fresh_fps else (
            "无（缺探针标注/无新鲜轮）" if fresh_fps is not None else "无"
        )
    )
    if not fresh_brief:
        # 空表但覆盖面在册的 CollectedFingerprints（被修面全部转 pass 的
        # 成功修复常态）按 __bool__ 为 truthy，fingerprint_brief 因 items()
        # 为空返回空串——兜底显式占位说明成因，与「无」（缺新鲜轮）区分，
        # 避免「新鲜侧: 」空槽位让日志/error 字段缺失无解释。
        fresh_brief = "表空（覆盖面内全部转 pass）"
    # 拒收 WARNING 先于 expect_status 复核落盘：即使随后 error 因状态面
    # 漂移被丢弃，拒收轮次在日志面仍留有痕迹（与 rejected 记账同序）。
    try:
        target._context.logger.warning(
            "pm_engine",
            f"修复申报被受理指纹门拒收 '{spec_name}': {verdict_detail}"
            f"（派单指纹: {dispatch_brief}；新鲜侧: {fresh_brief}）"
            "— 不重入执行，拒收信息经既有重派上下文回传下轮",
        )
    except Exception:  # noqa: BLE001 — 日志失败静默
        pass
    if expect_status is not None:
        _allowed = (
            {expect_status} if isinstance(expect_status, str)
            else set(expect_status)
        )
        _cur = (target._context.state_machine.read_one(spec_name) or {}).get(
            "status", ""
        )
        if _cur not in _allowed:
            try:
                target._context.logger.debug(
                    "pm_engine",
                    f"指纹门拒收 error 留痕丢弃 '{spec_name}'（current state "
                    f"'{_cur}', expected in {sorted(_allowed)}）— spec 已离开"
                    "受理处置状态面，rejected 记账已落、error 不覆写",
                )
            except Exception:  # noqa: BLE001 — 留痕失败不穿透拒收决定
                pass
            return
    error_text = (
        f"修复申报受理指纹门拒收（{verdict_detail}；派单指纹: "
        f"{dispatch_brief}；新鲜侧指纹: {fresh_brief}）— 本轮修复不采纳、"
        f"不重入执行，保持当前验证态，按指纹差异定向重修后重新申报"
    )
    try:
        target._context.state_machine.update_spec(
            spec_name, {"error": error_text}
        )
    except Exception as e:  # noqa: BLE001
        try:
            target._context.logger.warning(
                "pm_engine",
                f"指纹门拒收 error 留痕失败 '{spec_name}'（记账已落，不阻断）: "
                f"{type(e).__name__}: {e}",
            )
        except Exception:  # noqa: BLE001 — 留痕失败不穿透拒收决定（容错契约）
            pass


def accept_repair_claim(pipeline, spec_name, *, dispatch_fps=None,
                        fresh_fps=None, source: str = "",
                        as_pipeline=None) -> None:
    """受理放行记账（rejected=False）+ 指纹留痕；失败不阻断放行主路径。"""
    target = as_pipeline if as_pipeline is not None else pipeline
    record_claim_with_fingerprints(
        target, spec_name, rejected=False,
        dispatch_fps=dispatch_fps, fresh_fps=fresh_fps,
    )
    try:
        target._context.logger.info(
            "pm_engine",
            f"修复申报受理放行 '{spec_name}'"
            f"（{source or '指纹门'}；派单指纹: "
            f"{fingerprint_brief(dispatch_fps) or '无基线'}）",
        )
    except Exception:  # noqa: BLE001
        pass
