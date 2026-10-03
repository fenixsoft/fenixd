"""PipelineContext：VerificationPipeline 显式依赖注入容器（design D1/D10）。

VerificationPipeline 及其子组件通过 context 访问外部依赖，MUST NOT 直接回引
门面 `self._pm._<private>`——彻底消除门面封装破坏（phase 1 的核心目标）。

构造方式：`PipelineContext(pm)` 由 engine.py 的 `_verification` property
注入，也可在测试中手动构造（只需提供 D1 六成员 + D10 补充成员）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from core.state_machine import StateMachine


class _Logger(Protocol):
    """最小 logger 接口（engine.Logger 或 MagicMock 均满足）。"""

    def debug(self, *a: Any, **kw: Any) -> None: ...
    def info(self, *a: Any, **kw: Any) -> None: ...
    def warning(self, *a: Any, **kw: Any) -> None: ...
    def error(self, *a: Any, **kw: Any) -> None: ...


def _ocr_join_gate_disabled(spec_name: str, origin: str) -> str:
    """ocr join 门禁缺省实现：恒放行（"pass"）。

    add-impl-ocr-parallel-lane：供 ocr_join_gate 字段作 dataclass 缺省值——
    手动构造 context 的纯管道单测不提供该成员时，门禁视为未启用，验证管道
    行为与车道引入前逐字节一致（缺省关闭零行为变化）。
    """
    return "pass"


def _parallel_plan_lane(pm: Any) -> Any:
    """并行出题车道控制包装（add-verify-lane-throughput 1.3）。

    SimpleNamespace 成员 lambda **延迟解析** pm 私有方法（属性访问推迟到
    真正调用时，与 from_pm 委托成员同约定）：SimpleNamespace 式 pm 桩未声明
    对应私有属性时，调用才 AttributeError——消费侧外层 try/except fail-open
    回落串行出题，不影响验证轮。
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        read_marker=lambda spec_name: pm._read_parallel_plan_marker(spec_name),
        write_marker=lambda spec_name, payload: pm._write_parallel_plan_marker(
            spec_name, payload
        ),
        quarantine=lambda spec_name, reason: pm._quarantine_parallel_product(
            spec_name, reason
        ),
        stop=lambda spec_name, reason: pm._stop_parallel_planning(spec_name, reason),
    )


def _agent_runner_lane(pm: Any) -> Any:
    """fastlane code-fix 轻量修复派发包装（minor-defect-fastlane）。

    SimpleNamespace 成员 lambda **延迟解析** pm.agent_runner（与
    _parallel_plan_lane 同约定）：桩 pm 未声明 agent_runner 属性时，调用才
    AttributeError——消费侧按接线故障 ERROR 留痕后记账回落整轮，不影响验证轮。
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        _execute_agent=lambda *args, **kwargs: pm.agent_runner._execute_agent(
            *args, **kwargs
        ),
    )


@dataclass(frozen=False)
class PipelineContext:
    """VerificationPipeline 显式依赖注入容器。

    D1 核心成员（高频只读 / 跨域调用）：
        logger                直接引用 pm.logger
        project_root          直接引用 pm.project_root（Path）
        state_machine         直接引用 pm.state_machine
        config_reader         委托 pm._get_config(key, default)
        escalation_notifier   委托 pm._send_human_escalation_alert(...)
        enqueue               委托 pm._enqueue(spec_name, agent_type)

    D10 补充成员（6 个 PMEngine 私有目标，必须由 context 承载才能满足
    `grep -c 'self._pm._' == 0` 的数学可达性）：
        is_fix_spec           委托 pm._is_fix_spec(spec_name) → bool
        on_spec_verified      委托 pm._on_spec_verified(spec_name)
        on_spec_bug_found     委托 pm._on_spec_bug_found(spec_name,
                              failure_class="product", run_id="")
        read_implementer_result  委托 pm._read_implementer_result(spec_name)
        exempt_infra_run_budget  委托 pm._exempt_infra_run_budget(spec_name,
                                reason, refund_key="")
        env_infra_markers     只读 tuple，来自 pm._ENV_INFRA_MARKERS
        ocr_join_gate         委托 pm._dispatcher._ocr_join_gate(spec_name,
                              origin) → "pass"/"defer"/"reject"
                              （add-impl-ocr-parallel-lane：Dispatcher 未组合
                              的桩 pm 缺省恒放行，见 _ocr_join_gate_disabled）
    """

    # ── D1 核心成员 ─────────────────────────────────────────────────────────
    logger: _Logger
    project_root: Path
    state_machine: "StateMachine"

    config_reader: Callable[..., Any] = field(repr=False)
    escalation_notifier: Callable[..., None] = field(repr=False)
    enqueue: Callable[[str, str], None] = field(repr=False)

    # ── D10 补充成员（PMEngine 私有 → context 成员）─────────────────────────
    is_fix_spec: Callable[[str], bool] = field(repr=False)
    on_spec_verified: Callable[[str], None] = field(repr=False)
    on_spec_bug_found: Callable[..., None] = field(repr=False)
    read_implementer_result: Callable[[str], Optional[dict]] = field(repr=False)
    exempt_infra_run_budget: Callable[..., bool] = field(repr=False)
    # add-impl-ocr-parallel-lane：testing 出口 ocr join 门禁（有缺省，桩 context
    # 不提供即视为车道未启用）。
    ocr_join_gate: Callable[[str, str], str] = field(
        repr=False, default=_ocr_join_gate_disabled
    )
    env_infra_markers: tuple[str, ...] = field(default=(), repr=True)

    # ── add-verify-lane-throughput 1.3：并行出题车道控制（SimpleNamespace，
    # 成员 lambda 委托 pm 私有方法——pipeline 侧零 self._pm._ 回引，契约
    # test_no_self_pm_private_in_pipeline）。有缺省：桩 context 不提供即视
    # 为车道未启用（消费侧 fail-open 回落串行）。
    parallel_plan_lane: Any = field(default=None, repr=False)

    # ── minor-defect-fastlane：code-fix 轻量修复派发（SimpleNamespace 包装，
    # 成员 lambda 委托 pm.agent_runner——pipeline 侧零 self._pm._ 回引）。
    # 有缺省：桩 context 不提供即视为车道不可派发（消费侧按接线故障记账
    # 回落整轮）；测试可整体覆写该成员（SimpleNamespace 桩同源可用）。
    agent_runner: Any = field(default=None, repr=False)

    # ── 便捷构造（从 PMEngine 实例一键创建）─────────────────────────────────

    @classmethod
    def from_pm(cls, pm: Any) -> "PipelineContext":
        """从 PMEngine 实例构造 PipelineContext。

        委托成员以**关键字参数转发**的包装函数绑定 pm 对应私有方法：
        - 调用方传入的关键字参数原样透传给 pm 方法，与重构前
          `self._pm._<method>(...)` 的调用签名逐字节一致（既有测试以关键字
          参数断言 mock 调用，位置化转发会丢失 kwargs 语义）；
        - 属性访问**推迟到真正调用时**而非构造时——`SimpleNamespace` 式
          pm 桩只声明部分私有属性（如 test_scenario_reroute_gate 的 _mk_pm），
          构造时读取全部属性会 AttributeError。
        """

        def _config_reader(key: str, default: Any = None) -> Any:
            return pm._get_config(key, default)

        def _escalation_notifier(
            spec_name: str,
            signal_type: str,
            severity: str,
            description: str,
            evidence: str,
            recommended_action: str,
            trigger: dict | None = None,
            facts: dict | None = None,
        ) -> None:
            # 与既有调用点/测试断言逐字节一致：关键字转发；trigger 缺省时
            # 不显式下传（原调用点未传 trigger 时 mock 断言不含该键）。
            # kwargs 组装后单点转发（code-review item 2b17c6a6d9dc）：新增
            # 参数只改签名与 kwargs 一处，两分支不再各自复制六个实参。
            # facts 为可选结构化增强参数位（upgrade-narrative-to-investigation
            # 1.2：本期调用点缺省不传不注入），None 时不显式下传——既有 mock
            # 断言的调用形态零变化。
            kwargs = dict(
                spec_name=spec_name,
                signal_type=signal_type,
                severity=severity,
                description=description,
                evidence=evidence,
                recommended_action=recommended_action,
            )
            if trigger is not None:
                kwargs["trigger"] = trigger
            if facts is not None:
                kwargs["facts"] = facts
            pm._send_human_escalation_alert(**kwargs)

        def _enqueue(spec_name: str, agent_type: str) -> None:
            return pm._enqueue(spec_name, agent_type)

        def _is_fix_spec(spec_name: str) -> bool:
            return pm._is_fix_spec(spec_name)

        def _on_spec_verified(spec_name: str) -> None:
            return pm._on_spec_verified(spec_name)

        def _on_spec_bug_found(
            spec_name: str,
            failure_class: str = "product",
            run_id: str = "",
        ) -> None:
            return pm._on_spec_bug_found(spec_name, failure_class=failure_class, run_id=run_id)

        def _read_implementer_result(spec_name: str) -> Optional[dict]:
            return pm._read_implementer_result(spec_name)

        def _exempt_infra_run_budget(
            spec_name: str,
            reason: str,
            refund_key: str = "",
        ) -> bool:
            return pm._exempt_infra_run_budget(spec_name, reason, refund_key=refund_key)

        def _ocr_join_gate(spec_name: str, origin: str) -> str:
            # add-impl-ocr-parallel-lane：属性访问推迟到调用时（与上方委托
            # 包装同惯例）。桩 pm 未组合 Dispatcher（无 _dispatcher 属性）时
            # 恒放行——车道缺省关闭，纯管道单测零行为变化。
            dispatcher = getattr(pm, "_dispatcher", None)
            if dispatcher is None:
                return "pass"
            return dispatcher._ocr_join_gate(spec_name, origin)

        return cls(
            logger=pm.logger,
            project_root=pm.project_root,
            state_machine=pm.state_machine,
            config_reader=_config_reader,
            escalation_notifier=_escalation_notifier,
            enqueue=_enqueue,
            is_fix_spec=_is_fix_spec,
            on_spec_verified=_on_spec_verified,
            on_spec_bug_found=_on_spec_bug_found,
            read_implementer_result=_read_implementer_result,
            exempt_infra_run_budget=_exempt_infra_run_budget,
            ocr_join_gate=_ocr_join_gate,
            parallel_plan_lane=_parallel_plan_lane(pm),
            agent_runner=_agent_runner_lane(pm),
            env_infra_markers=getattr(pm, "_ENV_INFRA_MARKERS", ()),
        )
