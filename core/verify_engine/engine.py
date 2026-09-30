"""
engine.py — 验证引擎主控（Runner 插件化调度，design D1）

职责（纯调度，不含 per-kind 执行分支）：
  - 接收测试场景列表，规范化并按 kind 查注册表分派
  - 验收门收集：逐场景委托 Runner.validate（失败不启任何 Runner、不执行）
  - 按场景集实际出现的 kind **lazy setup/teardown**（纯 CLI/API 轮次不启浏览器）
  - 拓扑排序 + 信号量并行执行（每场景委托 Runner.execute）
  - 环境健全性门骨架：候选识别 → 整轮一次探针（探针本体委托 Runner）→ 批量降级
  - 场景状态判定 / 进度写盘 / 报告构建与保存

并行策略（默认）：
  - 拓扑排序：按 depends_on 声明分层层级
  - 同层并行：依赖已满足的场景通过 asyncio.gather + Semaphore 并发
  - 信号量控制：max_parallel 限制同时运行的场景数（默认5）
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .runner import (
    VerifyRunner,
    RUNNER_REGISTRY,
    get_runner_class,
    determine_scenario_status,
    _NullLogger,
)
from .scenarios import TestScenario, VALID_KINDS
from .env_gate import (
    finalize_scenario_status,
    is_env_candidate,
    is_connection_error_candidate,
    is_blank_render_candidate,
    probe_http_health,
)

# 导入 Runner 模块触发注册（web→WebRunner / api→ApiRunner / cli→CliRunner）；
# 引擎只按注册表分派，新增 kind 仅需在此追加导入。
from .web_runner import WebRunner, locate_app_base_url  # noqa: F401,E402
from .api_runner import ApiRunner  # noqa: F401,E402
from .cli_runner import CliRunner  # noqa: F401,E402

# 终态失败档（code-review item 5867b3576e1f）：依赖失败传播判定
# （_execute_parallel）与报告状态计数（_build_report）共用的单点字面量，
# 新增失败档状态在此同步扩展，勿在调用点散落硬编码。
TERMINAL_FAILURE_STATUSES = ("fail", "error")


class VerifyEngine:
    """验证引擎主控（纯调度）。

    流程：
    1. 加载测试场景（从JSON或直接传入）
    2. 验收门（逐场景委托 Runner.validate）
    3. 按场景集实际 kind lazy setup（只 setup 出现过的 Runner）
    4. 拓扑排序 → 并行执行场景（每场景委托对应 Runner.execute）
    5. 环境健全性门（探针委托 Runner.probe_env）
    6. 汇总报告
    7. teardown 全部已 setup 的 Runner
    """

    def __init__(
        self,
        spec_name: str,
        project_root: Path,
        logger=None,
        config: Optional[dict] = None,
        scenario_root: Optional[Path] = None,
    ):
        self.spec_name = spec_name
        self.project_root = project_root
        self.logger = logger or _NullLogger()
        self.config = config or {}
        # 场景执行根：worktree 轮传入 serving worktree 根，CLI 步骤
        # 缺省 cwd 以此为准；None 时回退 project_root（无 worktree 轮）。
        # 簿记路径（verify-progress）仍固定 project_root，不受此影响。
        self.scenario_root = scenario_root
        self._runners: dict[str, VerifyRunner] = {}
        self._env_probe = None
        # 契约统一供给的实例 base_url（design D4/D2.3：验证开始时确定，
        # 传给各 Runner，取代 navigate 文本正则考古）。无实例形态为空串。
        self.base_url = ""

        # 并行度配置（容错口径同 escalation.py：脏值回退默认 5，
        # 下限 1——信号量计数为 0 会令并行池永久拿不到许可而挂死）
        verify_cfg = (config or {}).get("verify_engine") or {}
        if not isinstance(verify_cfg, dict):  # 段非 dict（str/list 等）时回退空段
            verify_cfg = {}
        try:
            self.max_parallel = max(1, int(verify_cfg.get("max_parallel", 5)))
        except (TypeError, ValueError):
            self.max_parallel = 5

        # 兼容旧访问点：web Runner 的浏览器管理器（未创建 web Runner 时为
        # None；测试/回退路径可直连注入假浏览器）。
        self.browser = None

    # ── Runner 分派 ───────────────────────────────────────────

    def _runner_for(self, kind: str) -> VerifyRunner:
        """按 kind 查注册表惰性创建 Runner（memoize）。

        调度器唯一的分派点：无 per-kind if/else 执行分支。
        """
        if kind not in self._runners:
            cls = get_runner_class(kind)
            if cls is None:
                raise ValueError(
                    f"场景 kind '{kind}' 未注册 Runner，"
                    f"支持: {', '.join(sorted(RUNNER_REGISTRY))}"
                )
            runner = cls(
                self.spec_name,
                self.project_root,
                self.logger,
                self.config,
                scenario_root=self.scenario_root,
            )
            if self.base_url:
                runner.base_url = self.base_url
            self._runners[kind] = runner
            if kind == "web":
                self.browser = runner.browser  # 兼容旧访问点
        return self._runners[kind]

    # ── 主入口 ────────────────────────────────────────────────

    async def run(self, scenarios: list) -> dict:
        """主入口。

        Args:
            scenarios: TestScenario 对象列表 或 dict 列表
                       如果传入dict，会自动做 from_dict 转换

        Returns:
            report dict，结构:
            {
                "spec": str,
                "timestamp": iso8601,
                "summary": {total, passed, warnings, failed},
                "scenarios": [{...}, ...],
            }
        """
        # 探针 memoize 以单次 run 为界（code-review 5e779321cdad）：引擎实例
        # 被复用跑第二轮时不得套用上一轮的探针结论，入口先重置。
        self._env_probe = None

        # 规范化场景
        normalized = []
        # 验收错误清单提前到规范化期收集：dict 形态场景解析失败也走下方
        # 验收门同一出口打回 plan（code-review item 6e84d77a0f58）。
        acceptance_errors: list[str] = []
        for i, s in enumerate(scenarios):
            if isinstance(s, TestScenario):
                normalized.append(s)
            elif isinstance(s, dict):
                # 逐条捕获（对齐 load_scenarios 的解析容错）：畸形 dict
                # （如缺 id 键）若放任 from_dict 抛 KeyError，会穿出 run()
                # 不落报告、不写进度、不走「场景验收失败」打回通道。
                try:
                    normalized.append(TestScenario.from_dict(s))
                except Exception as e:
                    acceptance_errors.append(
                        f"场景[{i}] dict 解析失败: {type(e).__name__}: {e}"
                    )
            else:
                self.logger.warning(
                    "verify_engine",
                    f"跳过非场景对象: {type(s).__name__}",
                )

        # ── 场景验收门（2026-08-28：相对 navigate 导致白屏整轮假失败）──
        # 验收失败不启动任何 Runner、不执行任何场景，返回带 env_error 的
        # 空报告，由 pm_engine 退回 plan 阶段重新生成（上限与反馈机制在调用方）。
        seen_ids: set[str] = set()
        for s in normalized:
            # id 形态守卫（code-review item 1905de7d8585）：id 为 dict/list
            # 等不可哈希形态（冻结文件被手工修坏）时，下方对 set 的成员判断
            # 先抛 TypeError 穿出 run()——不落报告、不走「场景验收失败」打
            # 回通道，且成员判断先于 validate_scenario 的 isinstance 守卫执
            # 行，绕开了该防线。非 str 直接归入验收错误打回 plan。
            if not isinstance(s.id, str):
                acceptance_errors.append(
                    f"场景 id 必须为字符串，收到 {type(s.id).__name__}"
                )
                # id 已坏时逐字段校验无法归位（validate_scenario 内
                # id.strip() 会再抛 AttributeError），整场景跳过即可。
                continue
            # 跨场景 id 查重：validate 仅单场景校验不查重，重复 id 会被
            # _execute_parallel 的 completed_ids 过滤静默剔除（后到者不执行、
            # 不进报告），导致场景漏验证，故在此打回 plan。
            if s.id in seen_ids:
                acceptance_errors.append(
                    f"场景'{s.id}' id 重复（场景集内 id 必须唯一）"
                )
            else:
                seen_ids.add(s.id)
            # kind 形态守卫（同 item 1905de7d8585）：非 str kind 对 set 求
            # 成员先抛 TypeError，交 validate_scenario 的同源守卫报
            # 「未知 kind」（消息保留原值），此处仅避免成员判断先行爆炸。
            if not isinstance(s.kind, str) or s.kind not in VALID_KINDS:
                acceptance_errors.extend(s.validate())
                continue
            if get_runner_class(s.kind) is None:
                # kind 合法但 Runner 未注册（如 cli/api 尚未实现）：属验收
                # 错误打回 plan，而非运行时崩溃。
                acceptance_errors.append(
                    f"场景'{s.id}' kind '{s.kind}' 未注册 Runner，"
                    f"支持: {', '.join(sorted(RUNNER_REGISTRY))}"
                )
                continue
            acceptance_errors.extend(self._runner_for(s.kind).validate(s))
        # 悬空依赖校验：须在 seen_ids 收集完整个场景集后进行——前向引用
        # （被依赖场景定义在后）合法，不能在单遍循环里逐个判定。引用不
        # 存在的 dep id 会让 _execute_parallel 的就绪判定永远不满足，落入
        # 「ready 为空 → 全部并发」兜底，声明的先后顺序被静默丢弃。
        for s in normalized:
            # depends_on 形态守卫（code-review item 1905de7d8585）：容器非
            # list（冻结文件被修坏成 str/int 等）会让迭代本身抛 TypeError、
            # 元素为 dict 等不可哈希形态会让下方成员判断抛 TypeError，均穿出
            # run()。容器非 list 已由 validate_scenario 报「必须为场景ID列
            # 表」，此处跳过避免重复记账；非 str 元素归入验收错误打回 plan。
            if not isinstance(s.depends_on, list):
                continue
            for dep in s.depends_on:
                if not isinstance(dep, str):
                    acceptance_errors.append(
                        f"场景'{s.id}' depends_on 元素必须为场景ID字符串，"
                        f"收到 {type(dep).__name__}"
                    )
                elif dep not in seen_ids:
                    acceptance_errors.append(
                        f"场景'{s.id}' depends_on 引用不存在的场景 id '{dep}'"
                        f"（场景集内不存在该 id）"
                    )
        if acceptance_errors:
            head = "; ".join(acceptance_errors[:5])
            more = f" 等 {len(acceptance_errors)} 项" if len(acceptance_errors) > 5 else ""
            msg = f"场景验收失败（{head}{more}）"
            self.logger.error("verify_engine", msg)
            self._write_progress(0, len(normalized), msg)
            report = self._build_report([])
            report["env_error"] = msg
            self._save_report(report)
            return report

        # add-verify-parallel-backoff / design D3：降档轮（inconclusive 重验
        # 由 pm_engine 以 `_verify_parallel_override` 覆盖 max_parallel 后置位
        # `_parallel_override_active`）日志附降档来源标记，时间轴可追溯
        # 「因连续 blocked-env 降档至并行度 N」。
        _backoff_mark = (
            "（inconclusive 降档）" if getattr(self, "_parallel_override_active", False) else ""
        )
        self.logger.info(
            "verify_engine",
            f"🚀 开始验证 '{self.spec_name}': "
            f"{len(normalized)} 个场景, 并行度={self.max_parallel}{_backoff_mark}",
        )

        # ── 零场景守卫（code-review item d0db195a72b0）────────────
        # 入参为空列表或全部条目落入规范化期 warning 跳过分支时 normalized
        # 为空：验收门零错误、kinds 空集，若放行到底会以 total=0 的全绿报告
        # 结算并写「验证完成」进度。上游防线（frozen contract 空集 aborted、
        # load_scenarios 拒非法）被绕过时（如直接构造 engine 调用）整轮验证
        # 会以全绿假象收场，此处兜底：复用验收失败同款出口产出 env_error
        # 报告，不结算为成功。
        if not normalized:
            msg = "场景集为空/全部条目无法解析（无可验证场景）"
            self.logger.error("verify_engine", msg)
            self._write_progress(0, len(normalized), msg)
            report = self._build_report([])
            report["env_error"] = msg
            self._save_report(report)
            return report

        # ── lazy setup：仅对场景集中实际出现的 kind 执行 ──
        kinds = {s.kind for s in normalized}
        setup_done: list[str] = []
        for kind in kinds:
            runner = self._runner_for(kind)
            try:
                await runner.setup()
            except Exception as e:
                # Runner setup 失败（如 ApiRunner 依赖缺失）＝验证环境错误，
                # 不判 bug-found（design D2：lazy setup 与资源纪律）。
                # 此处早退绕过了执行路径的 finally teardown，已完成 setup 的
                # Runner（如已启动浏览器的 WebRunner）须先 best-effort 释放，
                # 否则常驻 daemon 内每轮此类失败都泄漏一个浏览器实例。
                for done_kind in setup_done:
                    try:
                        await self._runners[done_kind].teardown()
                    except Exception as te:
                        self.logger.warning("verify_engine", f"Runner '{done_kind}' teardown 异常: {te}")
                # 失败 Runner 自身也纳入 best-effort：_runner_for 已把它构造并
                # memoize 进 self._runners，其 setup 可能已分配部分资源（如
                # WebRunner 已 await async_playwright().start() 启动 driver 进程
                # 后才在 chromium.launch 失败），不释放则常驻 daemon 内每轮
                # setup 失败都泄漏一份直至进程退出。teardown 对半初始化实例
                # 有空值守卫（BrowserManager.stop 逐步容错），残余异常由同款
                # try/except 兜底为 warning。
                try:
                    await runner.teardown()
                except Exception as te:
                    self.logger.warning("verify_engine", f"Runner '{kind}' teardown 异常: {te}")
                msg = f"验证环境错误: {kind} Runner 初始化失败: {e}"
                self.logger.error("verify_engine", msg)
                # 与验收失败路径对称：早退也落一条进度，覆盖上一轮残留的
                # 「验证完成」等陈旧内容，避免仪表盘与当轮实际状态不符
                # （code-review 6b80ad1277a0）。
                self._write_progress(0, len(normalized), msg)
                report = self._build_report([])
                report["env_error"] = msg
                self._save_report(report)
                return report
            setup_done.append(kind)

        # 执行起点进度（fix-verify-progress-granularity）：此前首个写点在批次
        # 完成，出题结束到首批 gather 完成之间进度文件不存在，进度条恒 0。
        self._write_progress(0, len(normalized), "开始执行")

        try:
            results = await self._execute_parallel(normalized)
            # ── 环境健全性门：场景结算后的统一后置分类（design D1）──
            # mock 环境断流时等待类超时整批假阴性，不能逐场景烧 token 重验。
            # 探针在该轮验证中只执行一次（首个候选场景触达即 memoize），
            # 候选场景按各自 kind 的探针结论结算：失联 → 降级 blocked-env。
            await self._post_classify_environment(normalized, results)
        finally:
            for kind in kinds:
                try:
                    await self._runners[kind].teardown()
                except Exception as e:
                    self.logger.warning("verify_engine", f"Runner '{kind}' teardown 异常: {e}")

        report = self._build_report(results)
        self._save_report(report)

        # 验证完成，进度更新到 100%
        total = report["summary"]["total"]
        self._write_progress(
            total,
            total,
            f"验证完成: {report['summary']['passed']}通过, "
            f"{report['summary']['failed']}失败, "
            f"{report['summary']['errors']}错误",
        )

        return report

    # ── 并行执行引擎 ───────────────────────────────────────────

    async def _execute_parallel(self, scenarios: list[TestScenario]) -> list[dict]:
        """按依赖关系分层，同层场景通过信号量控制的并发池并行执行。

        每个场景按 kind 分派给对应 Runner.execute（调度器零 kind 分支）。
        依赖失败传播（code-review c240f974ba21）：依赖场景终态为 fail/error
        时下游不再照常执行——合成 blocked-env 跳过结果（非产品归因），避免
        夹具链断裂在缺失夹具状态下级联出连锁伪失败。
        """
        semaphore = asyncio.Semaphore(self.max_parallel)
        results: list[dict] = []
        completed_ids: set[str] = set()
        # 终态为 fail/error 的场景 id（含被级联跳过者）：依赖失败传播判定源
        failed_ids: set[str] = set()
        remaining = list(scenarios)
        batch_num = 0
        done_count = 0  # 逐场景完成计数（fix-verify-progress-granularity）
        total = len(scenarios)

        while remaining:
            # 找出所有依赖已满足的场景
            ready = [s for s in remaining if all(dep in completed_ids for dep in s.depends_on)]

            # ── 依赖失败传播（code-review c240f974ba21）──────────────
            # completed_ids 只表达「已执行完」不区分成败：依赖场景（多为
            # seed/mock 夹具提供方）失败后，下游若照常执行会在夹具缺失
            # 状态下连锁失败，judge 易把连锁失败误归因为产品缺陷。此处把
            # 依赖失败的下游从本批摘出：不执行、直接合成 blocked-env 结果
            # （复用既有非产品归因状态——计入 warnings、judge 免失败分类
            # 强检、escalation 仅在全批无真实失败时才触发 inconclusive），
            # 并以 dependency_skipped/skipped_depends_on 标注级联来源；
            # 被跳过场景同样记入 failed_ids，使跨层级联（C→B→A）逐层传播。
            dep_skipped: list[tuple[TestScenario, list[str]]] = []
            runnable: list[TestScenario] = []
            for s in ready:
                broken = [dep for dep in s.depends_on if dep in failed_ids]
                if broken:
                    dep_skipped.append((s, broken))
                else:
                    runnable.append(s)

            for s, broken in dep_skipped:
                completed_ids.add(s.id)
                failed_ids.add(s.id)
                done_count += 1
                self._write_progress(
                    done_count, total, f"已完成 {done_count}/{total}（{s.id}，依赖失败跳过）"
                )
                self.logger.warning(
                    "verify_engine",
                    f"场景'{s.id}'依赖的场景失败（{', '.join(broken)}），"
                    f"跳过执行（依赖失败传播，非产品归因）",
                )
                results.append(
                    {
                        "scenario_id": s.id,
                        "description": s.description,
                        "kind": s.kind,
                        "status": "blocked-env",
                        "error": (
                            f"依赖场景失败，未执行: {', '.join(broken)}"
                            f"（依赖失败传播，非本场景产品缺陷）"
                        ),
                        "step_results": [],
                        "assertion_results": [],
                        "visual_results": [],
                        "screenshots": [],
                        "dependency_skipped": True,
                        "skipped_depends_on": broken,
                    }
                )

            if runnable:
                ready = runnable
            elif dep_skipped:
                # 本批全部为依赖失败跳过（进度与 completed_ids 均已推进），
                # 收紧 remaining 后回循环头重判下一批，不空烧批次号
                remaining = [s for s in remaining if s.id not in completed_ids]
                continue
            else:
                # 悬空依赖已在验收门打回，走到这里只剩真实循环依赖，
                # 直接全部执行兜底
                ready = remaining

            batch_num += 1
            self.logger.info(
                "verify_engine",
                f"📦 批次{batch_num}: 并行执行 {len(ready)} 个场景",
            )

            async def run_one(scenario: TestScenario) -> dict:
                nonlocal done_count
                async with semaphore:
                    try:
                        runner = self._runner_for(scenario.kind)
                        return await runner.execute(scenario)
                    finally:
                        # 逐场景完成即写进度（含异常路径，fix-verify-progress-granularity）：
                        # 批次级写点对无依赖场景集退化成「结尾一次性」（0→100% 跳变
                        # 根因 2）。事件循环单线程，done_count 递增与写文件间无 await。
                        done_count += 1
                        self._write_progress(
                            done_count, total, f"已完成 {done_count}/{total}（{scenario.id}）"
                        )

            batch_results = await asyncio.gather(
                *[run_one(s) for s in ready],
                return_exceptions=True,
            )

            for i, r in enumerate(batch_results):
                sid = ready[i].id
                completed_ids.add(sid)
                if isinstance(r, BaseException):  # 含 CancelledError，防异常对象漏进结果集
                    failed_ids.add(sid)
                    self.logger.error("verify_engine", f"场景'{sid}'异常: {r}")
                    results.append(
                        {
                            "scenario_id": sid,
                            "description": ready[i].description,
                            "kind": ready[i].kind,
                            "status": "error",
                            "error": repr(r),
                            "step_results": [],
                            "assertion_results": [],
                            "visual_results": [],
                            "screenshots": [],
                        }
                    )
                else:
                    # 依赖失败传播判定源：终态 fail/error 的 id 记入 failed_ids
                    # （warning 属非失败档，不阻断下游，与验收门语义一致）
                    if r.get("status") in TERMINAL_FAILURE_STATUSES:
                        failed_ids.add(sid)
                    results.append(r)

            # 批次收尾不再重复写进度：批次内每个场景的逐场景写点已覆盖

            remaining = [s for s in remaining if s.id not in completed_ids]

        return results

    # ── 状态判定（跨 kind 共用，design D3）──────────────────────

    def _determine_scenario_status(
        self,
        step_results: list[dict],
        assertion_results: list[dict],
        visual_results: list[dict],
    ) -> str:
        """判定场景整体状态（兼容访问点，委托 runner.determine_scenario_status）。"""
        return determine_scenario_status(step_results, assertion_results, visual_results)

    # ── 环境健全性门（design D1/D2）───────────────────────────

    async def _post_classify_environment(
        self, scenarios: list[TestScenario], results: list[dict]
    ) -> dict:
        """对全部场景结果做统一后置分类：候选场景 → 环境探针 → blocked-env。

        - 候选 = 场景 status==fail 且（mock_api 步骤 + 纯等待超时失败）。
        - 探针只跑一次（本方法入口即整轮验证的首次触达），结果 memoize 在
          self._env_probe，供候选场景共享。探针健康 → 维持 fail。
        - 探针失联 → 候选降级为 blocked-env（按各 kind 的探针结论逐组结算）。

        Returns:
            {"probe_healthy": bool, "blocked_env": int, "probe_detail": str}
        """
        candidates = [
            r
            for r in results
            if is_env_candidate(r)
            or is_connection_error_candidate(r)
            or is_blank_render_candidate(r)
        ]
        if not candidates:
            self._env_probe = {"healthy": True, "detail": "无候选场景，跳过探针"}
            return {
                "probe_healthy": True,
                "blocked_env": 0,
                "probe_detail": self._env_probe["detail"],
            }

        # 首个候选触达时执行探针（整轮一次）
        if not getattr(self, "_env_probe", None):
            self._env_probe = await self._run_environment_probe(candidates)

        probe = self._env_probe
        overall_healthy = bool(probe.get("healthy", True))
        per_kind = probe.get("per_kind") or {}
        blocked_env = 0
        for r in results:
            # 混合 kind 候选集按各自 kind 的探针结论结算（逐组套用，避免
            # 单一探针裁决全部候选）；该 kind 未单独探针时回落整轮汇总结论。
            kind_probe = per_kind.get(r.get("kind", "web"))
            healthy = (
                bool(kind_probe.get("healthy", True)) if kind_probe else overall_healthy
            )
            detail = (
                kind_probe.get("detail", "") if kind_probe else probe.get("detail", "")
            )
            effective = finalize_scenario_status(r, healthy)
            if effective == "blocked-env":
                r["status"] = "blocked-env"
                r["env_blocked"] = True
                r["env_probe_detail"] = detail
                blocked_env += 1

        self.logger.info(
            "verify_engine",
            f"环境健全性门: 候选={len(candidates)}, 探针={'健康' if overall_healthy else '失联'}, "
            f"blocked-env={blocked_env} — {probe.get('detail', '')}",
        )
        return {
            "probe_healthy": overall_healthy,
            "blocked_env": blocked_env,
            "probe_detail": probe.get("detail", ""),
        }

    async def _run_environment_probe(self, candidates: list[dict]) -> dict:
        """环境健全性探针：探针本体委托 Runner.probe_env（整轮一次）。

        按候选场景的 kind 分组分别探针（web 优先），各 kind 结论独立记录在
        per_kind，混合 kind 候选集互不套用对方结论（code-review d1441fc08f76）；
        汇总 detail 标注结论来源 kind 供 judge 判别。无 Runner 可探时（测试
        直连注入浏览器等回退路径）落回 _fallback_environment_probe。
        """
        kinds = []
        for c in candidates:
            k = c.get("kind", "web")
            if k not in kinds:
                kinds.append(k)
        kinds.sort(key=lambda k: 0 if k == "web" else 1)
        runners = getattr(self, "_runners", {})
        per_kind: dict = {}
        for kind in kinds:
            runner = runners.get(kind)
            if runner is None:
                continue
            sub = [c for c in candidates if c.get("kind", "web") == kind]
            per_kind[kind] = await runner.probe_env(sub)
        if not per_kind:
            return await self._fallback_environment_probe(candidates)
        # 汇总：overall 取各 kind 探针的合取（任一失联即整轮判失联的保守
        # 口径），per-kind 差异由 _post_classify_environment 精确套用。
        healthy = all(p.get("healthy", True) for p in per_kind.values())
        detail = "；".join(
            f"{kind} 探针: {p.get('detail', '')}".strip(": ").strip()
            for kind, p in per_kind.items()
        )
        return {"healthy": healthy, "detail": detail, "per_kind": per_kind}

    async def _fallback_environment_probe(self, candidates: list[dict]) -> dict:
        """回退探针（无 Runner 可探：测试直连注入浏览器等路径）。

        与 WebRunner.probe_env 同语义（HTTP 连通 + 推流检查），供引擎在
        无 web Runner 的兼容形态下保持既有行为。
        """
        base = getattr(self.browser, "base_url", "") if self.browser else ""
        detail = ""
        healthy = True
        if not base and self.project_root:
            base = locate_app_base_url(candidates)
        if base:
            # 线程池执行：probe_http_health 为同步阻塞探测（最坏 3×2s），避免卡死事件循环
            healthy = await asyncio.to_thread(probe_http_health, base, timeout=2.0)
            detail = f"HTTP 探测 {base}: {'连通' if healthy else '失联'}"
        if healthy and self.browser and getattr(self.browser, "is_extension_project", False):
            try:
                from .web_runner import _probe_web_push

                push_ok = await _probe_web_push(self.browser)
                healthy = healthy and push_ok
                detail += f"；推流{'正常' if push_ok else '中断'}"
            except Exception as e:
                self.logger.debug("verify_engine", f"推流检查不可用，跳过: {e}")
        return {"healthy": healthy, "detail": detail.strip("；")}

    def _locate_app_base_url(self, candidates: list[dict]) -> str:
        """从候选场景的 navigate 步骤定位被测应用入口（兼容访问点）。"""
        return locate_app_base_url(candidates)

    # ── 报告生成 ───────────────────────────────────────────────

    def _build_report(self, scenario_results: list[dict]) -> dict:
        """构建最终验证报告。"""
        total = len(scenario_results)
        passed = sum(1 for r in scenario_results if r["status"] == "pass")
        warnings = sum(1 for r in scenario_results if r["status"] == "warning")
        # 终态失败两档计数与依赖失败传播判定共用 TERMINAL_FAILURE_STATUSES
        # （code-review item 5867b3576e1f）：按序解包，第 1 位 fail、第 2 位 error
        failed, errors = (
            sum(1 for r in scenario_results if r["status"] == st)
            for st in TERMINAL_FAILURE_STATUSES
        )
        blocked_env = sum(1 for r in scenario_results if r["status"] == "blocked-env")

        # blocked-env 计入 warning 统计而非 fail（spec verify-environment-sanity-gate），
        # 并以独立 blocked_env 字段供放行门禁换算（旧 report 无该字段读为 0）。
        warnings += blocked_env

        return {
            "spec": self.spec_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # add-verify-parallel-backoff / design D3：所有轮都写有效并行度
            # （正常轮=配置值，降档轮=override 值），降档语义由值与配置值的差
            # + 启动日志降档标记承载，不新增布尔键。测试经 object.__new__
            # 轻量构造绕过 __init__ 时不带 max_parallel，容错回退配置默认 5。
            "effective_parallel": getattr(self, "max_parallel", 5),
            "summary": {
                "total": total,
                "passed": passed,
                "warnings": warnings,
                "failed": failed,
                "errors": errors,
                "blocked_env": blocked_env,
            },
            "scenarios": scenario_results,
        }

    def _write_progress(self, done: int, total: int, current: str):
        """写入实时进度文件，供仪表盘读取。

        与旧版 verifier agent 写入的格式兼容：
        {"total": N, "done": D, "current": "描述"}
        """
        progress_path = self.project_root / ".fenix" / "verify-progress" / f"{self.spec_name}.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress = {
            "total": total,
            "done": done,
            "current": current,
        }
        # 原子写（code-review item 4897aa6ba94f，对齐 regression._atomic_write
        # 的 mkstemp+os.replace 范式）：进度文件随每个场景完成高频重写，裸
        # open("w") 原地截断会让并发读取侧（dashboard/质量门）读到半截 JSON。
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{progress_path.name}.", suffix=".tmp", dir=str(progress_path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(progress, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, progress_path)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception as e:
            self.logger.debug("verify_engine", f"进度文件写入失败（非致命）: {e}")

    def _save_report(self, report: dict):
        """将报告写入磁盘（mkstemp+os.replace 原子替换，防并发读侧撕裂）。

        写盘失败不向调用方抛出（code-review item 94bb0ab6bda3）：调用时全部
        场景已执行完、teardown 已完成，结果只存在于传入的 report 对象，异常
        穿出 run() 会把整轮验证结果替换成未捕获异常（验收失败早退路径还会把
        「打回 plan」通道变成 run 崩溃）。容错口径对齐 _write_progress：
        记日志留痕，保证 run() 恒返回报告对象。
        """
        try:
            report_dir = self.project_root / ".fenix" / "verify-progress" / self.spec_name
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / "report.json"
            # 原子写（code-review item 4897aa6ba94f，同 _write_progress）
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{report_path.name}.", suffix=".tmp", dir=str(report_dir)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, report_path)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception as e:
            self.logger.error(
                "verify_engine",
                f"报告写盘失败（非致命，本轮结果仅在内存中，未落 report.json）: {e}",
            )
            return
        self.logger.info(
            "verify_engine",
            f"📊 报告已保存: {report_path}",
        )
