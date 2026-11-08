"""core/admin_choice_exec.py — Administrator 处置 choice 执行机器单源
（fix-escalation-chain-ledger-closure 2.1，design D3）。

``AdminMonitor._apply_choice_execution`` / ``_persist_choice_step_records``
的执行核心抽为模块级函数；AdminMonitor 同名方法委托之（直接路径行为回归
零变化），处置链 closed 出口调用同一模块级函数——人工 alert-resolve、
admin_monitor 直接路径、链路径三处同源一个执行机器（不复制分支逻辑，
对齐 ``execute_adjudication_choice`` 单执行机器纪律）。

对 dashboard data 层沿用函数内 lazy import 既有形态（import 环规避：
admin_monitor 对本模块同为 lazy import，arbiter/escalation_chain 同）。
"""

# 全局信号占位 spec（降级分支判定用；与 adjudication_choices.
# GLOBAL_SPEC_PLACEHOLDER / admin_monitor._ORPHAN_GLOBAL_SPEC_PLACEHOLDER
# 同值——导入失败场景不能依赖上游常量，本模块自带同值字面量）
_GLOBAL_SPEC_PLACEHOLDER = "global"


def execute_choice_for_disposition(project_root, signal: dict, disp, logger
                                   ) -> "dict | None":
    """Administrator 处置 choice_id 非空 → 执行注册表动作映射（4.2）。

    与人工 alert-resolve 端点共用 ``execute_adjudication_choice``：同一
    动作映射、同一留痕格式。执行结果只记审计日志（最终 DISPOSITION
    记录已含 choice_id 留痕，动作步骤入日志 context）；执行失败记
    ERROR 不阻塞后续收尾（escalation 闭环 / 升级告警），失败状态由
    日志与既有告警面呈现。

    fix-global-signal-choice-execution 2.1/2.2：返回执行结果 dict 供终态
    回写判定——``{"ok": bool, "action": str|None, "error": str|None,
    "skipped": bool, "steps": list}``；各出口键集统一：skipped 恒给出、
    steps 空列表兜底（code-review item 66154381bdd7，下游
    persist_choice_step_records 只消费 ok/skipped/action/error，补键无
    副作用）；未尝试执行（choice_id 为空 / 无关联 spec）返回
    None。全局信号（spec 为空或占位 'global'）的 spec_scoped choice 在此
    提前跳过并留 INFO（与『无关联 spec 跳过』分支同型；执行器守卫
    1.2 为正确性兜底），跳过形态返回 ok=False + skipped=True——信号保留
    待重审，不闭环。

    Args:
        project_root: 消费项目根（执行器 ``execute_adjudication_choice``
            首参；AdminMonitor 传 self.project_root，链路径传链实例的
            project_root）。
        signal: 本次唤起信号 dict（含 signal_type/spec）。
        disp: AdminDisposition 处置结果（duck-typed）。
        logger: 结构化 logger（AdminMonitor/链实例各自注入；日志通道
            保持 ``admin_monitor`` 与抽取前一致）。
    """
    choice_id = str(getattr(disp, "choice_id", "") or "").strip()
    if not choice_id:
        return None
    # disp duck-typed 防御访问与 choice_id 同口径（code-review item
    # d90b707f972f）：宿主对象缺 spec 属性不得 AttributeError 穿透执行函数。
    spec = signal.get("spec") or getattr(disp, "spec", "")
    # fix-global-signal-choice-execution 2.1：全局信号 × spec_scoped choice
    # 提前跳过（双层设防的消费端一层），避免无谓执行报错；INFO 留痕。
    # 守卫须先于『无关联 spec 跳过』分支——spec 为空同样属全局形态，此
    # 形态下 spec_scoped choice 的跳过 MUST 以 not-ok 结果上报（拦截终态
    # 回写，信号保留待重审），不能走 None 短路被回写门视为已执行成功。
    # 未知/拒解析 choice_id（unknown-choice / not-in-bucket）对**具体
    # spec** 仍放行执行器报非法 choice（走失败留痕）；全局信号下执行器
    # 守卫触达不到——这些拒绝形态会落『无关联 spec』分支返回 None，被
    # 终态回写门按 resolved 收口、失败留痕永不触达（code-review item
    # ec2297068d68），故拒绝形态并入本守卫走 not-ok skipped，与导入失败
    # 降级分支（d5edc8ac335e）同方向 fail-closed。
    _resolved_choice = None
    # fix-admin-choice-payload-and-scenario-pairing 4.1：requires_payload
    # 位同样在作用域守卫处顺带读取（单次 resolve_choice 双用，不二次解析）
    _requires_payload = False
    try:
        from core.dashboard.data.adjudication_choices import (
            is_global_spec,
            resolve_choice,
        )

        _resolved_choice, _resolve_reason = resolve_choice(
            choice_id, str(signal.get("signal_type") or "")
        )
        # 载荷要求读注册表解析结果（单源），不硬编码选项名单
        _requires_payload = bool(
            (_resolved_choice or {}).get("requires_payload", False)
        )
        # scoped-no-reverse（未注册 signal_type 的 spec_scoped 动作被反查
        # 收紧拒解析）同属作用域拒入形态——全局信号照此提前跳过；
        # not-in-bucket / unknown-choice 拒解析形态同并入（见上方注释，
        # code-review item ec2297068d68）
        _globally_scoped = bool(
            is_global_spec(spec)
            and (
                (
                    _resolved_choice
                    and _resolved_choice.get("spec_scoped", True)
                )
                or _resolve_reason
                in ("scoped-no-reverse", "not-in-bucket", "unknown-choice")
            )
        )
    except Exception as e:  # noqa: BLE001 — 守卫不可用不阻塞执行（执行器兜底）
        logger.debug(
            "admin_monitor",
            f"choice 作用域预判不可用（执行器守卫兜底）: {e}",
        )
        _resolved_choice = None
        # 拒绝原因位随守卫降级缺省空串（下方 skipped 留痕分支引用，
        # 降级路径 resolve_choice 未成功调用、无拒绝原因可考）
        _resolve_reason = ""
        # 载荷要求位随守卫降级缺省 False（不拦处置，载荷合法性由执行器
        # 既有解析失败路径拒绝，与作用域守卫降级同方向）
        _requires_payload = False
        # code-review d5edc8ac335e：降级分支对全局形态 spec（空值或占位
        # 'global'，同 is_global_spec 口径）保守沿用 not-ok skipped 语义，
        # 与非降级路径 fail-closed 方向一致——否则空 spec × spec_scoped
        # choice 会落入下方「无关联 spec」分支返回 None，终态回写门把
        # None 视为未执行无阻塞、信号按 resolved 收口，违背 docstring 的
        # fail-closed 承诺（该形态下执行器守卫兜底不被触达）。具体 spec
        # 不受影响，照常放行执行器兜底。占位常量复用本模块既有定义
        # （导入失败场景不能依赖 adjudication_choices 的
        # GLOBAL_SPEC_PLACEHOLDER）。
        _spec_form = str(spec or "").strip().lower()
        _globally_scoped = (
            (not _spec_form)
            or _spec_form == _GLOBAL_SPEC_PLACEHOLDER
        )
    if _globally_scoped:
        # 拒解析形态（not-in-bucket/unknown-choice）下作用域不可考，留痕
        # 以 choice_id 兜底并附拒绝原因，不作「spec 作用域动作」的失真
        # 表述（code-review item ec2297068d68）
        _skip_basis = (
            f"choice 拒解析（{_resolve_reason}）"
            if _resolve_reason in ("not-in-bucket", "unknown-choice")
            else "为 spec 作用域动作"
        )
        logger.info(
            "admin_monitor",
            f"处置 choice_id={choice_id} {_skip_basis}，全局信号"
            f"（spec={spec!r}）无 spec 可操作，跳过执行（信号保留待重审）",
        )
        return {"ok": False, "skipped": True,
                # 拒解析形态（scoped-no-reverse/not-in-bucket/
                # unknown-choice）解析结果为 None，动作名以 choice_id
                # 兜底（留痕 action_taken 不缺位）
                "action": ((_resolved_choice or {}).get("action") or choice_id),
                "error": (f"全局信号（spec={spec!r}）不可执行"
                          f"（{_skip_basis}），已跳过"),
                "steps": []}
    if not spec and not (
        _resolved_choice and not _resolved_choice.get("spec_scoped", True)
    ):
        # 无关联 spec（信号与处置记录均空）且动作语义需要具体 spec
        # （spec_scoped / 注册表未知 id）——跳过执行。非作用域动作放行
        # （1.3：全局/空 spec 信号的非作用域收口不断路，执行器守卫 1.2
        # 兜底正确性）。
        logger.warning(
            "admin_monitor",
            f"处置 choice_id={choice_id} 无关联 spec，跳过执行",
        )
        return None
    # fix-admin-choice-payload-and-scenario-pairing 4.1：note 来源载荷优先
    # ——choice_payload 非空 → 原文整体直传（不经 actions_taken 拼接/截断，
    # 载荷型选项执行器契约强制完整 JSON 载荷，200 字截断结构性必败）；
    # 载荷空且选项 requires_payload → not-ok skipped（信号保留待重审），
    # 不空打执行器制造必然失败日志（处置产物硬门 3.1 为前置防线，此处
    # 双层设防）；其余情况维持依据文本截断 200 字现状。
    _choice_payload = str(getattr(disp, "choice_payload", "") or "")
    if _choice_payload.strip():
        basis = _choice_payload
    elif _requires_payload:
        logger.warning(
            "admin_monitor",
            f"处置 choice_id={choice_id} 为 requires_payload 选项而处置"
            "记录未携带 choice_payload JSON 载荷，跳过执行（信号保留待重审）",
        )
        return {"ok": False, "skipped": True,
                "action": ((_resolved_choice or {}).get("action") or choice_id),
                "error": ("该选项需要 choice_payload JSON 载荷"
                          '（{"scenarios": [...], "reason": "...", '
                          '"fixture_files": [...]}），处置记录未携带，'
                          "已跳过执行"),
                "steps": []}
    else:
        # 依据原文随执行留痕（截断防日志膨胀；完整依据已在 DISPOSITION 记录）
        basis = str(getattr(disp, "actions_taken", "") or "")[:200]
    # 陈旧代码预检（evo-add-key-path-stale-code-preflight 2.3）：choice 执行
    # 前查询进程代码陈旧旗标；陈旧则请求重启（一条 WARNING + daemon 侧
    # .fenix/restart_request 防重）并照常执行——执行结果与留痕不受预检影响。
    # 导入/调用与相邻 adjudication_choices 导入同款受守卫（code-review item
    # 17d5aecc7009）：异常按失败留痕上报（ok=False），不穿透本函数令终态
    # 回写与失败留痕双双缺席（pending 处置记录滞留孤儿）。
    try:
        from core.code_stale_flag import request_restart

        request_restart(
            lambda msg: logger.warning("admin_monitor", msg),
            "admin 处置 choice 执行",
        )
    except Exception as e:  # noqa: BLE001 — 预检失败按失败留痕，不穿透
        logger.error(
            "admin_monitor",
            f"陈旧代码预检（request_restart）异常 choice_id={choice_id} "
            f"spec='{spec}': {e}",
        )
        return {"ok": False, "skipped": False, "steps": [],
                "action": None,
                "error": f"陈旧代码预检异常: {e}"}
    try:
        from core.dashboard.data.admin_actions import execute_adjudication_choice

        result = execute_adjudication_choice(
            project_root,
            spec,
            choice_id,
            note=basis,
            signal_type=str(signal.get("signal_type") or ""),
        )
    except Exception as e:
        logger.error(
            "admin_monitor",
            f"处置 choice 执行异常 choice_id={choice_id} spec='{spec}': {e}",
        )
        # fix-global-signal-choice-execution 2.2：异常按失败上报——终态回写
        # 被拦截（fail-closed，信号保留待重审）
        return {"ok": False, "skipped": False, "steps": [],
                "action": None, "error": f"choice 执行异常: {e}"}
    if result.get("ok"):
        logger.info(
            "admin_monitor",
            f"处置 choice 执行成功 choice_id={choice_id} spec='{spec}'",
            {"steps": result.get("steps") or [], "action": result.get("action")},
        )
    else:
        logger.error(
            "admin_monitor",
            f"处置 choice 执行失败 choice_id={choice_id} spec='{spec}': "
            f"{result.get('error')}",
            {"steps": result.get("steps") or []},
        )
    return {"ok": bool(result.get("ok")), "skipped": False,
            "action": result.get("action"),
            "error": result.get("error"),
            "steps": result.get("steps") or []}


def persist_choice_step_records(store, signal: dict, signal_rec, disp,
                                choice_outcome, logger) -> None:
    """结构化 choice 通道小步落账（evo-add-admin-orphan-disposition-effect-check 2.1）。

    choice 执行返回后、final append 前落一条逐动作 DISPOSITION 事件
    （含 action_taken 与结果）：run 在 final 落账前死亡时已执行事实不丢
    （「执行成功→落账」窗口从秒级收敛到零）。两条硬约束：

    - 事件 MUST NOT 携带 admin_run_id（循 _close_signal_preprobed 无
      run_id 留痕先例）——携带会被 _merge_admin_runs 并入本组使组提前
      final，破坏「在飞 = has_pending 且非 final」判据（
      _spec_has_active_admin_run 的重派/节流护栏失守）；
    - 提前收口以 choice 整体执行 ok 为准（outcome["ok"]=True 才
      mark_signal_handled(result="resolved")），不按单动作成功收口；
      任一步骤失败（整体非 ok）不收口、不预写 resolved（保
      evo-fix-global-signal-choice-execution 2.2「信号保留待重审」的
      fail-closed 语义），失败形态落 result=failed 审计事件（非
      resolved，不触发任何回写门/静默期语义）。全局跳过形态
      （skipped=True）未执行任何动作，不落事件。

    落账/收口失败仅记日志，不阻塞 final 落账主链路。

    Args:
        store: AdminStore（AdminMonitor 传 self.store，链路径传自建实例）。
        signal: 本次唤起信号 dict。
        signal_rec: 关联信号记录（人工通道 None，跳过收口回写）。
        disp: AdminDisposition 处置结果（duck-typed）。
        choice_outcome: ``execute_choice_for_disposition`` 返回值。
        logger: 结构化 logger（通道保持 ``admin_monitor``）。
    """
    if choice_outcome is None or choice_outcome.get("skipped"):
        return
    ok = bool(choice_outcome.get("ok"))
    action = (
        choice_outcome.get("action")
        or str(getattr(disp, "choice_id", "") or "")
        or ""
    )
    try:
        from core.admin_store import DISPOSITION

        store.append(
            {
                "kind": DISPOSITION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec") or disp.spec,
                "severity": signal.get("severity"),
                "description": getattr(disp, "problem", "") or signal.get("description") or "",
                "action_taken": action,
                "result": "resolved" if ok else "failed",
                "error": "" if ok else str(choice_outcome.get("error") or "执行失败"),
                # 刻意不携带 admin_run_id：见 docstring 硬约束①
            }
        )
    except Exception as e:
        logger.error(
            "admin_monitor",
            f"choice 逐动作小步落账写入失败（不阻塞 final 落账）: {e}",
        )
    if not ok:
        return
    if signal_rec is not None:
        try:
            if store.mark_signal_handled(
                signal_rec.get("id"),
                action_taken=action,
                result="resolved",
            ):
                logger.info(
                    "admin_monitor",
                    f"choice 整体执行 ok，已提前收口信号 handled=true"
                    f"（id={signal_rec.get('id')}，"
                    f"{signal.get('signal_type')}，action={action}）",
                )
        except Exception as e:
            logger.warning(
                "admin_monitor",
                f"choice 提前收口信号失败（不阻塞 final 落账）: {e}",
                # 留痕自身不得再抛 AttributeError 穿透本函数（code-review
                # item d90b707f972f，duck-typed 防御访问口径统一）
                {"record_id": signal_rec.get("id"),
                 "run_id": getattr(disp, "run_id", None)},
            )
