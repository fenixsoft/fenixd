"""verification.py — VerificationPipeline：三阶段+legacy 验证/场景冻结/交互契约/verdict 证据分类/交付物门/env blocked 处理/验证门与告警 streak（refactor-core-packages 阶段 5）。

SPEC 状态经门面回引 self._pm.state_machine（design D3 规则 3）；本轮缓存态
_last_scenario_diff / _last_interaction_contract 随组件同迁（design D3 规则 1），
门面经 property 委托保持原路径可用。

"""

from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request

from core.serving_registry import ServingRegistry
from core.proc_utils import find_free_port

# judge-scenario-repair：judge 原地场景修复预算（上限重入轮数）。
# 场景文件自身缺陷（夹具未自建/步骤客观错误/依赖序缺失）由 judge 原地修复
# 后重执行，不再「env 伪失败→原样重验」空转；上限与阶段1 replan_left 对齐。
_SCENARIO_REPAIR_MAX_ROUNDS = 2

from core.verify_contract import (
    CommandVerifyServer,
    ensure_main_tree_deps,
    entry_preflight_error,
    load_verify_contract,
    probe_ready,
    provision_worktree_node_modules,
    resolve_deps_mode,
    rewrite_scenarios_origin,
    run_prepare_steps,
    StaticVerifyServer,
)

# fix-verdict-read-failclosed D3：与 runner 产物硬门共用同一 status 白名单单一来源
# （prompt_builder 定义、两侧 import，避免双实现漂移）。
from core.agent_runner.prompt_builder import planner_result_status_whitelist
# fix-verdict-retry-misattribution D3：frozen 门 error 文案与 runner.py 派发门共用
# 同一导出常量（防文案改动使匹配失效），取消判定沿用 AgentRunResult.cancelled 结构化
# 字段（非字符串匹配）。
from core.agent_runner.runner import FROZEN_TERMINATED_ERROR_PREFIX
# add-blocked-reverify-lane D3：env 阻塞轮次计数清零点收敛后与 state_machine
# 共用同一字段常量（防字符串漂移；唯一清零点=verified 落定与 unfreeze_spec）。
from core.state_machine import ENV_BLOCK_ROUNDS_FIELD, FREEZE_ERROR_PREFIX


class VerdictReadResult:
    """verdict 结果文件读取三态结果（fix-verdict-read-failclosed D4）。

    - ok=True  → status 为白名单内合法裁决（verified/bug-found/plan-ready/
      scenario-repaired）。
    - ok=False → 结果文件**不可读**（missing/parse/unknown-status/foreign-stamp），
      reason 归因、detail 附解析错误原文。不可读**绝不**等价于 verified——历史
      add-verify-contract-autodraft 事故：summary 裸换行致非法 JSON → 读侧按
      None 处理 → else 分支 → verified → done → auto-push。
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
        return (
            f"<VerdictReadResult unreadable reason={self.reason} "
            f"detail={self.detail!r}>"
        )

# 探针通过后的静置秒数（_finalize_static）：吸收冷实例后端收尾/前端首帧的
# 长尾，再放行开跑场景（add-spec-hooks 白屏 env 事故第三道纵深，2026-09-06）。
POST_READY_SETTLE_SECONDS = 10


class VerificationPipeline:
    """验证流水线组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    def _read_verify_report(self, spec_name: str) -> dict:
        """读取 verify-progress/<spec>/report.json（尽力解析，失败返回空 dict）。"""
        path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "report.json"
        )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


    def _handle_env_blocked_inconclusive(self, spec_name: str, report: dict) -> bool:
        """环境性失联门禁：全批 blocked-env → inconclusive → 保持 testing 重派新 attempt。

        inconclusive 判据（design D2）：summary.blocked_env > 0 且有效失败
        （failed + errors）为 0，即该轮原始失败全部为 blocked-env。

        处理：spec 回 implemented（verifier 派发门禁要求）→ 排队重验新 attempt；
        **不向 admin store 发 repeated_failures 信号**——本方法不产生 error 终态
        run 产物，repeated_failures 检测天然不累积（连续 inconclusive 不唤醒
        Administrator，对应 spec Scenario）。

        重验上限沿用 attempts=3（verify_engine.inconclusive_max_attempts 可调）：
        连续超限后停止自动重验、保持 implemented 并写 error 暴露，由
        admin_monitor stuck 检测唤起人工，不再无界自动重验。

        Returns:
            True 表示本轮已按 inconclusive 处理（调用方跳过 bug-found/verified
            判定）；False 表示无环境性失联，按既有判定继续。
        """
        summary = report.get("summary") or {}
        blocked_env = int(summary.get("blocked_env", 0) or 0)
        failed = int(summary.get("failed", 0) or 0)
        errors = int(summary.get("errors", 0) or 0)
        spec = self._pm.state_machine.read_one(spec_name) or {}
        if blocked_env <= 0 or (failed + errors) > 0:
            # add-verify-parallel-backoff / design D2：非 inconclusive 判定即
            # 健康轮（出现真实 verdict），复位降档并行度——存在才清，避免每轮
            # 无谓写盘（与 _inconclusive_attempts 同生命周期：链条断即复位）。
            if "_verify_parallel_override" in spec:
                self._pm.state_machine.update_spec(spec_name, {
                    "_verify_parallel_override": None,
                })
            return False

        try:
            attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        max_attempts = int(
            self._pm._get_config("verify_engine.inconclusive_max_attempts", 3) or 3
        )
        escalate_attempts = int(
            self._pm._get_config(
                "verify_engine.inconclusive_escalate_attempts", 4) or 4
        )

        # ── B7 升级通道（add-verdict-credibility-gate / design D6）──
        # 连续计数达到升级阈值（缺省 4）：向 admin store 写 kind=SIGNAL 记录，
        # 经 admin_monitor 摄取唤起 Administrator。三层既有检测口径
        # （repeated_failures / stuck / blocked_stuck）均实证错过该故障形态，
        # 不可依赖它们。写入后停止自动重验：计数不清零则 recovery（B6）保持
        # 跳过，人工处置是唯一出路——与「暂停自动重验」语义闭环。
        if attempts >= escalate_attempts:
            self._write_inconclusive_loop_signal(
                spec_name, attempts, blocked_env, report)
            self._pm.logger.error(
                "pm_engine",
                f"'{spec_name}' 连续 {attempts} 轮验证全部 blocked-env，"
                f"已达升级阈值 {escalate_attempts}，SIGNAL 已写 admin store，"
                f"暂停自动重验等待人工处置",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "status": "implemented",
                "tester_run": None,
                "error": (f"连续 {attempts} 轮验证全部环境性失联（blocked-env），"
                          f"已呼叫 Administrator 核查验证环境；"
                          f"人工处置后需清 _inconclusive_attempts 才能恢复自动重验"),
                "_inconclusive_attempts": attempts,
                "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
            })
            return True

        if attempts < max_attempts:
            self._pm.logger.warning(
                "pm_engine",
                f"'{spec_name}' 本轮 {blocked_env} 个失败场景全部为 blocked-env"
                f"（环境性失联），verdict=inconclusive，第 {attempts}/{max_attempts} 次重验",
            )
            updates = {
                "status": "implemented",
                "tester_run": None,
                "error": (f"环境性失联：{blocked_env} 个失败场景均 blocked-env，"
                          f"第 {attempts}/{max_attempts} 次重验（inconclusive 不判 fail）"),
                "_inconclusive_attempts": attempts,
            }
            # add-verify-parallel-backoff / design D1：连续 blocked-env 重验按
            # attempt 递减有效并行度——attempts≥2 起降档（配置值逐轮减半向下
            # 取整、下限 1），首轮不降档（白屏证据尚不存在，降档会冤枉健康
            # 环境）。下一轮 VerifyEngine 构造时读取覆盖 max_parallel。
            if attempts >= 2:
                base = int(
                    self._pm._get_config("verify_engine.max_parallel", 5) or 5
                )
                updates["_verify_parallel_override"] = max(1, base >> (attempts - 1))
            self._pm.state_machine.update_spec(spec_name, updates)
            self._pm._enqueue(spec_name, "verifier")
            return True

        # 连续 ≥max_attempts 轮全部环境性失联：停止自动重验，暴露错误等待人工。
        # 置 _dispatch_backoff_until 吸收同状态 update 触发的即时重派振荡。
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' 连续 {attempts} 轮验证全部 blocked-env，"
            f"疑为 mock/SSE 推送环境故障，暂停自动重验",
        )
        self._pm.state_machine.update_spec(spec_name, {
            "status": "implemented",
            "tester_run": None,
            "error": (f"连续 {attempts} 轮验证全部环境性失联（blocked-env），"
                      f"请人工检查 mock/SSE 推送环境；不产生 bug-found 信号"),
            "_inconclusive_attempts": attempts,
            "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
        })
        return True

    def _write_inconclusive_loop_signal(
        self, spec_name: str, attempts: int, blocked_env: int, report: dict,
    ) -> bool:
        """向 admin store 写 inconclusive_loop SIGNAL（design D6 / Task 5.2）。

        连续 blocked-env 达升级阈值时调用：kind=SIGNAL，type=inconclusive_loop，
        附 spec 名、连续轮数、末轮 blocked_env 数、最近实例探针摘要。admin_monitor
        _detect_family_explosion 摄取后按既有 SIGNAL 通道唤起 Administrator。

        写失败静默降级（信号只是升级通道，spec 的 error 字段已承载人工可见信息），
        返回是否写入成功。
        """
        # 最近实例探针摘要：末轮 blocked-env 场景的 env_probe_detail 里取第一条
        probe_detail = ""
        for sc in (report.get("scenarios") or []):
            if not isinstance(sc, dict):
                continue
            if sc.get("status") != "blocked-env":
                continue
            probe_detail = str(sc.get("env_probe_detail") or "").strip()
            if probe_detail:
                break
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self._pm.project_root, self._pm.logger)
        try:
            store.append({
                "kind": SIGNAL,
                "signal_type": "inconclusive_loop",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    f"'{spec_name}' 连续 {attempts} 轮验证全部为 blocked-env"
                    f"（环境性失联），已达升级阈值，请 Administrator 核查验证环境"
                ),
                "evidence": (
                    f"spec={spec_name}; 连续轮数={attempts}; "
                    f"末轮blocked_env数={blocked_env}; "
                    f"探针摘要={probe_detail or '无'}"
                ),
                "recommended_action": (
                    "验证环境核查清单：① 被测实例是否就绪（serve/start 命令与端口）；"
                    "② 资源与并行度（max_parallel 是否挤爆实例）；"
                    "③ mock+SSE 链路（mock_api 是否误拦推流、SSE 是否断流）；"
                    "④ 探针摘要（见 evidence）。恢复路径：人工处置后解冻 spec "
                    "（unfreeze）并清 `_inconclusive_attempts`，后续 blocked-env "
                    "轮次从 1 重新计数"
                ),
            })
            return True
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"inconclusive_loop 信号写入失败 '{spec_name}': {e}",
            )
            return False

    def _speculative_bug_found_gate(self, spec_name: str) -> bool:
        """归因分级门禁（add-verdict-credibility-gate / design D2 / Task 2.2）。

        在 bug-found 打回决定前调用：读取 report.json（judge 已增强），框架侧
        机械计算 attribution_level，白屏方向约束强制改写分类，然后判断打回
        依据是否全部为推测级（speculative）——是则抑制 bug-found：
          - 门禁预算内（verify_engine.credibility_gate_max_retries，缺省 1）：
            回 implemented 转重验一次，不向 implementer 带推测信号打回；
          - 预算耗尽：blocked + 告警（attribution_evidence_insufficient），
            交人工复核。

        Returns:
            True 表示已按门禁处置（调用方应 return，不推进 bug-found）；
            False 表示归因有证据支撑（或门禁异常降级不阻断），按既有流程推进。
        """
        try:
            from core.verdict_check import (
                validate_attribution_levels, should_suppress_bug_found,
                enforce_blank_screenshot_direction,
                load_report as _load_gate_report,
            )
            gate_report = _load_gate_report(self._pm.project_root, spec_name)
            if gate_report is None:
                return False  # 无 report.json，门禁无对象可判，不阻断
            validate_attribution_levels(gate_report)
            for _sc in gate_report.get("scenarios") or []:
                if isinstance(_sc, dict):
                    _new_cls = enforce_blank_screenshot_direction(_sc)
                    if _new_cls:
                        _sc["classification"] = _new_cls
                        _sc["blank_direction_forced"] = True
            if not should_suppress_bug_found(gate_report):
                # 清空门禁计数：本轮未触发（有证据支撑的归因，不记入 speculative 统计）
                spec_data = self._pm.state_machine.read_one(spec_name) or {}
                if spec_data.get("_credibility_gate_attempts"):
                    try:
                        self._pm.state_machine.update_spec(spec_name, {
                            "_credibility_gate_attempts": 0,
                        })
                    except Exception:
                        pass
                return False

            max_retries = int(
                self._pm._get_config(
                    "verify_engine.credibility_gate_max_retries", 1
                ) or 1
            )
            spec = self._pm.state_machine.read_one(spec_name) or {}
            gate_attempts = int(spec.get("_credibility_gate_attempts", 0) or 0)
            if gate_attempts < max_retries:
                self._pm.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' 打回归因全部为 speculative（推测级），"
                    f"抑制 bug-found——转重验一次"
                    f"（第 {gate_attempts + 1}/{max_retries} 次）",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "implemented",
                    "tester_run": None,
                    "error": (
                        f"归因证据不足待人工复核：全部驱动场景归因"
                        f"为推测级（speculative），已抑制 bug-found "
                        f"打回并重验一次（第 {gate_attempts + 1}/"
                        f"{max_retries} 次）"
                    ),
                    "_credibility_gate_attempts": gate_attempts + 1,
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：计数清零处同步清
                    # 降档并行度（_inconclusive_attempts 同生命周期）。
                    "_verify_parallel_override": None,
                })
                self._pm._enqueue(spec_name, "verifier")
                return True

            # 重试预算已耗尽：阻断为 blocked + 告警（交人工复核）
            self._pm.logger.error(
                "pm_engine",
                f"'{spec_name}' 归因证据不足待人工复核：连续 "
                f"{gate_attempts} 次推测级归因，门禁预算耗尽，"
                f"阻断为 blocked",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "status": "blocked",
                "error": (
                    f"归因证据不足待人工复核：全部驱动场景归因"
                    f"连续 {gate_attempts} 次为推测级（speculative），"
                    f"门禁重试预算耗尽，已 blocked 等待人工裁决"
                ),
            })
            self._pm._send_human_escalation_alert(
                spec_name=spec_name,
                signal_type="attribution_evidence_insufficient",
                severity="major",
                description=(
                    f"'{spec_name}' 验证归因证据不足待人工复核："
                    f"连续 {gate_attempts} 次驱动场景归因均为推测级"
                    f"（speculative），门禁已 blocked 等待人工裁决"
                ),
                evidence=(
                    f"spec={spec_name}; max_retries={max_retries}; "
                    f"连续推测轮数={gate_attempts}"
                ),
                recommended_action=(
                    "人工核验验证场景与失败断言：若为真·产品缺陷请"
                    "在 triage_violations.json 标注后重派 verify；"
                    "若为场景缺陷请退回 plan 修复场景"
                ),
            )
            return True
        except Exception as e:
            # 门禁自身异常不阻断既有裁决（治理代码是附加治理，框架级门禁
            # 崩溃按「不阻断」退化——judge 正常裁决继续，避免附加治理代码
            # 成为新单点故障）
            self._pm.logger.warning(
                "pm_engine",
                f"门禁校验异常跳过（不阻断裁决）'{spec_name}': "
                f"{type(e).__name__}: {e}",
            )
            return False


    def _serve_static_in_main(self, contract, scenarios_path) -> tuple:
        """方案 1（默认）：主树构建 + 主树起服务。同 root 复用已启动实例。"""
        root_dir = Path(self._pm.project_root) / contract.serve.root
        if not root_dir.is_dir():
            return False, False, f"验证契约 serve.root 不存在: {contract.serve.root}"
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        srv = cache.get("main")
        if srv is None or srv.root != root_dir.resolve():
            if srv is not None:
                srv.stop()
            srv = StaticVerifyServer(root_dir)
            cache["main"] = srv
        return self._finalize_static(srv, contract, scenarios_path, "主树")

    def _ensure_serving_worktree(self, spec_name: str, contract, mode: str):
        """serving worktree 供给（static/command 两型共享）。

        HEAD 未变且目录存活时复用；否则停掉旧实例、重建 worktree、provision
        依赖（deps_mode）并执行契约 prepare（构建产物）。

        Returns:
            (wt_path, head, err)：wt_path=None 时 err 为人类可读原因。
            server 生命周期（启动/复用/停止）由调用方按 mode 管理。
        """
        serve_root = Path(self._pm.project_root) / ".fenix" / "verify-serving"
        serve_root.mkdir(parents=True, exist_ok=True)
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        head = subprocess.run(
            ["git", "-C", str(self._pm.project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        old = cache.get(spec_name)
        if (old is not None and old.get("head") == head
                and old.get("mode") == mode
                and Path(old["wt_path"]).is_dir()):
            return old["wt_path"], head, None
        if old is not None:
            # verify-process-lifecycle D6：command 型旧实例 HEAD 变更前先移除登记
            old_server = old.get("server")
            if isinstance(old_server, CommandVerifyServer):
                self._unregister_serving_instance(spec_name, old_server)
            try:
                old_server.stop()
            except Exception:
                pass
            self._remove_serving_worktree(old["wt_path"])
        wt = serve_root / f"{spec_name}-{int(time.time())}"
        r = subprocess.run(
            ["git", "-C", str(self._pm.project_root),
             "worktree", "add", "--detach", str(wt), "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return None, None, (
                "验证 worktree 创建失败: "
                f"{(r.stderr or r.stdout).strip()[-200:]}")
        provision_worktree_node_modules(
            wt, self._pm.project_root,
            sorted({(s.cwd or ".") for s in contract.prepare}),
            mode=resolve_deps_mode(
                contract, self._pm._get_config("verify.deps_mode", "")),
            logger=self._pm.logger,
        )
        err = run_prepare_steps(contract, wt)
        if err:
            self._remove_serving_worktree(wt)
            return None, None, f"验证契约 prepare 失败（worktree 内）: {err}"
        return str(wt), head, None

    def _serve_static_in_worktree(self, spec_name, contract, scenarios_path) -> tuple:
        """方案 2：专用 serving worktree 内构建 + 起静态服务（隔离主树运行实例）。

        worktree 每次 HEAD 变化时重建（分离 HEAD、自管理生命周期，位于
        .fenix/verify-serving/，gitignore 排除）；HEAD 未变时复用已启动实例
        与产物（replan 循环不重复构建）。
        """
        wt, head, err = self._ensure_serving_worktree(
            spec_name, contract, mode="static")
        if wt is None:
            return False, False, err
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        old = cache.get(spec_name)
        if (old is not None and old.get("mode") == "static"
                and old.get("head") == head
                and isinstance(old.get("server"), StaticVerifyServer)):
            return self._finalize_static(
                old["server"], contract, scenarios_path, "验证 worktree（复用）")
        root_dir = Path(wt) / contract.serve.root
        if not root_dir.is_dir():
            self._remove_serving_worktree(wt)
            return False, False, f"验证契约 serve.root 不存在: {contract.serve.root}"
        cache[spec_name] = {
            "server": StaticVerifyServer(root_dir), "wt_path": wt, "head": head,
            "mode": "static",
        }
        return self._finalize_static(
            cache[spec_name]["server"], contract, scenarios_path, "验证 worktree")

    @staticmethod
    def _port_responds(port: int) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{port}/",
                        headers={"User-Agent": "fenix-verify-probe"}),
                    timeout=1.0):
                return True
        except Exception:
            return False

    def _serve_command_in_worktree(self, spec_name, contract, scenarios_path) -> tuple:
        """命令型被测实例的 worktree 隔离（serve.kind=command + static_scope=worktree）。

        full-stack 验证的解法：serving worktree 内 prepare 构建产物，再以
        worktree 为 cwd 启动 serve.cmd——后端 API 与前端产物同为本次 HEAD 的
        真实形态（static 模式无 API，交付物端点被迫 mock＝假阴性放大器）。
        端口注入（与 static 模式「框架分配、实例消费」同范式）：启动前分配
        空闲端口，经 {port} 占位符替换 + FENIX_VERIFY_PORT 环境变量双通道
        注入——实例永不与既有实例（主树常驻实例等）争抢端口；未消费注入的
        存量契约由 CommandVerifyServer 进程归属/邻近扫描兜底发现。HEAD 未变
        时复用已启动实例。
        """
        wt, head, err = self._ensure_serving_worktree(
            spec_name, contract, mode="command")
        if wt is None:
            return False, False, err
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        old = cache.get(spec_name)
        if (old is not None and old.get("mode") == "command"
                and old.get("head") == head
                and isinstance(old.get("server"), CommandVerifyServer)
                and old["server"].ok):
            return self._finalize_static(
                old["server"], contract, scenarios_path, "命令 worktree（复用）")
        port = find_free_port()
        # legacy 兜底参数：邻近扫描基准（serve.port 或 cmd 内端口数字）与
        # 启动前监听快照（跳过既有实例端口）；cmd 引用 {port} 后两者皆不需要
        import re as _re
        m = _re.search(r"(?:--port|-p)\s+(\d+)", contract.serve.cmd or "")
        legacy_hint = contract.serve.port or (int(m.group(1)) if m else None)
        pre = ({p for p in range(legacy_hint, legacy_hint + 51)
                if self._port_responds(p)} if legacy_hint else set())
        # 入口存在性预检（design D1）：{port} 替换前的原 cmd 检查（{port} 不在
        # 路径段）；入口文件不存在 → fail-fast，不 spawn、不跑场景，场景执行数=0。
        orig_cmd = contract.serve.cmd or ""
        preflight_err = entry_preflight_error(orig_cmd, Path(wt))
        if preflight_err:
            self._write_verify_contract_missing(
                spec_name,
                f"{preflight_err}（入口存在性预检失败，spawn 前 fail-fast）",
                f"serve.cmd 原文={orig_cmd!r}; cwd={wt}",
                recommended_action=(
                    "Administrator 修正 .fenix/verify.yaml serve.cmd 入口路径："
                    "按错误信息中「候选」提示修正，或确认构建产物已生成后重验"),
            )
            return False, False, preflight_err
        cmd_str = orig_cmd.replace("{port}", str(port))
        env = {**os.environ, "FENIX_VERIFY_PORT": str(port)}
        # design D3：worktree 路径同样落盘 boot.log（非 DEVNULL 吞掉），
        # 启动即死错误证据经 CommandVerifyServer 句柄关闭前可读。
        boot_log = self._open_boot_log(spec_name)
        try:
            proc = subprocess.Popen(
                cmd_str, shell=True, cwd=str(wt),
                stdout=boot_log, stderr=boot_log,
                start_new_session=True, env=env,
            )
        except Exception as e:
            boot_log.close()
            return False, False, f"验证命令实例启动失败: {e}"
        srv = CommandVerifyServer(
            proc, port, timeout=contract.ready.timeout or 60,
            legacy_hint=legacy_hint, legacy_pre=pre, boot_log=boot_log)
        if not srv.ok:
            # 启动即死：boot.log 尾部附入失败描述（Cannot find module 等）
            boot_tail = self._read_boot_log_tail(spec_name, boot_log)
            srv.stop()
            return False, False, (
                (srv.failure_note or "验证命令实例未就绪（注入端口未被消费）")
                + boot_tail)
        cache[spec_name] = {
            "server": srv, "wt_path": wt, "head": head, "mode": "command",
        }
        # verify-process-lifecycle D6：command 型实例创建时登记
        # （pid/port/spec/worktree），终局/周期清扫按 liveness 收割。
        self._register_serving_instance(spec_name, srv, wt_path=wt)
        return self._finalize_static(
            srv, contract, scenarios_path, "命令 worktree")

    def _finalize_static(self, srv, contract, scenarios_path, scope_label) -> tuple:
        """BASE_URL 注入 + 就绪探针：static 两类 scope 的共同收尾。

        探针通过后静置 ``POST_READY_SETTLE_SECONDS`` 再放行开跑场景：探针
        语义只保证「探针路径此刻可达」，冷实例的后端收尾/前端首帧渲染仍有
        长尾（add-spec-hooks 第 1 轮 4 个 web 场景白屏 env 事故——探针通过
        与场景开跑同一秒）。与 browser 首帧渲染等待、探针鉴别力自检同层，
        白屏防复发第三道纵深。用户指令 2026-09-06。
        """
        n = rewrite_scenarios_origin(scenarios_path, srv.base_url)
        ok, probe_note = probe_ready(srv.base_url, contract.ready)
        if not ok:
            note = (f"验证契约 static[{scope_label}]: 被测实例 {srv.base_url}"
                    f"（场景 origin 改写 {n} 处）— {probe_note}")
            return (False, False, note)
        time.sleep(POST_READY_SETTLE_SECONDS)
        note = (f"验证契约 static[{scope_label}]: 被测实例 {srv.base_url}"
                f"（场景 origin 改写 {n} 处，探针通过后静置 "
                f"{POST_READY_SETTLE_SECONDS}s）— {probe_note}")
        return (True, False, note)

    def _remove_serving_worktree(self, wt_path) -> None:
        subprocess.run(
            ["git", "-C", str(self._pm.project_root),
             "worktree", "remove", "--force", str(wt_path)],
            capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(self._pm.project_root), "worktree", "prune"],
            capture_output=True, timeout=15,
        )

    # ── 被测实例登记制（verify-process-lifecycle D6）─────────────────
    # serve.kind=command 与 _ensure_app_reachable 兜底 spawn 的实例创建时
    # 向 .fenix/verify-serving/servers.json 登记（pid/port/spec/worktree），
    # 停止时移除；spec 终局与 daemon 周期清扫按 /proc liveness 收割。

    def _register_serving_instance(self, spec_name: str, server,
                                   wt_path=None, hint_port=None) -> None:
        """command 型实例创建时登记。幂等：同 (pid,spec) 已登记则跳过。"""
        try:
            port = getattr(server, "port", None) or hint_port or 0
            ServingRegistry(self._pm.project_root, self._pm.logger).register(
                server.pid, port, spec_name, wt_path or "")
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"serving 实例登记失败 '{spec_name}'（非阻塞）: {e}")

    def _unregister_serving_instance(self, spec_name: str, server) -> None:
        """command 型实例停止时移除登记。幂等：无匹配条目安全空转。"""
        try:
            ServingRegistry(self._pm.project_root, self._pm.logger).remove(
                server.pid, spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"serving 实例登记移除失败 '{spec_name}'（非阻塞）: {e}")

    def _evict_spec_serving(self, spec_name: str) -> None:
        """spec 终局（done/verified）后回收其被测实例并驱逐缓存。

        command 型：stop 进程 + 移除 servers.json 登记 + 移除 serving worktree；
        static 型：stop 实例。幂等：无缓存条目/无登记时安全空转。
        主树 static 共享实例（缓存键 "main"）不在此列（多 spec 共享，保留）。
        """
        cache = self.__dict__.get("_contract_static_servers", {})
        old = cache.pop(spec_name, None)
        if old is None:
            return
        server = old.get("server")
        try:
            if server is not None and hasattr(server, "pid"):
                # 登记过的实例（CommandVerifyServer 或兜底 spawn Popen）同步移除
                self._unregister_serving_instance(spec_name, server)
            if server is not None and getattr(server, "ok", True):
                server.stop()
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"spec 终局实例回收失败 '{spec_name}'（非阻塞）: {e}")
        wt = old.get("wt_path")
        if wt:
            self._remove_serving_worktree(wt)

    def _current_instance_base_url(self, spec_name: str) -> str:
        """本轮被测实例的 base_url（契约统一供给，引擎分发给各 Runner）。

        取代旧「从候选场景 navigate 步骤文本正则考古 base_url」的回退逻辑
        （该逻辑在场景失联时会漏判）：serve 流程已确定实例地址，直接取。

        优先级：
          1. ``_contract_static_servers`` 缓存中的 server.base_url
             （契约 static/command 两型：worktree 作用域键=spec_name、
             主树 static 共享实例键="main"）；
          2. 无契约兜底 spawn（commands.start）时查 serving 登记；
          3. 均无 → 空串（引擎/web runner 落回 navigate 考古，api runner
             无实例形态探针保守健康）。
        """
        cache = self.__dict__.get("_contract_static_servers", {})
        for key in (spec_name, "main"):
            entry = cache.get(key)
            if entry is None:
                continue
            srv = entry.get("server") if isinstance(entry, dict) else entry
            if srv is not None and getattr(srv, "base_url", ""):
                # verify-process-lifecycle D6 配套：缓存实例可能已被
                # serving_registry 周期清扫收割（spec 轮间回 implementing 时
                # 「无在飞 spec」即杀进程）——对已死实例不得当作现存可达
                # 实例返回，否则契约轻量自证/探针探死端口永久失败，
                # 环境死循环（fix-dashboard-fault-isolation 实证）。
                # StaticVerifyServer 无 ok 属性（线程驻留），getattr 默认
                # True 保持原行为；CommandVerifyServer.ok 含进程 liveness。
                if not getattr(srv, "ok", True):
                    continue
                return srv.base_url
        # 兜底 spawn（commands.start，无契约）：serving 登记里的端口
        try:
            reg = ServingRegistry(self._pm.project_root, self._pm.logger).entries()
            for e in (reg or []):
                if isinstance(e, dict) and e.get("spec") == spec_name and e.get("port"):
                    return f"http://127.0.0.1:{e['port']}"
        except Exception:
            pass
        return ""

    def _ensure_app_reachable(self, spec_name: str) -> tuple:
        """验证前确保应用可达：自动启动 commands.start、处理端口冲突。

        最终用户验证为必选项：场景执行前先保证应用可被浏览器访问；
        若不可达则自动启动服务（commands.start），端口冲突时换端口重试
        （改写场景 URL）。仅在「需用户参与（如收验证码/登录）」或
        「判定无法解决」时才返回不可达，由上层判定而非静默通过。

        Returns:
            (reachable, user_blocked, note)
            - reachable: 自愈后应用是否可达
            - user_blocked: 是否为需用户参与而无法自动验证（预留判定位）
            - note: 人类可读说明（供错误展示）
        """
        scenarios_path = (self._pm.project_root / ".fenix" / "verify-progress"
                          / spec_name / "test_scenarios.json")
        if not scenarios_path.exists():
            return True, False, ""
        try:
            data = json.loads(scenarios_path.read_text(encoding="utf-8"))
        except Exception:
            return True, False, ""

        # ── 契约形态按场景集反推（verify-runner-engine D4：serve/ready 必要性
        # 由场景集 kind 组成决定，零新增字段）──
        # 纯 cli 场景集：serve/ready 全省（不回退 commands.start——无人消费的
        # 实例不拉起）；契约 prepare 仍执行（构建/命令可用性是唯一环境门）。
        # 含 web/api 场景：serve（或 commands.start 兜底）必须有效，缺失时
        # 下方报明确错误打回 plan。
        kinds = {str(sc.get("kind", "web")) for sc in data if isinstance(sc, dict)}
        if kinds and kinds <= {"cli"}:
            contract = load_verify_contract(self._pm.project_root, self._pm.logger)
            if contract is not None and contract.prepare:
                # 纯 cli 无实例形态：不建 serving worktree，prepare 在主树执行
                # （add-main-tree-deps-provision：主树 prepare 前按 prepare cwd
                # 集合预装依赖，防 add-ssh-foundation 事故 exit 127 复发；本 SPEC
                # 入口预检在其后的 spawn 点——顺序：供给 → prepare → 预检 → spawn。）
                ensure_main_tree_deps(
                    self._pm.project_root,
                    sorted({(s.cwd or ".") for s in contract.prepare}),
                    mode=resolve_deps_mode(
                        contract, self._pm._get_config("verify.deps_mode", "")),
                    logger=self._pm.logger,
                )
                err = run_prepare_steps(contract, self._pm.project_root)
                if err:
                    return False, False, f"验证契约 prepare 失败: {err}"
            return True, False, "纯 cli 场景集，跳过 serve/ready（无实例形态）"
        if not kinds:
            return True, False, ""

        # 收集场景实例入口 URL（web navigate / api http_request、sse_connect）
        urls: list[str] = []
        for sc in (data if isinstance(data, list) else []):
            if not isinstance(sc, dict):
                continue
            for step in sc.get("steps", []) or []:
                if not isinstance(step, dict):
                    continue
                action = step.get("action")
                if action == "navigate":
                    # navigate 目标 URL 存于 value（见 scenarios.TestStep）：191 个场景
                    # 全部用 value 携带链接，target/url 为空。旧代码读 url/target 导致
                    # urls 恒空，_ensure_app_reachable 恒判可达，可达性门禁永不触发。
                    u = str(step.get("value") or step.get("url") or step.get("target") or "")
                elif action in ("http_request", "sse_connect"):
                    # api 场景打同一实例（BASE_URL 铁律扩展：URL origin 全量改写），
                    # 入口 URL 同样参与可达性探测
                    u = str(step.get("url") or "")
                else:
                    continue
                if u.startswith("http") and u not in urls:
                    urls.append(u)

        # ── 声明式验证契约（.fenix/verify.yaml，字段语义见 verify_contract.py）──
        # 场景必须打「被测实现 fresh 构建出的可运行形态」。契约存在时：prepare
        # 重建产物 → static 无条件新鲜服务 + 场景 origin 全量改写（下方「已可达
        # 即跳过」捷径对构建型应用＝陈旧产物陷阱，契约 static 模式禁用）→ ready
        # 探针放行。契约缺失时维持 commands.start 旧行为（存量项目零迁移）。
        contract = load_verify_contract(self._pm.project_root, self._pm.logger)
        start_cmd_override = ""
        serve_port_hint = None
        if contract is not None:
            serve = contract.serve
            scope = str(self._pm._get_config("verify.static_scope", "main")
                        or "main").strip().lower()
            wt_scope = scope == "worktree"
            # 主树 prepare 仅在实例落于主树时需要——worktree 作用域在
            # serving worktree 内构建（共享助手），主树构建纯属双倍等待
            # （add-main-tree-deps-provision 锚点：该案在此主树 prepare 前做
            # 依赖供给，本 SPEC 预检在其后 spawn 前——供给 → prepare → 预检
            # → spawn。）
            if contract.prepare and not wt_scope:
                # add-main-tree-deps-provision：主树 prepare 前按 prepare cwd
                # 集合预装依赖（本 SPEC 预检在其后 spawn 前——供给 → prepare
                # → 预检 → spawn）
                ensure_main_tree_deps(
                    self._pm.project_root,
                    sorted({(s.cwd or ".") for s in contract.prepare}),
                    mode=resolve_deps_mode(
                        contract, self._pm._get_config("verify.deps_mode", "")),
                    logger=self._pm.logger,
                )
                err = run_prepare_steps(contract, self._pm.project_root)
                if err:
                    return False, False, f"验证契约 prepare 失败: {err}"
            if serve and serve.kind == "static":
                if wt_scope:
                    return self._serve_static_in_worktree(
                        spec_name, contract, scenarios_path)
                return self._serve_static_in_main(contract, scenarios_path)
            if serve and serve.kind == "command" and serve.cmd:
                if wt_scope:
                    return self._serve_command_in_worktree(
                        spec_name, contract, scenarios_path)
                start_cmd_override = serve.cmd
                serve_port_hint = serve.port

        def _probe(u: str, timeout: float = 2.0) -> bool:
            try:
                req = urllib.request.Request(u, method="GET",
                                             headers={"User-Agent": "fenix-verify-probe"})
                with urllib.request.urlopen(req, timeout=timeout):
                    return True
            except Exception:
                return False

        # 1) 直接探测：已可达则无需自愈
        if all(_probe(u) for u in urls):
            return True, False, ""

        # 2) 自愈：验证契约 serve.cmd 优先，回退 commands.start（旧行为）
        start_cmd = start_cmd_override or str(
            self._pm._get_config("commands.start", "") or "").strip()
        if not start_cmd or start_cmd in ("echo 'No start command configured yet'",):
            kind_label = "、".join(sorted(kinds))
            # 契约缺失/损坏：产生 verify_contract_missing 信号派发 Administrator 起草
            # （设计 D1：确定性死局不等 4 次失败计数与升级冷却）
            note = (
                f"场景集含 {kind_label} 场景但无 serve 配置"
                f"（.fenix/verify.yaml serve 段或 config commands.start 兜底）"
                f"——已派发 Administrator 起草验证契约"
            )
            # 检测是否为契约解析失败（文件存在但 YAML 解析失败）
            contract_path = self._pm.project_root / ".fenix" / "verify.yaml"
            parse_error = False
            if contract_path.is_file() and contract is None:
                # 文件存在但 load_verify_contract 返回 None = 解析失败
                parse_error = True
            # 写入 verify_contract_missing 信号（形态参照 verify_uniform_failure）
            from core.admin_store import AdminStore, SIGNAL
            store = AdminStore(self._pm.project_root, self._pm.logger)
            try:
                store.append({
                    "kind": SIGNAL,
                    "signal_type": "verify_contract_missing",
                    "spec": spec_name,
                    "severity": "major",
                    "description": note,
                    "evidence": (
                        f"项目根={self._pm.project_root}; "
                        f"场景kind集={','.join(sorted(kinds))}; "
                        f"parse_error={'是' if parse_error else '否'}"
                    ),
                    "recommended_action": (
                        "Administrator 起草 .fenix/verify.yaml 验证契约："
                        "检查项目构建命令、静态目录、服务启动方式；"
                        "草稿写临时路径 → bin/fenix_verify_contract.py 自证 → "
                        "全通才落位 → git 提交 → spec 复位 ready 触发重验证"),
                })
            except Exception as e:
                self._pm.logger.error(
                    "pm_engine", f"verify_contract_missing 信号写入失败: {e}")
            return False, False, note

        # 端口注入（与 worktree 路径同机制）：cmd 引用 {port} 时分配空闲
        # 端口替换并导出 FENIX_VERIFY_PORT——主树兜底自启同样不撞既有实例
        base_port = serve_port_hint
        injected_port = None
        if "{port}" in start_cmd:
            injected_port = find_free_port()
            start_cmd = start_cmd.replace("{port}", str(injected_port))
            base_port = injected_port
        elif base_port is None:
            pm = re.search(r"(?:--port|-p)\s+(\d+)", start_cmd)
            if pm:
                base_port = int(pm.group(1))

        self._pm.logger.warning(
            "pm_engine",
            f"验证目标应用不可达，自动启动服务: {start_cmd}",
        )

        # 入口存在性预检（design D1）：主树兜底自启同样在 spawn 前校验入口
        # 存在性——serve.cmd 入口指向不存在文件时 fail-fast（场景执行数=0，
        # 确定性错误不等探活超时浪费 30s）；commands.start 等非脚本型运行时
        # 形态由解析器返回 None 放行（零误杀）。
        preflight_err = entry_preflight_error(start_cmd, self._pm.project_root)
        if preflight_err:
            self._write_verify_contract_missing(
                spec_name,
                f"{preflight_err}（入口存在性预检失败，spawn 前 fail-fast）",
                (f"start_cmd 原文={start_cmd!r}; cwd={self._pm.project_root}; "
                 f"来源={'契约 serve.cmd' if start_cmd_override else 'config commands.start 兜底'}"),
                recommended_action=(
                    "Administrator 修正入口路径：按错误信息中「候选」提示修正 "
                    ".fenix/verify.yaml serve.cmd（或 commands.start），确认构建"
                    "产物已生成后重验"),
            )
            self._escalate_env_blocked(
                spec_name,
                [preflight_err],
                title="验证环境阻塞（入口存在性预检失败）",
            )
            return False, False, preflight_err

        # 启动一次（后台、脱离会话、stdout/stderr 落盘 boot.log）；
        # 随后等待可达或扫描邻近端口。启动即死错误（Cannot find module 等）
        # 从 DEVNULL 吞掉改为落盘（design D3），探活失败时尾部附入告警。
        boot_log = self._open_boot_log(spec_name)
        env = {**os.environ}
        if injected_port:
            env["FENIX_VERIFY_PORT"] = str(injected_port)
        try:
            proc = subprocess.Popen(
                start_cmd, shell=True, cwd=str(self._pm.project_root),
                stdout=boot_log, stderr=boot_log,
                start_new_session=True, env=env,
            )
        except Exception as e:
            boot_log.close()
            return False, False, f"启动验证目标应用失败: {e}"
        # verify-process-lifecycle D6：兜底 spawn 同登记纳入管理
        # （pid/spec/worktree 空、端口先按 hint，实际可达端口由探测修正）
        self._register_serving_instance(spec_name, proc, hint_port=base_port)

        for _ in range(30):
            time.sleep(1)
            if all(_probe(u) for u in urls):
                boot_log.close()
                return True, False, "已自动启动应用服务"

        # 场景 URL 端口 ≠ commands.start 端口（planner 臆测端口，如 3000 vs 8787）：
        # 应用已在 base_port 可达时，错的是场景端口而非应用——改写场景端口为
        # 实际端口后重探。原逻辑只改写 base_port 的出现处（base_port → 扫描到的
        # 邻近端口），对「场景写了别的端口」完全无能为力，导致应用明明已启动
        # 却被判不可达、spec 永久卡死在 testing（fix-fix-improve-verify-adjudication）。
        if base_port and _probe(f"http://127.0.0.1:{base_port}/"):
            foreign_ports = {
                m.group(1)
                for u in urls
                for m in [re.search(r":(\d+)(?=[/\?#]|$)", u)]
                if m and int(m.group(1)) != base_port
            }
            if foreign_ports:
                for p in sorted(foreign_ports, key=int):
                    self._pm._rewrite_scenario_port(scenarios_path, int(p), base_port)
                urls_new = []
                for u in urls:
                    v = u
                    for p in foreign_ports:
                        v = re.sub(r":%s(?=[/\?#]|$)" % p, f":{base_port}", v)
                    urls_new.append(v)
                if all(_probe(u) for u in urls_new):
                    boot_log.close()
                    return True, False, (
                        f"场景 URL 端口 {sorted(foreign_ports, key=int)} 与应用实际端口 "
                        f"{base_port} 不符（planner 臆测），已改写场景端口并确认可达"
                    )

        # 端口自动递增场景（如 --port 被占用时服务上探到邻近端口）：
        # 扫描 base_port 附近的端口，命中则改写场景 URL 并确认可达
        if base_port:
            for port in range(base_port + 1, base_port + 51):
                if _probe(f"http://127.0.0.1:{port}/"):
                    urls_new = [re.sub(r":%d(?=[/\?]|$)" % base_port, f":{port}", u) for u in urls]
                    if all(_probe(u) for u in urls_new):
                        self._pm._rewrite_scenario_port(scenarios_path, base_port, port)
                        boot_log.close()
                        return True, False, f"已自动启动应用服务（端口冲突，改用 {port}）"

        # 探活最终失败：boot.log 尾部（≤2KB）附入错误串，启动即死错误
        # （Cannot find module 等）对 admin 直接可读（design D3）
        boot_tail = self._read_boot_log_tail(spec_name, boot_log)
        boot_log.close()
        return False, False, ("应用仍不可达：已自动执行 commands.start 并扫描邻近端口，"
                              "仍无法连接（可能需人工启动/换端口，或属需用户参与的验证场景）"
                              + boot_tail)

    def _open_boot_log(self, spec_name: str):
        """打开 .fenix/verify-serving/<spec>-boot.log（覆盖写句柄，design D3）。

        兜底/命令型 spawn 的 stdout/stderr 落盘于此（替代 DEVNULL 吞掉），
        启动即死错误（Cannot find module 等）对 admin 可读。启动前 truncate
        控制单轮大小（验证实例生命周期短，分钟级，接受无界增长）。
        """
        log_dir = Path(self._pm.project_root) / ".fenix" / "verify-serving"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return open(log_dir / f"{spec_name}-boot.log", "wb")
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"boot.log 打开失败（回退丢弃输出）: {e}")
            return subprocess.DEVNULL

    def _read_boot_log_tail(self, spec_name: str, handle) -> str:
        """读 boot.log 尾部 ≤2KB 附入探活失败错误串（design D3）。

        句柄关闭前调用以 flush 子进程残留输出；读失败/空文件返回空串
        （不因取证自身异常改动错误判定）。
        """
        try:
            handle.flush()
        except Exception:
            pass
        try:
            log_path = (Path(self._pm.project_root) / ".fenix"
                        / "verify-serving" / f"{spec_name}-boot.log")
            data = log_path.read_bytes()[-2048:]
            if not data.strip():
                return ""
            tail = data.decode("utf-8", errors="replace").rstrip()
            return f"\n── boot.log 尾部（≤2KB）──\n{tail}"
        except Exception:
            return ""

    def _write_verify_contract_missing(self, spec_name: str, note: str,
                                       evidence: str,
                                       recommended_action: str = "") -> None:
        """写 verify_contract_missing 信号呼叫 Administrator（契约相关 fail-fast 共用）。

        契约缺失/损坏/入口预检失败/轻量自证失败的统一出口（design D1/D2）：
        spawn 前确定性错误不等待失败计数与升级冷却，直接派发。失败记 warning
        不抛穿调用方（信号通道自身不可影响验证判定）。
        """
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self._pm.project_root, self._pm.logger)
        try:
            store.append({
                "kind": SIGNAL,
                "signal_type": "verify_contract_missing",
                "spec": spec_name,
                "severity": "major",
                "description": note,
                "evidence": evidence,
                "recommended_action": recommended_action or (
                    "Administrator 修正 .fenix/verify.yaml 验证契约："
                    "检查构建命令、serve 段入口/静态目录、端口注入；"
                    "修正后 git 提交 → spec 复位 ready 触发重验证"),
            })
        except Exception as e:
            self._pm.logger.error(
                "pm_engine", f"verify_contract_missing 信号写入失败: {e}")

    def _rewrite_scenario_port(self, scenarios_path: Path, old_port: int, new_port: int):
        """端口冲突换端口后，重写 test_scenarios.json 中的 URL 端口。"""
        try:
            content = scenarios_path.read_text(encoding="utf-8")
            content = re.sub(r":%d(?=[/\?\"']|$)" % old_port, f":{new_port}", content)
            scenarios_path.write_text(content, encoding="utf-8")
            self._pm.logger.info("pm_engine", f"已重写验证场景端口 {old_port} → {new_port}")
        except Exception as e:
            self._pm.logger.warning("pm_engine", f"重写验证场景端口失败: {e}")


    def _current_verify_round(self, spec_name: str) -> int:
        """推导本轮验证轮次：``_verify_fail_rounds + 1``（首轮=1）。"""
        entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
        except (TypeError, ValueError):
            fail_rounds = 0
        return fail_rounds + 1


    def _serving_port_for_spec(self, spec_name: str):
        """本轮 serving 端口（从契约 base_url 解析）；无实例形态返回 None。"""
        base_url = self._current_instance_base_url(spec_name)
        if not base_url:
            return None
        try:
            from urllib.parse import urlparse
            return urlparse(base_url).port
        except Exception:
            return None


    def _run_scenario_static_check(self, spec_name: str) -> None:
        """场景静态缺陷扫描挂点（add-scenario-defect-triage-gate D3）。

        在场景集冻结完成后、阶段2 执行前调用（_run_three_stage_verification
        经门面转调）。findings 覆盖写 ``scenario_static_findings.json`` 供
        judge prompt 情报段注入——**只做情报不拦截执行**，任何异常记 WARNING
        不阻断验证（fail-open）。
        """
        from core.verify_engine.scenario_static_check import (
            scan_scenarios, write_findings,
        )
        scenarios_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "test_scenarios.json"
        )
        try:
            if not scenarios_path.exists():
                return
            data = json.loads(scenarios_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return
            serving_port = self._serving_port_for_spec(spec_name)
            findings = scan_scenarios(data, serving_port=serving_port)
            write_findings(self._pm.project_root, spec_name, findings)
            if findings:
                from collections import Counter
                dist = dict(Counter(f.rule_id for f in findings))
                self._pm.logger.info(
                    "pm_engine",
                    f"场景静态扫描 '{spec_name}'（serving 端口 "
                    f"{serving_port or '未知'}）检出 {len(findings)} 条情报: "
                    f"{dist}",
                )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"场景静态扫描跳过 '{spec_name}'（fail-open，不阻断验证）: "
                f"{type(e).__name__}: {e}",
            )

    def _run_contract_static_check(self, spec_name: str) -> None:
        """契约只读一致性检查挂点（planner-contract-findings，design D4）。

        在 planner-plan 产物验收通过后（出题完成处）调用：对验证契约做只读
        一致性检查（入口存在性/与 start script 一致性/端口注入），findings
        覆盖写 ``contract_findings.json`` 供 admin 处置 prompt 注入。
        **只做情报不拦截出题**，任何异常记 WARNING 不阻断（fail-open）。
        """
        from core.verify_engine.scenario_static_check import (
            scan_contract, write_contract_findings,
        )
        try:
            findings = scan_contract(self._pm.project_root)
            write_contract_findings(
                self._pm.project_root, spec_name, findings)
            if findings:
                from collections import Counter
                dist = dict(Counter(f["rule_id"] for f in findings))
                self._pm.logger.info(
                    "pm_engine",
                    f"契约静态检查 '{spec_name}' 检出 {len(findings)} 条情报: "
                    f"{dist}",
                )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"契约静态检查跳过 '{spec_name}'（fail-open，不阻断出题）: "
                f"{type(e).__name__}: {e}",
            )


    def _apply_scenario_freeze(self, spec_name: str) -> dict:
        """应用场景集冻结：planner 产出 vs 持久化集 diff，写回 scenarios.json。

        design D3：确定性、纯 Python，planner 无法通过输出文本绕过。
        在场景执行前调用（_run_three_stage_verification 阶段1 之后）。

        写端 schema 门（fix-frozen-scenario-orphan-reservoir D1/D2/D3）：
        - 收编写回 / 补齐写回 test_scenarios.json 前过 ``validate_scenario_dicts``
          同源校验（与读端 load_scenarios 同源），坏条目剔除留痕（id 清单）、
          不整批拒绝；剔除数超本轮 20% 时 ERROR 升级（Task 2.4）。
        - ``_scenarios_full.json`` 备份仅当 planner 产出全部合法时更新
          （备份价值在「可恢复」，存毒即失去价值）；含非法条目时保留旧备份
          + WARNING 留痕。
        - 无理由缺场景且备份缺定义 → 改弃场景（D3）：登记「定义不可恢复」
          剔除清单，不再写 ``{"id","description"}`` 非法占位，验证以剩余
          场景继续；备份有完整定义时维持既有补回行为（Task 3.2）。

        写前客户端预校验（evo-planner-scenario-schema-alignment 3.1-3.10）：
        - planner 产出进入阶段2 前逐条过与写端一致的校验器
          （``validate_scenario_dicts``，与读端同源且含旧 schema 迁移），
          非法条目剔除留痕（场景 id + 缺失字段），合法部分照常进入执行，
          MUST NOT 等整批落盘后整批剔除（09-13 两批 100% 剔除 → 阶段2
          整轮失败退回的既有路径）。
        - 3.3 移除声明豁免：携带 ``remove_reason`` 的声明条目不过滤
          （纯移除声明过不了 validate_scenario_dicts——缺 navigate 步骤等），
          令 diff 仍看到移除声明、仅对「实际写入集」过滤——否则理由丢失、
          planner 显式移除被静默反转为保留。
        - 3.2 主路径写回（MUST）：过滤得合法集后，于主路径把合法子集整体
          重写回 test_scenarios.json（事故实证条件——第 1 轮 / persisted 为空 /
          无理由缺失 0——永不进补齐分支，若只把写回挂补齐分支，非法条目仍留
          在文件、阶段2 仍旧整轮失败）；与补齐分支写回互斥（补齐分支已写即
          不再写），两处写回内容均为过滤后集合。
        - 3.5/3.8 空集显式兜底：过滤后无合法场景 → 不写空 test_scenarios.json、
          不 save_scenario_set（防止持久化集被写成空集——load_scenario_set 对
          ``scenarios: []`` 返回非 None、下一轮 diff 从首轮全量口径退化增量
          口径），以结构化返回值 ``{'aborted': 'no_valid_scenarios', ...}``
          承载信号，由调用点消费（阶段1 主路径退回 plan / 重排预算耗尽显式
          结束；judge 重入路径拒绝重入）——MUST NOT 依赖加载报错通道
          （写回合法子集后该报错不再触发，0 场景报告会被洗白门 fail-open
          放行判 verified）。
        - 3.9 剔除比例口径：超本轮 20% 的 ERROR 升级以写回前最终合法集为
          基准统计（两遍剔除——过滤 pass 与补齐 pass——合并）。
        - 3.10 剔除留痕：剔除条目 id 与 covers 存实例属性，紧随其后的
          ``_apply_interaction_contract`` 据此把「条目非法剔除」与「设计漏项」
          缺口区分开，避免「重排-剔除」循环。

        Returns:
            dict：{'diff': <DiffResult>, 'path': <写入路径>}，便于报告渲染复用；
            空集显式兜底时返回 {'aborted': 'no_valid_scenarios', 'rejected':
            [<逐条剔除描述>], 'total': <原始总数>, 'path': <场景文件路径>}。
        """
        from core.verify_scenarios import (
            load_scenario_set, diff_planner_output, save_scenario_set,
        )
        from core.verify_engine.scenarios import (
            validate_scenario_dicts, prepare_scenarios_for_write,
        )
        verify_dir = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name
        )
        scenarios_path = verify_dir / "test_scenarios.json"
        if not scenarios_path.exists():
            return {}
        try:
            planner_scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(planner_scenarios, list):
            return {}

        entry = self._pm.state_machine.read_one(spec_name) or {}
        current_round = self._pm._current_verify_round(spec_name)

        # ── 写前客户端预校验（3.1/3.3）：逐条过与写端一致的校验器 ──
        # 过滤出「实际写入集」（valid_planner）与「diff 输入集」（diff_input ＝
        # 合法集 + 携带 remove_reason 的移除声明，3.3 移除声明豁免）。
        valid_planner: list = []
        rejected: list[str] = []
        rejected_ids: list[str] = []
        diff_input: list = []
        for idx, item in enumerate(planner_scenarios):
            if not isinstance(item, dict):
                rejected.append(f"[{idx}]非对象({type(item).__name__})")
                continue
            item_id = item.get("id") or f"[{idx}]"
            if isinstance(item.get("remove_reason"), str) and item["remove_reason"]:
                # 3.3：纯移除声明条目保留进 diff 输入（移除理由照常生效），
                # 不参与写回（其形态本就不是可执行场景）。
                diff_input.append(item)
                continue
            errs = validate_scenario_dicts([item])
            if errs:
                rejected.append(f"{item_id}（{'；'.join(errs[:2])}）")
                rejected_ids.append(str(item_id))
                continue
            valid_planner.append(item)
            diff_input.append(item)

        # 3.10：剔除条目 id 与 covers 留痕（交互契约消费——被剔除场景覆盖的
        # 候选不属「设计漏项」缺口，避免「重排-剔除」循环）。
        self._last_freeze_rejected = list(rejected_ids)
        rejected_covers: set = set()
        rejected_set = set(rejected_ids)
        for item in planner_scenarios:
            if not isinstance(item, dict):
                continue
            if item.get("id") in rejected_set:
                covers = item.get("covers")
                if isinstance(covers, list):
                    rejected_covers.update(str(c) for c in covers if c)
        self._last_freeze_rejected_covers = rejected_covers

        # ── 空集显式兜底（3.5/3.8）：全部条目非法 → 不写空文件、不持久化 ──
        # 写回合法子集后「全部非法」不再触发阶段2 load_scenarios 报错（既有
        # 退回路径依赖的正是该报错），必须在此显式判定；0 场景经 engine.run([])
        # 产出无 env_error 的全绿报告、会被洗白门 fail-open 放行判 verified，
        # 故空集 MUST NOT 以 0 场景继续进入阶段2。空集判定先于 save_scenario_set
        # （3.8）：持久化集保持不变，下一轮 diff 维持首轮全量口径。
        if not valid_planner:
            if rejected:
                reject_note = "、".join(rejected)
                self._pm.logger.error(
                    "pm_engine",
                    f"场景写前预校验整批拒绝 '{spec_name}'（{len(rejected)}/"
                    f"{len(planner_scenarios)} 条全部非法），无合法场景可执行 "
                    f"— 不写空文件/不持久化，退回 plan 重排: {reject_note}",
                )
            return {
                "aborted": "no_valid_scenarios",
                "rejected": rejected,
                "total": len(planner_scenarios),
                "path": str(scenarios_path),
            }

        # ── 剔除留痕（第一遍，3.4 既有语义：超本轮 20% ERROR 升级）──
        if rejected:
            reject_note = "、".join(rejected)
            total = len(planner_scenarios) or 1
            ratio = len(rejected) / total
            log_fn = (self._pm.logger.error if ratio > 0.2
                      else self._pm.logger.warning)
            log_fn(
                "pm_engine",
                f"场景写前预校验剔除 {len(rejected)}/{len(planner_scenarios)} "
                f"条非法条目（{'超本轮20%' if ratio > 0.2 else '未超20%'}），"
                f"合法部分照常执行: {reject_note}",
            )

        diff = diff_planner_output(
            self._pm.project_root, spec_name, entry, diff_input, current_round)
        if rejected:
            reject_note = "、".join(rejected)
            diff.change_lines.append(
                f"- 写前预校验剔除 {len(rejected)} 条非法条目（未落盘）：{reject_note}"
            )

        # 写回 scenarios.json（原子写；首轮写入 / 合并追加 / 补齐后稳定集）
        path = save_scenario_set(self._pm.project_root, diff.scenario_set)
        # 全量场景定义备份（_scenarios_full.json）：供无理由缺场景时按持久化集
        # 补齐 test_scenarios.json 的原始定义（design D2：不丢回归面）。
        # 仅当本轮未删减既有场景时更新备份（保留最全的历史定义）。
        # D2 特例：备份仅当 planner 产出全部合法时更新——存毒即失去可恢复价值，
        # 含非法条目时保留旧备份并 WARNING 留痕。
        # D3 交互：当存在无理由缺场景（unreasoned_missing）时，旧备份是补回
        # 所需的历史定义源——此时 MUST NOT 覆盖（否则 reconcile 无法取回定义，
        # 缺定义场景被误判为不可恢复）。仅当 diff.ok（无无理由缺失）时更新。
        if not diff.removed and not diff.unreasoned_missing:
            if rejected:
                self._pm.logger.warning(
                    "pm_engine",
                    f"场景备份未更新 '{spec_name}'：planner 产出含 "
                    f"{len(rejected)} 条非法条目（_scenarios_full.json 存毒即"
                    f"失去可恢复价值，保留旧备份）",
                )
            else:
                full_backup = verify_dir / "_scenarios_full.json"
                try:
                    # frozen-scenario-schema-migration 2.1：写端恒定写入
                    # schema_version 标记（旧字段先迁移再落盘，读侧直通）
                    full_backup.write_text(
                        json.dumps(
                            prepare_scenarios_for_write(valid_planner),
                            ensure_ascii=False, indent=2,
                        ),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
        self._pm.logger.info(
            "pm_engine",
            f"场景集冻结 '{spec_name}'（第 {current_round} 轮）：稳定集 "
            f"{len(diff.scenario_set.scenarios)} 个，新增 {len(diff.added)}，"
            f"有理由移除 {len(diff.removed)}，无理由缺失 {len(diff.unreasoned_missing)}",
        )

        # ── 写回 test_scenarios.json 的合法子集（3.2/3.6/3.9）──
        # 两处写点互斥 3.2：补齐分支（无理由缺场景时以持久化集补齐后写回）与
        # 主路径写回；两处内容均为过滤后集合。第二遍剔除（write_rejected，补齐
        # pass 对备份取回条目再剔一批）与第一遍合并统计 3.9。
        write_rejected: list[str] = []
        final_valid: list = []
        if not diff.ok and diff.unreasoned_missing:
            # 无理由缺场景 → 以持久化集补齐 test_scenarios.json（不中断验证，
            # design D2）：planner 实际执行的场景文件必须含全部既有场景，否则
            # 回归面丢失。优先从上一轮全量备份 _scenarios_full.json 取回被丢弃
            # 场景的原始定义。
            missing_ids = {e.id for e in diff.unreasoned_missing}
            reconciled = [s for s in valid_planner
                          if isinstance(s, dict) and s.get("id")
                          and s.get("id") not in missing_ids]
            backup = verify_dir / "_scenarios_full.json"
            backup_map = {}
            if backup.exists():
                try:
                    for s in json.loads(backup.read_text(encoding="utf-8")):
                        if isinstance(s, dict) and s.get("id"):
                            backup_map[s["id"]] = s
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    backup_map = {}
            # D3：备份缺定义 → 改弃场景（不再写 {"id","description"} 占位）。
            # 备份取回的条目可能来自旧备份（未经写端门），统一过下方
            # 收编写回 schema 门剔除坏条目；备份缺定义的条目登记「定义不可恢复」
            # 从本轮验证集剔除（宁少验一个，不写必败文件）。
            unrecoverable: list[str] = []
            for mid in missing_ids:
                if mid in backup_map:
                    reconciled.append(backup_map[mid])
                else:
                    unrecoverable.append(mid)
            if unrecoverable:
                self._pm.logger.error(
                    "pm_engine",
                    f"无理由缺失且备份缺定义的场景定义不可恢复，从本轮验证集"
                    f"剔除（宁少验一个，不写必败文件）: {'、'.join(unrecoverable)}",
                )
                diff.change_lines.append(
                    f"- 无理由缺失且备份缺定义的场景 {len(unrecoverable)} 个"
                    f"定义不可恢复，已剔除：{'、'.join(unrecoverable)}"
                )
            # ── 收编写回 schema 门（D1/D2 / 3.1 同校验收敛）──
            # 备份取回条目与合法 planner 产出再次整体过结构校验：坏条目剔除留痕，
            # 合法部分照常落盘，不整批拒绝。
            write_valid: list = []
            for idx, item in enumerate(reconciled):
                if not isinstance(item, dict):
                    write_rejected.append(f"[{idx}]非对象({type(item).__name__})")
                    continue
                item_id = item.get("id") or f"[{idx}]"
                errs = validate_scenario_dicts([item])
                if errs:
                    write_rejected.append(f"{item_id}（{'；'.join(errs[:2])}）")
                    continue
                write_valid.append(item)
            if write_rejected:
                self._pm.logger.warning(
                    "pm_engine",
                    f"补齐写回剔除 {len(write_rejected)} 条非法条目（未落盘）: "
                    f"{'、'.join(write_rejected)}",
                )
                diff.change_lines.append(
                    f"- 补齐写回剔除 {len(write_rejected)} 条非法条目（未落盘）："
                    f"{'、'.join(write_rejected)}"
                )
            try:
                # frozen-scenario-schema-migration 2.1：补齐写回同样恒定写入
                # schema_version（备份取回条目可能为旧 schema，先迁移再落盘）
                scenarios_path.write_text(
                    json.dumps(
                        prepare_scenarios_for_write(write_valid),
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as e:
                # 3.6：写回相关异常须 ERROR 留痕（外层 except 仅记 WARNING）
                self._pm.logger.error(
                    "pm_engine",
                    f"补齐场景写回失败 '{spec_name}'（spec 可能仍以未过滤文件"
                    f"进入阶段2）: {e}",
                )
            final_valid = write_valid
        else:
            # ── 3.2 主路径写回（MUST，否则本修复对本次事故空转）──
            # 事故实证条件（第 1 轮 / persisted 为空 / 无理由缺失 0）永不进入
            # 上方补齐分支（verification.py:1296），而补齐分支是既有唯一写点；
            # 若只把写回挂补齐分支，非法条目仍留在 planner 写的文件、阶段2
            # 仍旧整轮失败。故在主路径写回过滤后合法子集，覆盖首轮/无缺失轮。
            try:
                scenarios_path.write_text(
                    json.dumps(
                        prepare_scenarios_for_write(valid_planner),
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as e:
                # 3.6：写回成为主路径，异常以 ERROR 留痕（不得只留 WARNING 旁证）
                self._pm.logger.error(
                    "pm_engine",
                    f"场景合法子集主路径写回失败 '{spec_name}'（spec 将仍以 "
                    f"planner 原文件进入阶段2，非法条目可能致整批失败）: {e}",
                )
            final_valid = valid_planner

        # ── 3.9 剔除比例合并统计（以写回前最终合法集为基准）──
        # 既有实现只统计第一遍 rejected（过滤 pass）；补齐 pass 的剔除
        # （write_rejected，含从备份取回的既有场景）现仅 WARNING、无比例升级，
        # 会静默缩小回归面。两遍合并后统一按「写回前最终合法集」基准升级。
        if rejected or write_rejected:
            total_rejected = len(rejected) + len(write_rejected)
            base = len(final_valid) or 1  # 写回前最终合法集为基准（3.9 口径）
            ratio = total_rejected / base
            if ratio > 0.2:
                self._pm.logger.error(
                    "pm_engine",
                    f"场景剔除合计超本轮 20%（{total_rejected} 条剔除 / 写回前"
                    f"最终合法集 {len(final_valid)} 条，比例 {ratio:.0%}）"
                    f"'{spec_name}' — 可见性兜底升级（非退回触发器）",
                )
                diff.change_lines.append(
                    f"- 场景剔除合计 {total_rejected} 条（过滤 pass "
                    f"{len(rejected)} + 补齐 pass {len(write_rejected)}），"
                    f"超写回前最终合法集 20%"
                )

        self._last_scenario_diff = diff  # 供报告渲染（2.3）读取
        return {"diff": diff, "path": str(path)}


    def _apply_interaction_contract(self, spec_name: str) -> dict:
        """场景执行前校验交互契约覆盖（design D1/D2）。

        页面类 SPEC 检出可交互候选时，校验场景集对每个候选的覆盖（``covers``
        登记 / 场景文本命中）或纯展示声明（``declared_display`` / SPEC 标注）。
        辅助治理：任何异常不阻断验证主流程。

        Returns:
            {"ok": True} 或 {"ok": False, "result": ContractResult,
            "feedback": <退回 plan 的反馈文本>, "uncovered": [元素标识]}
        """
        from core.interaction_contract import (
            validate_interaction_coverage, build_replan_feedback,
            load_planner_scenarios,
        )
        from core.verify_scenarios import load_scenario_set
        try:
            scenarios_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            planner_scenarios = load_planner_scenarios(scenarios_path)
            if planner_scenarios is None:
                return {"ok": True, "skipped": True}
            persisted = load_scenario_set(self._pm.project_root, spec_name)
            result = validate_interaction_coverage(
                self._pm.project_root, spec_name, planner_scenarios, persisted)
            # evo-planner-scenario-schema-alignment 3.10：被 schema 预校验剔除的
            # 场景覆盖的候选不属「设计漏项」缺口——剔除已在该场景自身暴露结构
            # 问题并单独留痕（3.1 剔除 + 3.4/3.9 比例升级），覆盖校验将其从
            # uncovered 移除，避免「重排-剔除」循环（剔除改变文件 → 覆盖校验
            # 误判缺口 → 退回重排 → planner 再生成同类非法场景）。本去噪仅对
            # 覆盖登记（covers 字段）生效；未登记 covers 的文本命中式覆盖无法
            # 从剔除侧反推，按既有「设计漏项」判定（3.10 至少区分两类缺口）。
            rejected_covers = getattr(self, "_last_freeze_rejected_covers", None) or set()
            if rejected_covers and not result.ok and result.uncovered:
                remaining = [k for k in result.uncovered if k not in rejected_covers]
                removed = [k for k in result.uncovered if k in rejected_covers]
                if removed:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"交互契约覆盖校验 '{spec_name}'：{len(removed)} 个候选"
                        f"原由被 schema 预校验剔除的场景覆盖"
                        f"（{sorted(removed)}）— 归为「条目非法剔除」缺口，"
                        f"不计入设计漏项，不触发退回",
                    )
                    result.uncovered = remaining
                    result.ok = not remaining
                    result.change_lines.append(
                        f"- 元素 {'、'.join(sorted(removed))} 原由被 schema "
                        f"预校验剔除的场景覆盖（剔除已单独留痕），不属设计漏项"
                    )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"交互契约校验跳过 '{spec_name}'（不阻断）: {e}")
            return {"ok": True, "skipped": True}

        self._last_interaction_contract = result
        if result.ok:
            self._pm.logger.info(
                "pm_engine",
                f"交互契约覆盖校验通过 '{spec_name}'（候选 "
                f"{len(result.candidates)} 个，纯展示声明 {len(result.declared)} 个）",
            )
            return {"ok": True, "result": result}

        self._pm.logger.warning(
            "pm_engine",
            f"交互契约覆盖不完整 '{spec_name}': {result.uncovered}",
        )
        return {
            "ok": False, "result": result,
            "feedback": build_replan_feedback(result),
            "uncovered": list(result.uncovered),
        }


    def _render_scenario_change_section_to_report(self, spec_name: str) -> None:
        """把本轮场景集变更小节追加到 verification-report.md（spec 需求 2.3）。

        报告闸门（add-verify-report-gate）已保证文件存在；此处幂等追加，
        重复调用会因已存在「本轮场景集变更」标题而跳过。diff 来源优先级：
        ``_last_scenario_diff``（本轮冻结计算）> 重新读取 scenarios.json（首轮）。
        """
        diff = getattr(self, "_last_scenario_diff", None)
        from core.verify_scenarios import (
            render_change_section, load_scenario_set, render_first_write_section,
        )
        if diff is None:
            persisted = load_scenario_set(self._pm.project_root, spec_name)
            if persisted is None:
                return
            section = render_first_write_section(persisted)
        else:
            section = render_change_section(diff)
        if not section.strip():
            return
        report_path = (
            Path(self._pm.project_root) / "spec" / "changes"
            / spec_name / "verification-report.md"
        )
        if not report_path.exists():
            return
        try:
            content = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        if "## 本轮场景集变更" in content:  # 幂等：不重复追加
            return
        # add-verify-report-gate 要求不覆盖 mtime 语义仅针对「Agent 已写」文件；
        # 此处为框架追加小节，直接写回（Agent 漏写场景变更时由框架补）。
        try:
            report_path.write_text(content.rstrip("\n") + "\n" + section + "\n",
                                   encoding="utf-8")
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"场景集变更小节写回失败 '{spec_name}': {e}")


    def _run_three_stage_verification(self, spec_name: str, _repair_depth: int = 0):
        """三步验证流水线主逻辑。"""
        # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）：入口状态
        # 非 testing → DEBUG 丢弃本流水线结果（注明当前状态），不执行任何迁移/
        # 回退/派发。覆盖 stale-result 防护拨回 implemented、并发双路径中先到者
        # 已推进、以及一切状态漂移变体。正常路径（dispatch 刚置 testing）不受影响。
        _entry_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
        if _entry_status != "testing":
            self._pm.logger.debug(
                "pm_engine",
                f"Verify result discarded for '{spec_name}': spec is "
                f"'{_entry_status}', not testing at pipeline entry — dropped",
            )
            return

        import asyncio
        import importlib
        import sys

        # 重新加载验证引擎模块，确保使用最新代码
        # fenixd 作为常驻进程运行，Python 会缓存已导入的模块，
        # 实现者更新代码后缓存不会自动失效，必须显式重新加载
        # 注意：子模块必须先于父包重新加载（依赖顺序）
        #
        # 额外保障机制（fix-fix-fix-fix）：
        # importlib.reload 不会更新其他模块中已导入的名称引用，
        # 因此在 reload 之后显式重新导入核心类，确保使用最新版本。
        _verify_modules = [
            "core.verify_engine.visual_diff",
            "core.verify_engine.browser",
            # admin 修 2026-09-06：web_runner 持有 `from .browser import
            # BrowserManager` 的旧类引用（reload 不会更新其他模块已导入的
            # 名称），不 reload 它则 browser.py 的更新经 WebRunner 实例化
            # 路径完全不生效（add-spec-hooks admin 处置实测：browser 首帧
            # 等待修复被旧 BrowserManager 类屏蔽）。须先于 engine reload。
            "core.verify_engine.web_runner",
            # admin 修 2026-09-07：三个 runner 一并 reload——此前 cli/api
            # runner 不在列表内，其代码修复同样不生效；配合 runner.py 的
            # 同模块重注册放行（否则装饰器对已注册 kind raise、reload 整体
            # 失败且被下方静默吞掉，sys.modules 留存旧类）。
            "core.verify_engine.cli_runner",
            "core.verify_engine.api_runner",
            "core.verify_engine.assertions",
            "core.verify_engine.scenarios",
            "core.verify_engine.scenario_static_check",
            "core.verify_engine.engine",
            "core.verify_engine",
        ]
        for mod_name in _verify_modules:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception as e:
                    # reload 失败绝不可静默：sys.modules 将留存旧代码，admin
                    # 的引擎修复看似已生效实则被旧类屏蔽（本类根因曾静默潜伏
                    # 至 fix-mobile-touch-disclosure 轮才暴露）。降级告警留痕。
                    self._pm.logger.warning(
                        "pm_engine",
                        f"verify_engine 模块热重载失败 '{mod_name}'（将沿用旧代码）: "
                        f"{type(e).__name__}: {e}",
                    )

        # 额外保障：强制从磁盘重新导入核心模块
        # Python 的 import 系统会检查 sys.modules，但如果 reload 失败，
        # 下面的 import 会使用已更新的 sys.modules 条目
        for mod_name in _verify_modules:
            try:
                if mod_name not in sys.modules:
                    importlib.import_module(mod_name)
            except Exception:
                pass

        from core.verify_engine import VerifyEngine
        from core.verify_engine.scenarios import load_scenarios

        # ── 阶段1+2: Planner↔场景验收闭环（2026-08-28）──
        # 场景验收（绝对 navigate URL/完整性）失败 → 写 REPLAN_FEEDBACK.md 退回
        # plan 阶段重新生成，上限 2 次重排；连续失败保持 implemented + error
        # 可见（验收失败属环境/任务书问题，绝非产品缺陷，绝不流转 bug-found）。
        verify_dir = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name
        )
        replan_left = 2
        replan_feedback = None
        # fix-replan-feedback-injection：上一轮验收错误原文——连续两轮一字不差说明
        # planner 未消费反馈（重跑即纯烧钱），升级为 ERROR 提示人工关注。
        prev_replan_error = None
        report = None
        app_reachable = True
        reach_note = ""
        # ── 场景冻结复用（scenario-reuse-on-reenter，2026-09-04）──
        # 冻结集一经生成即跨轮一致的量尺：重入验证（打回/修复轮/重试）直接
        # 复用，绝不重新出题——planner 单轮 2h/30M token 级成本只支付一次。
        # 冻集变更的唯一通道：admin 裁决（扩展/豁免）或人工删除冻结文件批准
        # 重新出题。首次进入（无冻结文件）走下方 planner 设计闭环。
        frozen = self._load_frozen_scenarios(verify_dir)
        if isinstance(frozen, tuple) and frozen[0] == "corrupt":
            self._pm.logger.error(
                "pm_engine",
                f"冻结场景文件验收失败 '{spec_name}' — 场景一经冻结跨轮一致，"
                f"变更须 admin 裁决，不自动重新出题",
            )
            # frozen-scenario-schema-migration 1.2：升级告警附字段级差异清单
            # （场景 id/下标/缺失字段），admin 可凭差异精准修复冻结文件，
            # 不再给笼统 corrupt 盲修。
            detail = frozen[1] if len(frozen) > 1 else ""
            self._escalate_env_blocked(
                spec_name,
                ["冻结场景文件损坏或验收失败。处置选项：① 确认场景集已过时 → "
                 f"删除 .fenix/verify-progress/{spec_name}/test_scenarios.json "
                 "批准重新出题；② 文件可修复 → 修复后保持冻结。",
                 f"验收差异清单：{detail[:600]}" if detail else "验收差异清单：无"],
                title="场景计划争议",
            )
            return
        while True:
            if frozen is not None:
                # ── 冻结复用：跳过整段出题，覆盖缺口按计划争议升级 ──
                self._pm.logger.info(
                    "pm_engine",
                    f"[阶段1] 场景冻结复用（{len(frozen)} 个场景），跳过重新出题: "
                    f"{spec_name}",
                )
                cov = self._pm._apply_interaction_contract(spec_name)
                if cov is not None and not cov.get("ok"):
                    self._pm.logger.error(
                        "pm_engine",
                        f"冻结场景覆盖缺口 '{spec_name}'（修复新增可交互元素？）"
                        f"— 场景变更须 admin 裁决，不自动重排: {cov.get('uncovered')}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [f"冻结场景未覆盖可交互元素: {cov.get('uncovered')}。"
                         "处置选项：① 扩展冻结场景集；② 声明纯展示；"
                         "③ 删除冻结文件批准重新出题。"],
                        title="场景计划争议",
                    )
                    return
                # 覆盖完整 → 落入下方阶段2（共享执行段）
            else:
                if replan_feedback is not None:
                    fb = verify_dir / "REPLAN_FEEDBACK.md"
                    fb.parent.mkdir(parents=True, exist_ok=True)
                    fb.write_text(
                        "# 场景验收反馈（上一轮未通过，必须逐条修正）\n\n"
                        + replan_feedback
                        + "\n\n重新输出全部场景；navigate 的 value 必须为绝对 URL。\n",
                        encoding="utf-8",
                    )
                # ── 阶段1 派 run 前状态重查（fasttrack-orphan-planner-race）──
                # D6 入口检查只覆盖 pipeline 进入时刻；竞态窗口内 fast-track
                # advance（_fast_track_advance_to_verified）可能已把 spec 推过
                # verified/done/pushed——此刻再派 planner run 即成孤儿
                # （2026-09-08 fix-verify-cli-cwd-isolation：已 pushed 后场景生成
                # run 白跑 14min）。非 testing 一律丢弃，与 D6 同语义（注明当前
                # 状态，不迁移不回退不派发）；replan 重排轮次同样经过本检查点。
                _stage1_status = (
                    self._pm.state_machine.read_one(spec_name) or {}
                ).get("status", "")
                if _stage1_status != "testing":
                    self._pm.logger.warning(
                        "pm_engine",
                        f"[阶段1] Planner 派发前状态重查丢弃 '{spec_name}': spec is "
                        f"'{_stage1_status}', not testing at planner dispatch — "
                        "dropped (orphan-planner guard)",
                    )
                    return
                self._pm.logger.info("pm_engine", f"[阶段1] Planner 生成场景: {spec_name}")
                # 路由地图前置生成（add-planner-efficiency：planner-route-map 1.1）：
                # 阶段1 进入处接入，对 impl worktree 生成/复用路由地图（HEAD 键控、
                # fail-open——生成器缺失/失败不阻塞）。planner 出题 prompt 组装前
                # 的最终保障在 runner 的 worktree 创建点，此处为前置早生成。
                self._pm.agent_runner.ensure_planner_route_map(spec_name)
                plan_result = self._pm.agent_runner.run_planner(spec_name, "plan")

                if not plan_result.success:
                    # ── 人工取消 hold-state（add-run-cancel D4）──
                    # planner run 被取消：spec 保持 testing 原状，只写 error，
                    # 不流转 bug-found、不降级 legacy、不入队。
                    if getattr(plan_result, "cancelled", False):
                        p_err = plan_result.error or ""
                        cancelled_err = (
                            f"run 被人工取消：{p_err}" if p_err else "run 被人工取消"
                        )
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": cancelled_err,
                            # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                            "_cancelled_hold": True,
                        })
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Planner plan run 被人工取消 — hold-state '{spec_name}' "
                            f"(保持 testing): {cancelled_err}",
                        )
                        return
                    # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
                    # 熔断期 planner 派发失败属「provider 故障」，不是验证逻辑失败：
                    # 不得 raise（会触发 legacy 降级 → bug-found → 伪 fix 级联），
                    # 保持 spec 在 implemented（由 full_scan recovery 兜底重排）。
                    if plan_result.error and "provider circuit open" in plan_result.error:
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": plan_result.error,
                        })
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Provider circuit open — planner suppressed for '{spec_name}', "
                            f"holding implemented: {plan_result.error}",
                        )
                        return
                    raise RuntimeError(f"Planner plan 失败: {plan_result.error}")

                # 验证 Planner 是否成功生成场景文件
                plan_read = self._pm._read_planner_result(spec_name)
                # fix-verdict-read-failclosed：plan 结果不可读（缺失/非法/白名单外）
                # 与「非 plan-ready」同判——阶段1 本就 fail-closed（≠plan-ready 即
                # 降级 legacy），不可读绝不等于「场景已生成」（fail-open 的反面）。
                if not plan_read.ok or plan_read.status != "plan-ready":
                    # fix-planner-invalid-output-alert：planner run 成功收工却无有效产出
                    # ＝ 整轮 planner 时长/成本白烧，必须显式留痕（error 字段 + ERROR 级
                    # 日志），否则只在降级 WARNING 里一笔带过，浪费不可见。
                    plan_status_text = (
                        f"不可读({plan_read.reason}: {plan_read.detail})"
                        if not plan_read.ok else f"'{plan_read.status}'"
                    )
                    self._pm.state_machine.update_spec(spec_name, {
                        "error": (
                            f"Planner 场景生成无效（status={plan_status_text}，run="
                            f"{plan_result.run_id}，{plan_result.duration_seconds / 60:.1f}min）"
                            f"— 降级旧版验证流程"
                        ),
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"Planner 未生成有效场景 '{spec_name}'（status={plan_status_text}，"
                        f"run={plan_result.run_id}，白烧 "
                        f"{plan_result.duration_seconds / 60:.1f}min）— 降级旧版 verifier",
                    )
                    # add-planready-artifact-gate D3：降级前落盘上下文
                    # （供 verify_report 合成路径注入降级标注，G3）。
                    self._write_degrade_context(
                        spec_name,
                        reason=(
                            f"Planner 未生成有效场景，status={plan_status_text}"
                        ),
                        run_id=plan_result.run_id,
                        duration_seconds=plan_result.duration_seconds or 0,
                    )
                    raise RuntimeError(f"Planner 未生成有效场景，status={plan_status_text}")

                # add-planready-artifact-gate D3：plan-ready 校验通过（新一轮验证
                # 正常启动）→ 删除陈旧 degrade_context.json，防旧降级事实污染后续
                # 正常报告（成功时才清理，失败/重验路径历史留痕）。
                self._clear_degrade_context(spec_name)

                # ── 契约只读一致性检查（planner-contract-findings，design D4）──
                # planner-plan 产物验收通过后（出题完成处）：对验证契约做只读
                # 一致性检查并落盘 contract_findings.json（fail-open，不阻断
                # 出题——契约检查与场景生成相互独立）。
                self._run_contract_static_check(spec_name)

                # ── 场景集冻结（add-verify-scenario-freeze）──
                # 首轮写入 / 修复轮 diff 校验（design D3：确定性，planner 不可绕过）。
                # 在场景执行前应用：以持久化集约束 planner 产出，缺场景补齐后继续验证。
                # （冻结复用路径不经过此处——冻结集即原班场景，无需再约束产出。）
                try:
                    freeze_result = self._pm._apply_scenario_freeze(spec_name)
                except Exception as e:
                    # 冻结逻辑属辅助治理，绝不阻断验证主流程
                    self._pm.logger.warning(
                        "pm_engine",
                        f"场景集冻结处理跳过 '{spec_name}'（异常不阻断验证）: {e}",
                    )
                    freeze_result = None
                if isinstance(freeze_result, dict) and freeze_result.get("aborted"):
                    # ── 空集显式兜底（evo-planner-scenario-schema-alignment 3.5/3.7）──
                    # 写回合法子集后「全部非法」不再触发阶段2 load_scenarios 报错
                    # （既有退回路径依赖的正是该报错），空集信号经结构化返回值承载：
                    # 0 场景经 engine.run([]) 产出无 env_error 的全绿报告，会被洗白
                    # 门 fail-open 放行判 verified——MUST NOT 以 0 场景进入阶段2。
                    reject_detail = "、".join(freeze_result.get("rejected") or [])
                    fb_text = (
                        f"场景写前预校验整批拒绝：本轮 planner 产出全部非法"
                        f"（写盘前逐条预检，未生成任何可执行场景），共 "
                        f"{freeze_result.get('total', 0)} 条。逐条原因："
                        f"{reject_detail[:600]}。请按 prompt 注入段「场景断言/"
                        f"操作必填字段」的必填字段与合法样例修正后重新输出全部场景。"
                    )
                    if replan_left > 0:
                        replan_feedback = fb_text
                        replan_left -= 1
                        self._pm.logger.error(
                            "pm_engine",
                            f"场景集为空（写前预校验整批拒绝）'{spec_name}' — "
                            f"退回 plan 阶段（剩余重排 {replan_left} 次）: "
                            f"{reject_detail[:200]}",
                        )
                        continue
                    # 3.7 预算耗尽分支：MUST NOT 落入下方「预算耗尽即继续验证」
                    # fall-through（对空集即等于携 0 场景进入阶段2 执行与裁决）。
                    # 比照 env_error 退回的预算耗尽分支（verification.py:1929-1943）：
                    # 置 implemented + error 显式结束本轮，ERROR 留痕。
                    self._pm.state_machine.update_spec(spec_name, {
                        "status": "implemented",
                        "tester_run": None,
                        "error": (
                            f"场景写前预校验整批拒绝且重排预算耗尽（{replan_left} "
                            f"次用尽）: {reject_detail[:280]}"
                        ),
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"场景集为空且重排预算耗尽 '{spec_name}' — 显式结束本轮"
                        f"（保持 implemented 等待人工），0 场景不进入阶段2: "
                        f"{reject_detail[:200]}",
                    )
                    return

                # ── 交互契约覆盖校验（add-interaction-contract-and-per-assert-triage 1.3）──
                # 可交互元素既无场景覆盖又无纯展示声明 → 写反馈退回 plan 补齐
                # （复用场景验收退回路径）；重排预算耗尽后不阻断验证，违规留痕。
                contract = self._pm._apply_interaction_contract(spec_name)
                if contract is not None and not contract.get("ok"):
                    if replan_left > 0:
                        replan_feedback = contract.get("feedback") or ""
                        replan_left -= 1
                        self._pm.logger.warning(
                            "pm_engine",
                            f"交互契约覆盖不完整 '{spec_name}' — 退回 plan 阶段"
                            f"（剩余重排 {replan_left} 次）: {contract.get('uncovered')}",
                        )
                        continue
                    self._pm.logger.error(
                        "pm_engine",
                        f"交互契约重排预算耗尽 '{spec_name}' — 违规留痕继续验证: "
                        f"{contract.get('uncovered')}",
                    )

            # ── 契约消费期轻量自证（design D2）──
            # mtime 变化后的首验轮执行（serve 段合法性 + 现有实例 ready 鉴别力
            # 自检，不执行 prepare、不起实例）；自证失败 = 契约错误 fail-fast，
            # 不进入场景执行（场景执行数=0），走 verify_contract_missing 信号
            # 通道呼叫 Administrator。契约缺失/纯 cli 形态返回 None 天然放行。
            selfcheck_err = None
            try:
                from core.verify_contract import selfcheck_contract_light
                selfcheck_err = selfcheck_contract_light(
                    self._pm.project_root, self._pm.logger,
                    base_url=self._current_instance_base_url(spec_name))
            except Exception as e:
                # 自证自身异常 fail-open：不因自证代码缺陷牵连验证主流程
                self._pm.logger.warning(
                    "pm_engine",
                    f"契约轻量自证跳过 '{spec_name}'（异常不阻断验证）: {e}")
            if selfcheck_err:
                self._pm.logger.error(
                    "pm_engine",
                    f"契约轻量自证失败 '{spec_name}' — fail-fast 阻断场景执行: "
                    f"{selfcheck_err}")
                self._write_verify_contract_missing(
                    spec_name,
                    f"{selfcheck_err}（契约消费期轻量自证失败，场景执行数为 0）",
                    f"项目根={self._pm.project_root}; 自证类型=轻量(mtime 门+serve 段)"
                    f"+ready 鉴别力",
                    recommended_action=(
                        "Administrator 修正 .fenix/verify.yaml 验证契约：按错误信息"
                        "中的段落与原因修正（serve 段字段/static root 目录/ready 探针"
                        "配置），修正后 git 提交 → spec 复位 ready 触发重验证"),
                )
                self._escalate_env_blocked(
                    spec_name,
                    [selfcheck_err],
                    title="验证环境阻塞（契约轻量自证失败）",
                )
                return

            # ── 阶段2: 验证引擎执行 ──
            self._pm.logger.info("pm_engine", f"[阶段2] 验证引擎执行: {spec_name}")
            scenarios_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            # 场景文件验收失败（相对 URL/结构非法）＝ 明确的环境错误：
            # 退回 plan 阶段重新生成，不走 raise 穿透、更不判 bug-found。
            env_error = None
            report = None
            try:
                scenarios = load_scenarios(scenarios_path)
            except ValueError as e:
                env_error = f"场景文件验收失败: {e}"

            if env_error is None:
                # ── 阶段2.5: 应用可达性自愈（最终用户验证必选）──
                # 场景执行前确保应用可被浏览器访问；不可达时自动启动 commands.start、
                # 端口冲突换端口重试。自愈失败由下方验证门禁兜底，不静默判定通过。
                app_reachable, user_blocked, reach_note = self._pm._ensure_app_reachable(spec_name)
                self._pm.logger.info(
                    "pm_engine",
                    f"[阶段2] 应用可达性: {'OK' if app_reachable else '不可达'} — {reach_note or '无 navigate 依赖'}",
                )

                # ── 可达性自愈失败即本轮 fail-fast（add-verify-unreachable-failfast D1）──
                # 自愈失败（就绪探针超时 / prepare 失败 / 契约缺失）属确定性环境错误，
                # 继续跑整轮场景只会空转烧钱、由判定链末段兜底还易误拒。此处直接短路：
                # 场景执行数=0、不重读场景、不创建/运行 VerifyEngine、不退回 plan 重排，
                # 复用既有 _escalate_env_blocked 升级通道（落 blocked → 自动呼叫
                # Administrator → 连续 2 轮冻结转人工）。evidence 用 reach_note（已由
                # add-verify-preflight-gate D3 内嵌 boot.log 尾部）。user_blocked 守卫：
                # 「需用户参与（收验证码/登录）」预留判定位恒 False，将来实现后不得被
                # 短路自动判 blocked，故显式含 not user_blocked。
                if not app_reachable and not user_blocked:
                    self._pm.logger.error(
                        "pm_engine",
                        f"[阶段2] 应用不可达，本轮 fail-fast（场景执行数=0）'{spec_name}': "
                        f"{reach_note}",
                    )
                    self._escalate_env_blocked(
                        spec_name, [reach_note], title="验证环境阻塞（应用不可达）",
                    )
                    return

                # 自愈可能改写场景文件端口（planner 臆测端口 → 应用实际端口）：
                # 上方 load 先于自愈，内存场景仍持臆测端口，改写只落文件、对本次
                # 执行无效 → 全场景对失联端口 navigate 整轮伪失败
                # （add-v3-spec-detail-page：24 场景导航 localhost:8000 全灭）。
                # 故自愈后必须重读场景文件再执行。
                try:
                    scenarios = load_scenarios(scenarios_path)
                except ValueError as e:
                    env_error = f"自愈改写后场景文件验收失败: {e}"

            if env_error is None:
                # ── 场景静态缺陷扫描（add-scenario-defect-triage-gate D3）──
                # 在场景集冻结完成后、执行前调用：findings 只作情报落盘
                # （scenario_static_findings.json）+ judge prompt 定向注入，
                # fail-open——任何异常记 WARNING，不阻断验证执行。
                self._pm._run_scenario_static_check(spec_name)

                # 场景执行根：worktree 轮传入 serving worktree 根（CLI 步骤
                # 缺省 cwd 以此为准，seed 写入落验证树而非主树）；
                # 无 worktree 轮不传（回退主树 project_root，行为不变）。
                scenario_root = None
                _sv_cache = self.__dict__.get("_contract_static_servers", {})
                _sv_entry = _sv_cache.get(spec_name)
                if isinstance(_sv_entry, dict):
                    _wt_path = _sv_entry.get("wt_path")
                    if _wt_path:
                        scenario_root = Path(_wt_path)
                engine = VerifyEngine(
                    spec_name, self._pm.project_root, self._pm.logger,
                    self._pm.config, scenario_root=scenario_root,
                )
                # add-verify-parallel-backoff / design D1（读端）：spec attrs 的
                # `_verify_parallel_override` 非空时覆盖 max_parallel 配置值——
                # 该字段仅由 inconclusive 重验链路（连续 blocked-env 降档）写入、
                # 健康轮自动复位，构造签名不变，既有测试兼容。降档来源标记随
                # 引擎启动日志与 report 顶层 effective_parallel 透出（D3）。
                _parallel_override = (
                    self._pm.state_machine.read_one(spec_name) or {}
                ).get("_verify_parallel_override")
                if _parallel_override is not None:
                    try:
                        engine.max_parallel = int(_parallel_override)
                        engine._parallel_override_active = True
                    except (TypeError, ValueError):
                        self._pm.logger.warning(
                            "pm_engine",
                            f"降档并行度解析失败 '{spec_name}' "
                            f"(_verify_parallel_override={_parallel_override!r})，"
                            f"沿用配置并行度",
                        )
                # 契约统一供给 base_url（design verify-runner-engine base_url 统一供给）：
                # 取代「从候选场景 navigate 步骤文本正则考古」——serve 流程已知
                # 实例地址，直接分发各 Runner（web/api URL origin 改写依据、
                # 环境门探针定位依据）。无实例形态（纯 cli）为空串无害空操作。
                engine.base_url = self._current_instance_base_url(spec_name)
                report = asyncio.run(engine.run(scenarios))
                env_error = report.get("env_error")

            if env_error:
                # ── 重跑消费硬门（fix-frozen-scenario-orphan-reservoir D5）──
                # 验收失败退回 plan 重跑前，先比对上一轮错误清单：本轮错误与上轮
                # 相同或为上轮超集 → planner 未消费反馈，**不再 continue 重跑**
                # （重跑即纯烧钱），直接走 _escalate_env_blocked 分级升级
                # （blocked → admin 自动处置 → 阈值冻结转人工）。
                # 错误实质性消除（数量减少或主体变化）→ 预算内照常重跑。
                cur_items = self._extract_replan_error_items(env_error)
                prev_items = (self._extract_replan_error_items(prev_replan_error)
                              if prev_replan_error else None)
                if self._replan_errors_unconsumed(prev_items, cur_items):
                    self._pm.logger.error(
                        "pm_engine",
                        f"场景验收错误与上轮相同或为上轮超集 '{spec_name}' — "
                        f"planner 未消费反馈（{len(prev_items)} 条错误一条未消），"
                        f"拒绝重跑，升级 admin 自动处置: {env_error[:200]}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [f"场景验收连续失败且 planner 未消费反馈（错误清单与上一轮"
                         f"相同或为上轮超集，重跑即纯烧钱）。处置选项：① 修复场景"
                         f"文件（test_scenarios.json 写回须过结构校验门，且与 "
                         f"scenarios.json 同源坏条目同步清理，双文件一致）；"
                         f"② 删除冻结集批准重新出题。"],
                        title="场景计划争议",
                    )
                    return
                prev_replan_error = env_error
                if replan_left <= 0:
                    self._pm.state_machine.update_spec(spec_name, {
                        "status": "implemented",
                        "tester_run": None,
                        "error": (
                            f"场景验收连续失败（退回 plan 2 次仍不通过）: "
                            f"{env_error[:280]}"
                        ),
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"场景验收连续失败 '{spec_name}' — 保持 implemented 等待人工: "
                        f"{env_error}",
                    )
                    return
                if frozen is not None:
                    # 冻结复用路径：执行期场景异常不重新出题（量尺一致原则），
                    # 升级 admin 裁决
                    self._pm.logger.error(
                        "pm_engine",
                        f"冻结场景执行异常 '{spec_name}' — 不重新出题，升级 admin "
                        f"裁决: {env_error}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [f"冻结场景执行环境异常: {str(env_error)[:200]}"],
                        title="场景计划争议",
                    )
                    return
                replan_feedback = env_error
                replan_left -= 1
                self._pm.logger.warning(
                    "pm_engine",
                    f"场景验收未通过 '{spec_name}' — 退回 plan 阶段"
                    f"（剩余重排 {replan_left} 次）: {env_error}",
                )
                continue

            # 验收通过：清理反馈文件（下次全新验证不受旧反馈干扰）
            try:
                (verify_dir / "REPLAN_FEEDBACK.md").unlink()
            except OSError:
                pass
            break

        fail_count = report["summary"]["failed"] + report["summary"]["errors"]
        self._pm.logger.info(
            "pm_engine",
            f"[阶段2] 完成: {report['summary']['total']}场景, "
            f"{report['summary']['passed']}通过, "
            f"{report['summary']['warnings']}警告, "
            f"{fail_count}失败",
        )

        # ── 阶段2 验证门禁：应用不可达且场景全失败时不判定 verified ──
        # 最终用户验证为必选项：若自愈后应用仍不可达、0 场景通过，则本次验证
        # 并未真正触达最终用户可见功能，不得静默判定 verified/done；将问题与
        # 已尝试的解决方案写入 error 暴露（而非 "0通过/31失败" 却标完成）。
        if (not app_reachable
                and report["summary"]["passed"] == 0
                and fail_count == report["summary"]["total"]):
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": "blocked:app-unreachable",
                "error": f"验证无法执行（最终用户验证未完成）: {reach_note or '应用不可达'}",
            })
            self._pm.logger.error(
                "pm_engine",
                f"验证门禁: '{spec_name}' 应用不可达，未判定 verified — {reach_note}",
            )
            # 死端修复（admin 2026-09-07，notes-standalone-sync 卡 testing 事故）：
            # 此前的裸 return 使 spec 永久滞留 testing——blocked:app-unreachable
            # 标记全库无消费者，且冻结场景集路径（scenario-reuse-on-reenter）
            # 不会重新出题，BLOCKER CHECK 的 auto-recovery 只会原样重验并再次
            # 撞门禁，形成每 stuck_threshold 一次的无效静默重试循环。按冻结
            # 复用路径同款语义升级：blocked + 自动呼叫 Administrator 处置验证
            # 基建（场景 URL/serve 配置属 admin 职权，planner 无法自愈）。
            self._escalate_env_blocked(
                spec_name,
                [f"应用不可达，验证无法执行（冻结场景集下自动重验无效，需 admin "
                 f"修正场景 URL/serve 配置）: {(reach_note or '应用不可达')[:200]}"],
                title="验证环境阻塞",
            )
            return

        # ── 阶段2.6 环境性失联门禁（verify-environment-sanity-gate / design D2）──
        # 全批 blocked-env → inconclusive：回 testing 重派新 attempt，不判 bug-found、
        # 不产生 repeated_failures 信号。阻断后直接 return（跳过 judge / 终态判定）。
        if self._pm._handle_env_blocked_inconclusive(spec_name, report):
            return

        # ── 阶段2.7 全场景同因失败哨（2026-08-28）──
        # pass=0 且全部失败场景错误签名一致 → 疑环境/场景问题，呼叫 admin 介入
        # 判断；不判 bug-found、不派生 fix；连续 3 轮同因自动 blocked。
        if self._pm._detect_uniform_verify_failure(spec_name, report):
            return

        # ── 阶段3 快道：全绿机械 verified（judge 效率治理 2026-09-06）──
        # 0 失败且 0 警告时 judge 无信息增量（无分类对象；洗白门禁仅在
        # 「0 通过或 env 失败」可触发，全绿恒无违规）——跳过 LLM 裁决
        # （常态 15-50 分钟），合成结果文件后走与 judge 完全同源的采纳
        # 尾段（进度核对/报告闸门/洗白门禁/transition）。tester_run 记
        # mechanical-all-green 留痕。
        judge_result = self._all_green_fast_path(spec_name, report, fail_count)
        if judge_result is None:
            # ── 阶段3: Planner 判定结果 ──
            self._pm.logger.info("pm_engine", f"[阶段3] Planner 判定: {spec_name}")
            judge_result = self._pm.agent_runner.run_planner(spec_name, "judge")

        if not judge_result.success:
            # ── 人工取消 hold-state（add-run-cancel D4，judge 同语义）──
            # judge run 被取消：spec 保持 testing 原状，只写 error。
            if getattr(judge_result, "cancelled", False):
                j_err = judge_result.error or ""
                cancelled_err = (
                    f"run 被人工取消：{j_err}" if j_err else "run 被人工取消"
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "error": cancelled_err,
                    # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                    "_cancelled_hold": True,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Planner judge run 被人工取消 — hold-state '{spec_name}' "
                    f"(保持 testing): {cancelled_err}",
                )
                return
            # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
            # 同阶段1：熔断期 planner judge 失败属「provider 故障」，
            # 不得 raise → legacy 降级 → bug-found → 伪 fix 级联。
            if judge_result.error and "provider circuit open" in judge_result.error:
                self._pm.state_machine.update_spec(spec_name, {
                    "error": judge_result.error,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Provider circuit open — planner judge suppressed for "
                    f"'{spec_name}', holding implemented: {judge_result.error}",
                )
                return
            # ── 首轮 frozen 让位分支（fix-verdict-retry-misattribution D4）──
            # judge 首次派发于冻结前、run 在飞期间 spec 被人工冻结、run 完成返回
            # frozen 失败：与 cancelled「保持 testing 只写 error」及 circuit-open
            # 「抑制」同型——INFO 留痕后静默退出，不 raise、不重派、不改状态。
            # 判据与 runner.py 派发门共用导出常量（design D3 文案同源）。
            if (judge_result.error or "").startswith(FROZEN_TERMINATED_ERROR_PREFIX):
                self._pm.logger.info(
                    "pm_engine",
                    f"Planner judge run 完成时 spec 已冻结 — 让位退出 '{spec_name}'"
                    f"（在飞 run 结果按 frozen 处置，不重派不改状态）: "
                    f"{judge_result.error}",
                )
                return
            raise RuntimeError(f"Planner judge 失败: {judge_result.error}")

        # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
        # judge run 完成时刻再次核对 spec 状态：在飞旧 verify run 完成时若 spec
        # 已被重置（stale-result 防护拨回 implemented / 并发新 attempt 已接管），
        # 结果按 DEBUG 静默丢弃——不走失败迁移、不触发 fallback 重派整轮 verifier
        # （02:13 事故：implemented→verified 被拒后回退转 testing 重派）。
        _apply_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
        if _apply_status != "testing":
            self._pm.logger.debug(
                "pm_engine",
                f"Stale/foreign verify result discarded for '{spec_name}' "
                f"(run {judge_result.run_id}, current state '{_apply_status}', "
                f"result verified) — spec no longer in testing, result dropped",
            )
            return

        # ── 阶段3+ 裁决证据分类校验与重试（add-verdict-evidence-taxonomy D1-D5；
        #    fix-verdict-retry-misattribution D1/D2/D5/D7）──
        # judge 已在 report.json 增强每个非 PASS 场景的 classification/evidence。
        # 此处确定性校验：不合规 → 走既有 judge 重试一次（同 run_planner 调用）；
        # 二次仍不合规 → cause=violations，blocked-env + 告警（与 verify-report-gate
        # 阻断语义一致，宁可不推进也不带病采纳）。重试派发被 frozen/取消拦截 =
        # 人工已接管 → 静默让位（零写入零告警）；派发失败/异常/产物丢失 → 温和
        # 处置不发 verdict_evidence_invalid。合规后按分类-状态映射强制重写 status（D3）。
        verdict_ret = self._pm._verify_verdict_evidence(spec_name, retry_judge=True)
        if not verdict_ret["ok"]:
            cause = verdict_ret.get("cause", "violations")
            violations = verdict_ret.get("violations") or []
            dispatch_error = verdict_ret.get("dispatch_error") or ""
            if cause == "batch_attribution_dedup":
                # ── 批量归因查重拒绝采纳（fix-verdict-dedup-resynthesis D1/D2）──
                # 查重拒绝已由 _verify_verdict_evidence 内部完成「落盘违规 →
                # 派发重合成 judge → 回灌校验」闭环；本分支仅剩的语义是「重合成
                # 预算耗尽已升级 blocked」——_handle_attr_dedup_rejection 已置
                # blocked + admin 告警，此处仅 WARNING 对账，不重复写 error。
                # report.json 实际已在盘上（judge 自己写的），拒绝的是状态机
                # 采纳而非落盘——不再「保持 testing 静默等待」（170 分钟自锁
                # 与全量重跑罚金的根因已消除）。
                detail = (violations[0].get("reason") if violations else "")
                self._pm.logger.warning(
                    "pm_engine",
                    f"批量归因查重拒绝采纳 '{spec_name}'（重合成预算耗尽）— "
                    f"已 blocked 等待人工裁决: {detail}",
                )
                return
            if cause in ("dispatch_frozen", "dispatch_cancelled"):
                # ── 让位语义（design D2 / fix-verdict-retry-misattribution）──
                # frozen 门/取消旗标 = 人工已接管：零写入（不 update_spec——不写
                # status/error、不触 _cancelled_hold）、不发任何人工升级告警；
                # 留痕已在上游方法内以 INFO 完成，此处补充采纳侧结论供日志对账。
                self._pm.logger.info(
                    "pm_engine",
                    f"裁决证据校验重试派发被"
                    f"{'取消旗标' if cause == 'dispatch_cancelled' else 'frozen 门'}"
                    f"拦截 '{spec_name}' — 让位：spec 保持 testing 原状，"
                    f"不写 blocked、不发告警（cause={cause}）",
                )
                return
            if cause == "dispatch_failed":
                # ── 派发故障温和处置（design D1）──
                # 网关拒绝/预算闸门等：写 error 留痕但不动 status、不写 blocked、
                # 不发 verdict_evidence_invalid（「二次违反证据契约」语义不得被
                # 派发故障冒用）；spec 保持 testing 等待下轮重验。
                self._pm.logger.warning(
                    "pm_engine",
                    f"裁决重试 judge 派发失败 '{spec_name}' — 保持 testing，"
                    f"留 error 待下轮重验: {dispatch_error}",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "error": f"裁决重试 judge 派发失败（非证据不合规）：{dispatch_error}",
                })
                return
            if cause == "dispatch_exception":
                # ── 异常早退（design D1 / D7）──
                # 上游已确保不复读旧 report.json、不打「重试后仍不合规」；此处
                # 同样不按违规处置——留 error 保持 testing，异常多属瞬态。
                self._pm.logger.error(
                    "pm_engine",
                    f"裁决证据校验重试异常早退 '{spec_name}' — 保持 testing，"
                    f"留 error 待下轮重验: {dispatch_error}",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "error": (
                        f"裁决重试 judge 异常（非证据不合规，未复检旧产物）："
                        f"{dispatch_error}"
                    ),
                })
                return
            if cause == "report_missing":
                # ── 重试成功但产物不可读（design D1）──
                # fail-closed：无法确定性校验合规即不推进，阻断交人工；信号沿用
                # 裁决结果不可读通道，不发 verdict_evidence_invalid（非违规判定）。
                self._pm.logger.error(
                    "pm_engine",
                    f"裁决重试 judge 成功但 report.json 不可读 '{spec_name}' — "
                    f"阻断为 blocked（fail-closed，不按违规处置）",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "blocked",
                    "error": (
                        f"验证裁决重试后 report.json 不可读（产物缺失，非证据不合规），"
                        f"已 blocked 等待人工裁决"
                    ),
                })
                self._pm._send_human_escalation_alert(
                    spec_name=spec_name,
                    signal_type="verdict_result_unreadable",
                    severity="critical",
                    description=(
                        f"'{spec_name}' 裁决重试后 report.json 不可读，已 blocked "
                        f"等待人工裁决（非证据不合规）"
                    ),
                    evidence=(
                        f"spec={spec_name}; cause=report_missing; report="
                        f".fenix/verify-progress/{spec_name}/report.json"
                    ),
                    recommended_action=(
                        "检查 judge 重试轮是否覆写/破坏了 report.json（产物门禁外的"
                        "缺失路径）；修复产物后重置验证或重跑"
                    ),
                )
                return
            if cause != "violations":
                # ── 未知 cause 保守处置（design risk：fail-closed）──
                # 前向兼容防护：枚举之外的 cause 值按 violations 同等保守处置
                # （blocked + 告警），并 ERROR 留痕——不静默放行。
                self._pm.logger.error(
                    "pm_engine",
                    f"裁决证据校验未知 cause '{cause}' '{spec_name}' — 按 violations "
                    f"保守处置（fail-closed）: {verdict_ret}",
                )
            # ── cause=violations（真·二次违规）：保留既有语义 blocked + 告警 ──
            # 本轮回合计入失败历史侧车（cause_type=evidence-invalid），供升级闸门
            # 分型与轮间 diff（fix-verdict-retry-misattribution D6）。
            self._pm._append_fail_history(
                spec_name, "evidence-invalid",
                [v.get("scenario_id") or v.get("id") or "?"
                 for v in violations if isinstance(v, dict)],
            )
            self._pm.logger.error(
                "pm_engine",
                f"裁决证据分类二次校验仍失败 '{spec_name}' — 阻断推进为 blocked-env"
                f"（{len(violations)} 项违规）",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "status": "blocked",
                "error": (
                    f"验证裁决证据分类校验连续失败：report.json 非 PASS 场景缺 "
                    f"classification/evidence，重试一次仍不合规（{len(violations)} 项"
                    f"违规），已 blocked 等待人工裁决"
                ),
            })
            self._pm._send_human_escalation_alert(
                spec_name=spec_name,
                signal_type="verdict_evidence_invalid",
                severity="critical",
                description=(
                    f"'{spec_name}' 验证裁决证据分类校验连续失败（{len(violations)} 项"
                    f"违规），已 blocked 等待人工裁决"
                ),
                evidence=self._verdict_violations_evidence(
                    spec_name, violations),
                recommended_action=(
                    "检查 planner-judge 是否遵守 prompt 第4步（对全部非 PASS 场景补 "
                    "classification/evidence）；人工重置后重跑验证"
                ),
            )
            return

        # ── 阶段3+ warning 连续悬置追踪与升级（design D4 / D5）──
        # 裁决采纳处更新连续计数侧车；达 2 轮的 warning 场景发 triage 升级告警，
        # 并写入下一轮 planner prompt 的优先复核清单（triage_recheck.json）。
        try:
            triage_hits = self._pm._update_warning_streaks(spec_name)
            if triage_hits:
                self._pm._warning_stale_triage_alert(spec_name, triage_hits)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"warning_streaks 更新跳过（异常不阻断采纳）'{spec_name}': {e}",
            )

        # 读取判定结果（fix-verdict-read-failclosed：结构化三态）
        verifier_result = self._pm._read_planner_result(spec_name)
        verifier_status = verifier_result.status if verifier_result.ok else None
        # ── 结果状态判据（fix-daemon-lifecycle-races D6，结果应用处最终核对）──
        # 前道守卫之后的取证校验/重试窗口内 spec 亦可能漂移，此处兜底：非 testing
        # → DEBUG 丢弃，不迁移/不派生/不重派。
        _apply_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
        if _apply_status != "testing":
            self._pm.logger.debug(
                "pm_engine",
                f"Stale/foreign verify result discarded for '{spec_name}' "
                f"(current state '{_apply_status}', result {verifier_status}) — "
                f"spec no longer in testing, result dropped",
            )
            return
        # ── 裁决不可读 → fail-closed（fix-verdict-read-failclosed D4）──
        # 结果文件缺失/非法 JSON/status 白名单外一律不得晋级 verified（历史事故：
        # add-verify-contract-autodraft 裸换行非法 JSON → None → else 分支 →
        # verified → done → auto-push）。处置：重派 judge 一次 → 复读；二次仍不可读
        # → blocked + critical 告警（含解析错误原文与结果文件完整路径），不推进
        # bug-found、不派生 fix。重试前复用入口状态判据（非 testing 丢弃，与
        # stale-result 防护同构，不新增竞态面）。
        if not verifier_result.ok:
            verdict_result_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            retry_status = (self._pm.state_machine.read_one(spec_name) or {}).get(
                "status", "")
            if retry_status == "testing":
                self._pm.logger.warning(
                    "pm_engine",
                    f"裁决结果不可读 '{spec_name}'（reason={verifier_result.reason}）"
                    f"— 重派 judge 一次后复读: {verifier_result.detail}",
                )
                retry_judge = self._pm.agent_runner.run_planner(spec_name, "judge")
                if retry_judge.success:
                    verifier_result = self._pm._read_planner_result(spec_name)
                    verifier_status = (
                        verifier_result.status if verifier_result.ok else None)
            if not verifier_result.ok:
                self._pm.logger.error(
                    "pm_engine",
                    f"裁决结果二次仍不可读 '{spec_name}' — 阻断为 blocked"
                    f"（reason={verifier_result.reason}）: {verifier_result.detail}",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "blocked",
                    "error": (
                        f"验证裁决结果文件不可读（重派 judge 一次后仍不可读，"
                        f"reason={verifier_result.reason}）：{verifier_result.detail}"
                    ),
                })
                self._pm._send_human_escalation_alert(
                    spec_name=spec_name,
                    signal_type="verdict_result_unreadable",
                    severity="critical",
                    description=(
                        f"'{spec_name}' 验证裁决结果文件不可读，已 blocked 等待人工裁决"
                        f"（reason={verifier_result.reason}）"
                    ),
                    evidence=(
                        f"spec={spec_name}; result_file={verdict_result_path}; "
                        f"parse_error={verifier_result.detail}"
                    ),
                    recommended_action=(
                        "检查 planner-judge 是否以合法 JSON 写入结果文件（字符串内换行/"
                        "引号/控制字符须转义，建议以代码 json.dump 生成而非手工拼接）；"
                        "修复文件后重置验证或重跑"
                    ),
                )
                return
        # ── 阶段3+ 场景原地修复通道（judge-scenario-repair）──
        # 测试场景文件自身也可能有缺陷（夹具未自建/步骤客观错误/依赖序缺失）。
        # judge 原地修复场景文件并申报 scenario-repaired：框架经冻结 diff 记账
        # （无理由移除会被确定性补齐——judge 无法靠删场景凑通过）后有界重入
        # 阶段2/3——serving 实例在同函数缓存中存续，重执行秒级。与既有通道
        # 分工：机械缺陷原地修（省一次完整出题）；覆盖级缺陷走交互契约退回
        # plan；测试 harness 代码缺陷走 bug-found fix 链。
        if verifier_status == "scenario-repaired":
            if _repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS:
                self._pm.state_machine.update_spec(spec_name, {
                    "error": (
                        f"judge 场景原地修复预算耗尽（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）"
                        f"— 保持 testing 等待下一轮重验，若仍场景缺陷将按既有升级路径处置"
                    ),
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' judge 场景修复预算耗尽 "
                    f"（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）— 不再重入",
                )
                return
            try:
                freeze_result = self._pm._apply_scenario_freeze(spec_name)
            except Exception as e:
                # 冻结记账属辅助治理，异常不阻断修复重入
                self._pm.logger.warning(
                    "pm_engine",
                    f"修复轮场景冻结记账跳过 '{spec_name}'（异常不阻断）: {e}",
                )
                freeze_result = None
            if isinstance(freeze_result, dict) and freeze_result.get("aborted"):
                # ── 空集显式兜底（evo-planner-scenario-schema-alignment 3.7）──
                # judge 原地修复后场景集为空（写前预校验整批拒绝）：MUST 拒绝
                # 本次重入、保持原状并留痕，MUST NOT 以空集或未过滤文件继续
                # 进入阶段2（0 场景报告会被洗白门 fail-open 放行判 verified）。
                reject_detail = "、".join(freeze_result.get("rejected") or [])[:400]
                self._pm.state_machine.update_spec(spec_name, {
                    "error": (
                        f"judge 原地修复后场景集为空（写前预校验整批拒绝，共 "
                        f"{freeze_result.get('total', 0)} 条）— 拒绝本次重入，"
                        f"保持 testing 待人工/下轮处置: {reject_detail}"
                    ),
                })
                self._pm.logger.error(
                    "pm_engine",
                    f"judge 场景修复后无合法场景 '{spec_name}' — 拒绝重入，"
                    f"0 场景不进入阶段2: {reject_detail}",
                )
                return
            self._pm.logger.info(
                "pm_engine",
                f"[阶段3+] judge 场景原地修复采纳 '{spec_name}' — 重入执行"
                f"（第 {_repair_depth + 1}/{_SCENARIO_REPAIR_MAX_ROUNDS} 次修复）",
            )
            return self._run_three_stage_verification(
                spec_name, _repair_depth=_repair_depth + 1)
        if verifier_status == "bug-found":
            # ── 归因分级门禁（add-verdict-credibility-gate / design D2 / Task 2.2）──
            # 打回依据全部为 speculative（推测级）时抑制 bug-found 打回：
            # 转重验一次或写 error「归因证据不足待人工复核」，不得带推测
            # 信号打回 implementer（B2/B7：宁可多一次重验也不可带假信号打回，
            # 本次事故直接教训）。
            if self._pm._speculative_bug_found_gate(spec_name):
                return
            # judge 自述环境问题守卫：judge 自己把根因描述为环境/基础设施问题时，
            # 属「验证没能发生」而非「验证发现了缺陷」，不得流转 bug-found
            # 派生伪 fix 级联（admin 处置 2026-08-28 failover 相对 URL 伪失败实证）。
            if self._pm._judge_bugs_declare_env(spec_name) and self._pm._handle_judge_env_declared(spec_name):
                return
            # ── 场景缺陷改道门（add-scenario-defect-triage-gate D1/D2/D3）──
            # judge 申报 bug-found 后、打回 implementer 前，读 report.json 场景
            # classification 分布：非 PASS 场景全部显式 test-defect/flaky 且
            # product-bug=0 → 纯场景缺陷清单，拒绝打回 implementer（不再烧实现轮
            # 修场景文件——add-spec-status-modal-budget 事故的直接教训），定向重派
            # judge 一次走 scenario-repaired 原地修复通道。None/未知值/含任一
            # product-bug 一律不走改道（保守，D1）。重派计入 _SCENARIO_REPAIR_
            # MAX_ROUNDS 预算（与 scenario-repaired 重入共用 _repair_depth）。
            if self._pm._scenario_defect_reroute_gate(
                    spec_name, _repair_depth, judge_result):
                return
            # 验证报告产物闸门（add-verify-report-gate）：裁决 Agent 漏写报告时
            # 由框架合成兜底，合成失败则阻断推进（下游修复引用的路径必然可读）
            report_blocker = self._pm._ensure_verification_report(spec_name)
            if report_blocker:
                self._pm.state_machine.update_spec(spec_name, {
                    "error": report_blocker,
                })
                self._pm.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止推进 bug-found — {report_blocker}",
                )
                return
            self._pm.state_machine.transition(spec_name, "bug-found")
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": judge_result.run_id,
                "error": "Verification found bugs — see verification report",
                # 明确非环境性失联：复位 inconclusive 计数（环境恢复后从零重算）
                "_inconclusive_attempts": 0,
                # add-verify-parallel-backoff / design D2：bug-found 属健康轮
                # 判定（非 inconclusive），降档并行度同轮复位。
                "_verify_parallel_override": None,
            })
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3）
            self._pm._render_scenario_change_section_to_report(spec_name)
            self._pm.logger.warning(
                "pm_engine",
                f"Verifier found bugs in '{spec_name}', transitioning to bug-found",
            )
            # ── 守卫二：spawn 抑制（fix-repair-lane-dedup / design 守卫二）──
            # 被验对象为 fix spec 且自身 ready/implementing（重实现已在飞）时，
            # 跳过派生子 fix——由在飞重实现承载修复。
            if self._pm._is_fix_spec(spec_name):
                cur = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                if cur in ("ready", "implementing"):
                    self._pm.logger.info(
                        "pm_engine",
                        f"守卫二：'{spec_name}' 为 fix spec 且自身 {cur}"
                        f"（重实现在飞）——跳过派生子 fix",
                    )
                    self._pm.state_machine.update_spec(spec_name, {
                        "error": "修复由在飞重实现承载，跳过派生子 fix",
                    })
                    return
            self._pm._on_spec_bug_found(spec_name)
        else:
            # D6: testing→verified 前置进度核对：done>=total 才晋级
            vblocker = self._pm._check_verification_gate(spec_name)
            if vblocker:
                # 不完整：按 verifier 失败处理，写 error 摘要，不晋级 verified
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": judge_result.run_id,
                    "error": vblocker,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"验证未完成 '{spec_name}'，阻止晋级 verified: {vblocker}",
                )
                return
            # 验证报告产物闸门（add-verify-report-gate）
            report_blocker = self._pm._ensure_verification_report(spec_name)
            if report_blocker:
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": judge_result.run_id,
                    "error": report_blocker,
                })
                self._pm.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止晋级 verified — {report_blocker}",
                )
                return
            # verified 洗白门禁（help-center 0/15 verified 事故防线）：
            # 0 通过或 env 失败不得放行，升级 admin 处置
            if not self._pm._env_whitewash_gate(spec_name):
                return
            self._pm.state_machine.transition(spec_name, "verified")
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": judge_result.run_id,
                "error": None,
                "_inconclusive_attempts": 0,
                # add-verify-parallel-backoff / design D2：verified 属健康轮，
                # 降档并行度同轮复位（与 _inconclusive_attempts 同生命周期）。
                "_verify_parallel_override": None,
                # add-fail-counter-budget D1：验证 PASS 是 _verify_fail_rounds
                # 的唯一归零点——跨修复周期累计的失败计数在此清零并持久化，
                # 打回重派/修复收工等中间转换不再归零（见 _do_spec_bug_found）。
                "_verify_fail_rounds": 0,
                # fix-daemon-lifecycle-races D3：验证自然通过（verified 落定）是
                # _verify_redo_count（重启恢复重验计数）的清零点，与
                # _verify_fail_rounds 清零点对齐；人工 unfreeze_spec 亦清零。
                "_verify_redo_count": 0,
                # add-blocked-reverify-lane D3：env 阻塞轮次唯一自动清零点=验证
                # 通过（与 _verify_fail_rounds PASS 唯一归零点同语义）；处置复位/
                # 恢复/fix 链等中间转换不清零。
                ENV_BLOCK_ROUNDS_FIELD: 0,
            })
            # 失败历史侧车随 verified 终态清空（fix-verdict-retry-misattribution D6）
            self._pm._clear_fail_history(spec_name)
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3）
            self._pm._render_scenario_change_section_to_report(spec_name)
            self._pm._on_spec_verified(spec_name)


    def _verifier_error_is_infra(self, error_text: str) -> bool:
        """verifier 失败是否属基础设施类（不得流转 bug-found）。

        覆盖：provider 熔断抑制、failover 链耗尽（chain exhausted）、
        classify_switch_error 可识别的切换类错误（unrecognized_model/5xx/网络）。
        此类失败说明「验证没能发生」，不是「验证发现了缺陷」。
        """
        if not error_text:
            return False
        if "provider circuit open" in error_text or "chain exhausted" in error_text:
            return True
        try:
            # 严格 is True：分类器返回非布尔（如测试桩）时按非基础设施处理
            return self._pm.agent_runner.classify_switch_error(error_text) is True
        except Exception:
            return False


    def _verifier_result_is_stale(self, result, result_path: Path, spec_name: str) -> bool:
        """verifier 结果文件是否不可信（陈旧重放 / 异 spec 残留 / 缺失）。

        判据（任一命中即陈旧）：
        - run_id 内嵌 epoch 早于文件 mtime 之前 5 秒以上 → 本轮验证器未曾写回；
        - 文件缺失却宣称成功 → 判定来源不明；
        - 文件 spec 戳与当前 spec 不符 → 其它 spec 的残留。
        无法解析 run_id 时不判定（维持既有行为，向后兼容）。
        """
        import re
        try:
            m = re.search(r"-(\d{10,})-a\d+$", getattr(result, "run_id", "") or "")
            if not m:
                return False
            run_start = int(m.group(1))
        except (TypeError, ValueError):
            return False
        if not result_path.exists():
            return True
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return True
        if not isinstance(data, dict):
            return True
        stamped = data.get("spec")
        if isinstance(stamped, str) and stamped and stamped != spec_name:
            return True
        try:
            if result_path.stat().st_mtime < run_start - 5:
                return True
        except OSError:
            return True
        return False


    def _branch_commit_count(self, result) -> Optional[int]:
        """实现分支相对 main 的提交数（`git rev-list --count main..<branch>`）。

        单一来源（fix-fasttrack-resultfile-missing-redispatch D1）：供
        ``_implementation_branch_has_commits`` 与 ``_implementer_zero_change``
        共用。``result.branch`` 为空或 rev-list 失败/超时返回 None
        （调用方各自按 conservative fail-open 处置，不吞风险）。
        """
        import subprocess as _sp
        branch = getattr(result, "branch", None)
        if not branch:
            return None
        try:
            r = _sp.run(
                ["git", "rev-list", "--count", f"main..{branch}"],
                capture_output=True, text=True, timeout=15,
                cwd=str(self._pm.project_root),
            )
            if r.returncode != 0:
                return None
            return int(r.stdout.strip() or "0")
        except (OSError, ValueError, _sp.TimeoutExpired):
            return None

    def _implementation_branch_has_commits(self, result) -> bool:
        """实现分支相对 main 是否已有提交（`git rev-list --count main..<branch>` > 0）。

        Conservative fail-open：``result.branch`` 为空或 rev-list 失败/超时一律
        返回 False（→ 调用方走重派，不吞风险）。供 fast-track 死亡路径分流
        （dispatch._run_fast_track_flow）与 ``_implementer_zero_change`` 共用。
        """
        count = self._branch_commit_count(result)
        return count is not None and count > 0

    def _implementer_zero_change(self, spec_name: str, result) -> bool:
        """实现器零变更成功判定：分支零新提交 且 全程零 Edit/Write 工具调用。

        分支缺失（result.branch 为空）不判定（保持既有行为，向后兼容）。
        """
        branch = getattr(result, "branch", None)
        if not branch:
            return False
        count = self._branch_commit_count(result)
        if count is None:
            return False  # rev-list 失败/超时 → fail-open 不判零变更（既有语义）
        if count > 0:
            return False  # 有新提交 → 正常成功
        # 分支零提交，再看运行产物中是否有编辑类工具调用
        run_file = self._pm.project_root / ".fenix" / "runs" / f"{result.run_id}.jsonl"
        try:
            with run_file.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    for c in (d.get("message") or {}).get("content") or []:
                        if (isinstance(c, dict) and c.get("type") == "tool_use"
                                and c.get("name") in (
                                    "Edit", "Write", "MultiEdit", "NotebookEdit")):
                            return False
        except OSError:
            return False
        return True


    def _deliverable_gate_missing(self, spec_name: str, result) -> list:
        """交付物守卫：返回 SPEC 声明与实现分支现实的差异条目清单。

        纯文件存在性检查（add-implementer-deliverable-gate D3）：从 SPEC 目录
        提取声明路径，逐一在 ``result.branch`` 的 HEAD 提交中校验 blob 存在。
        校验基准为实现分支（worktree 已清理，仅分支留存）。

        提取器语义升级（add-deliverable-extractor-semantics）：仅
        ``deliverables``（新建交付物）参与缺件判定；``references``（既有文件
        引用）走软校验——缺失仅记审计日志（D4），不阻断、不重派、不改状态。
        路径按字面校验（``normalize_check_path`` 已退役为恒等映射：
        ``.fenix`` 自引用符号链接设计废弃后为实体目录，历史的前缀归一化
        会在根路径同名文件存在时把 ``.fenix/x`` 缺件假放行）。

        结构化返回（add-deliverable-delete-kind D3）：返回类型为
        ``list[dict]``，每项 ``{"path": str, "kind": str,
        "violation": "missing"|"undeleted"}``。``violation`` 语义由 ``kind``
        决定——``new``/``modify``：分支 HEAD 无该 blob → ``missing``；
        ``delete``：分支 HEAD 仍有该 blob → ``undeleted``（反判）。kind 来自
        声明段 ``extract_declared_entries``；正则回退路径无 kind 概念，统一
        按 non-delete 语义（缺失即 ``missing``）。

        Returns:
            差异条目列表；空列表表示放行（含无路径 SPEC 跳过场景）。
        """
        from core.deliverables import extract_declared, \
            extract_declared_entries, extract_paths_typed

        spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return []
        # 声明优先（planner 交付契约）：tasks.md 有 `## Deliverables` 段时做机械
        # 对账，不做正则语境猜测；无声明段回退 extract_paths_typed（向后兼容）。
        typed = extract_declared(spec_dir)
        decl_source = "declared"
        if typed is None:
            typed = extract_paths_typed(spec_dir)
            decl_source = "extracted"
        declared = typed["deliverables"]
        references = typed["references"]
        if not declared and not references:
            # 无路径 SPEC：跳过守卫，行为退化到守卫上线前（向后兼容）
            return []
        # kind 映射：声明段条目提供 path→kind（供反判 delete）；
        # 正则回退无 kind 概念，全部按 non-delete 语义（缺失即 missing）。
        kind_by_path: dict = {}
        if decl_source == "declared":
            for e in (extract_declared_entries(spec_dir) or []):
                kind_by_path[e["path"]] = e["kind"]
        wm = self._pm.agent_runner.worktree_manager
        branch = getattr(result, "branch", None)
        if not branch:
            # 无分支无法校验存活交付物：保守放行（与既有零变更哨共用缺失判定），
            # 交由零变更哨/merge 流程兜底
            return []

        def _exists_on_branch(path: str) -> bool:
            # 字面路径校验（.fenix 前缀归一化已退役，见本方法 docstring）
            return wm.file_exists_on_branch(branch, path)

        # 交付物（硬校验）：按 kind 区分违规类别——
        #   new/modify 缺失 → missing（既有一致行为）；
        #   delete 仍存在 → undeleted（反判，D3 结构化返回）。
        violations: list = []
        for p in declared:
            kind = kind_by_path.get(p, "new")
            if kind == "delete":
                if _exists_on_branch(p):
                    violations.append(
                        {"path": p, "kind": "delete", "violation": "undeleted"})
            else:
                if not _exists_on_branch(p):
                    violations.append(
                        {"path": p, "kind": kind, "violation": "missing"})
        violations.sort(key=lambda v: v["path"])

        # 引用（软校验，D4）：缺失仅审计留痕——引用错误不该阻断实现
        missing_refs = [p for p in references if not _exists_on_branch(p)]
        if missing_refs:
            self._pm.logger.warning(
                "deliverable-reference-missing",
                f"引用类路径在实现分支中不存在（仅审计留痕，不阻断）："
                f"{spec_name} -> {', '.join(missing_refs)}",
                context={"spec": spec_name, "branch": branch,
                         "source": decl_source,
                         "missing_references": missing_refs},
            )
        return violations

    def _tasks_md_relint_from_branch(self, spec_name: str, branch) -> list:
        """full 车道 tasks.md 收口复检：读实现分支 HEAD 版本并判定违规。

        基准 = 分支上的 tasks.md（merge 前主树版本 = 立项旧版本，读分支才反映
        中途编辑）。``git show`` 非零退出（路径不存在）→ fail-open 返回 ``[]``，
        与 lint「文件不存在不拦」语义一致（task-track relint fail-open）。
        """
        if not branch:
            return []
        try:
            proc = subprocess.run(
                ["git", "-C", str(self._pm.project_root), "show",
                 f"{branch}:spec/changes/{spec_name}/tasks.md"],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            self._pm.logger.warning(
                "pm_engine",
                f"tasks.md relint git show 失败（fail-open）'{spec_name}': {e}",
            )
            return []
        if proc.returncode != 0:
            # 路径不存在 → fail-open（fast-track 前置 spec 允许后补）
            return []
        from core.deliverables import lint_tasks_text
        return lint_tasks_text(proc.stdout)

    def _tasks_md_relint_from_worktree(self, spec_name: str, worktree_path) -> list:
        """fast-track 车道 tasks.md 收口复检：读 worktree 内版本并判定违规。

        path 不存在 → fail-open 返回 ``[]``（同晋升 lint「文件不存在不拦」语义）。
        任何异常 → WARNING + fail-open，不阻塞成功收口。
        """
        if worktree_path is None:
            return []
        try:
            tasks_file = (Path(worktree_path) / "spec" / "changes"
                          / spec_name / "tasks.md")
            if not tasks_file.exists():
                return []
            text = tasks_file.read_text(encoding="utf-8")
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"tasks.md relint 读取失败（fail-open）'{spec_name}': {e}",
            )
            return []
        from core.deliverables import lint_tasks_text
        return lint_tasks_text(text)

    def _disputed_deliverables(self, impl_result, missing) -> list:
        """实现 run 对缺件提出的 deliverable-dispute 异议与缺件清单求交。

        交互契约的 findings 通道（add-interaction-contract 泛化）：实现 run 认为
        某缺件路径实为运行时写入目标/既有引用而非本仓库交付物时，在
        ``.fenix-run-result.json`` findings 登记 ``deliverable-dispute`` 条目。
        守卫拒绝前先对账：命中异议的缺件**不得**自动重派（负反馈死循环会烧钱），
        由调用方转人工/裁决。

        element 与缺件路径按字面匹配（``normalize_check_path`` 已退役为
        恒等映射）。返回值为 dispute 命中路径列表（``list[str]``），供调用方
        按路径拼接 error 话术，不因 kind 区分。

        Args:
            impl_result: 实现 run 结果 dict（含 findings）。
            missing: 守卫返回的差异条目列表（``list[dict]``，每项含
                ``path``/``kind``/``violation``）。

        Returns:
            命中异议的缺件路径子集（保序）。
        """
        if not impl_result or not missing:
            return []

        disputed: list = []
        for f in (impl_result.get("findings") or []):
            if not isinstance(f, dict) or f.get("type") != "deliverable-dispute":
                continue
            el = str(f.get("element") or "").strip()
            if not el:
                continue
            for m in missing:
                # missing 现在是 list[dict]，按路径匹配（D5：dispute 按路径匹配，
                # 不因 kind 失效）
                m_path = m.get("path") if isinstance(m, dict) else str(m)
                if m_path == el and m_path not in disputed:
                    disputed.append(m_path)
        return disputed


    @staticmethod
    def _normalize_fail_signature(text: str) -> str:
        """归一化失败签名：数字→N、去引号、折叠空白，便于同因比较。"""
        import re as _re
        t = _re.sub(r"\d+", "N", text or "")
        t = _re.sub(r"['\"`]", "", t)
        return _re.sub(r"\s+", " ", t).strip()

    @staticmethod
    def _extract_replan_error_items(env_error: str) -> list[str]:
        """抽取场景验收错误文本中的逐条错误清单（消费硬门比对基准，D5）。

        场景文件验收错误文本（load_scenarios ValueError）形如：
            "场景文件包含 N 个错误:\n  - 场景'a'步骤0: ...\n  - ..."
        逐条抽取 "- " 前缀行作为错误项；无该形态（单条错误/其它来源）时
        退化为整段文本单条目，与既有「一字不差」比对语义同源。

        Returns:
            错误条目列表；env_error 为空返回空表。
        """
        if not env_error:
            return []
        items: list[str] = []
        for line in (env_error or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
        if items:
            return items
        return [env_error.strip()]

    @staticmethod
    def _replan_errors_unconsumed(prev_items: list, cur_items: list) -> bool:
        """消费硬门判定：本轮错误清单是否为上轮相同或超集（D5）。

        上轮错误逐条在本轮全部复现（相同或超集）→ True（planner 未消费反馈）；
        错误实质性消除（数量减少或主体变化）→ False。空清单不作判定（False）。
        """
        if not prev_items:
            return False
        return set(prev_items) <= set(cur_items)

    def _detect_uniform_verify_failure(self, spec_name: str, report: dict) -> bool:
        """全场景同因失败哨：pass=0 且全部失败场景错误签名一致 → 疑环境/场景问题。

        呼叫 admin 介入判断（verify_uniform_failure 信号，major）；不判
        bug-found、不派生 fix。连续 3 轮同因 → blocked 交人工。
        Returns: True 表示本轮已按同因失败处理（调用方跳过后续判定）。
        """
        summary = report.get("summary") or {}
        try:
            passed = int(summary.get("passed", 0) or 0)
            failed = int(summary.get("failed", 0) or 0)
            total = int(summary.get("total", 0) or 0)
        except (TypeError, ValueError):
            return False
        if passed != 0 or failed < 3:
            return False
        failed_scns = [s for s in (report.get("scenarios") or [])
                       if s.get("status") == "fail"]
        if len(failed_scns) < failed:
            return False  # 报告口径不一致，不哨
        sigs: set[str] = set()
        for s in failed_scns:
            sig = ""
            for a in (s.get("assertion_results") or []):
                if a.get("pass") is False:
                    sig = str(a.get("error") or "")
                    break
            if not sig:
                for st in (s.get("step_results") or []):
                    if st.get("success") is False:
                        sig = str(st.get("error") or st.get("detail") or "")
                        break
            sigs.add(self._pm._normalize_fail_signature(sig)[:80])
        if len(sigs) != 1:
            return False
        signature = next(iter(sigs))
        spec = self._pm.state_machine.read_one(spec_name) or {}
        try:
            attempts = int(spec.get("_uniform_fail_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        note = (f"全场景同因失败（{failed}/{total}，签名一致: \"{signature[:60]}\"）"
                f"——疑似环境或场景问题，已呼叫 admin 介入判断（第 {attempts} 次）")
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self._pm.project_root, self._pm.logger)
        try:
            store.append({
                "kind": SIGNAL,
                "signal_type": "verify_uniform_failure",
                "spec": spec_name,
                "severity": "major",
                "description": note,
                "evidence": f"signature={signature[:120]}; failed={failed}",
                "recommended_action": (
                    "判断失败类别：环境问题（实例/端口/构建）→ 修复后把 spec 拨回 "
                    "implemented 重验；场景/plan 问题 → 修正或重写场景；确认真实 "
                    "缺陷 → 人工处置。连续 3 轮同因将自动 blocked。"),
            })
        except Exception as e:
            self._pm.logger.error("pm_engine",
                              f"verify_uniform_failure 信号写入失败: {e}")
        updates: dict = {
            "error": note,
            "_uniform_fail_attempts": attempts,
        }
        if attempts >= 3:
            updates["status"] = "blocked"
            updates["tester_run"] = None
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.warning("pm_engine",
                            f"全场景同因失败哨触发 '{spec_name}': {note}")
        return True


    def _run_legacy_verification(self, spec_name: str):
        """降级方案：使用旧版单体 Verifier Agent。"""
        # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）：入口状态
        # 非 testing → DEBUG 丢弃（注明当前状态），不执行任何迁移/回退/重派。
        _entry_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
        if _entry_status != "testing":
            self._pm.logger.debug(
                "pm_engine",
                f"Verify result discarded for '{spec_name}': spec is "
                f"'{_entry_status}', not testing at legacy pipeline entry — dropped",
            )
            return

        result = self._pm.agent_runner.run_verifier(spec_name)

        # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
        # 熔断期 verifier 派发失败属「provider 故障」，不是真实验证失败：
        # 不得 transition bug-found / 调用 _on_spec_bug_found（否则会派生伪 fix
        # 级联，与 implementer 路径的 fix-fix-stashpop-deadlock 同理）。保持 spec
        # 在 implemented（由 full_scan recovery 兜底重排），写入 error 供 dashboard 可见。
        if getattr(result, "cancelled", False):
            # ── 人工取消 hold-state（add-run-cancel D4，legacy verifier）──
            # verifier run 被取消：spec 保持 testing 原状，只写 error，
            # 不流转 bug-found、不入队重派。
            v_err = result.error or ""
            cancelled_err = (
                f"run 被人工取消：{v_err}" if v_err else "run 被人工取消"
            )
            self._pm.state_machine.update_spec(spec_name, {
                "error": cancelled_err,
                # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                "_cancelled_hold": True,
            })
            self._pm.logger.warning(
                "pm_engine",
                f"Verifier run 被人工取消 — hold-state '{spec_name}' "
                f"(保持 testing): {cancelled_err}",
            )
            return
        if self._pm._verifier_error_is_infra(result.error):
            # 基础设施类失败（熔断/链耗尽/网关切换类错误）＝「验证没能发生」，
            # 不是「验证发现了缺陷」：保持当前状态不流转 bug-found、不派生 fix
            # （2026-08-28 chain_exhausted 误产空壳 fix 实证），由 full_scan
            # recovery 兜底重排；冷却到期后下一次扫描即恢复验证。
            self._pm.state_machine.update_spec(spec_name, {
                "error": result.error,
            })
            self._pm.logger.warning(
                "pm_engine",
                f"Verifier infra failure — holding '{spec_name}' state, "
                f"no bug-found: {result.error}",
            )
            return

        if result.success:
            # 环境性失联门禁（legacy 路径同样生效）：旧版 verifier 若在 report.json
            # 中标记了 blocked-env 且全批环境性失联，则同样判定 inconclusive 重派，
            # 不判 bug-found（防假阴性派生 fix 家族）。
            report = self._pm._read_verify_report(spec_name)
            if self._pm._handle_env_blocked_inconclusive(spec_name, report):
                return
            # fix-verdict-read-failclosed D5（legacy 同门）：结果文件读取优先
            # verify-progress/<spec>/.fenix-run-result.json（旧版 verifier 的
            # 确定性产物路径），回退主树共享 .fenix/.fenix-run-result.json（兼容
            # 旧行为：verifier 把结果写到 worktree 根、由 _execute_agent 复制到
            # 主树的情况）。主树共享文件会被 implementer 成功时残留
            # status=success/error 污染，读侧直接读它会把 implementer 残留当
            # 验证裁决（admin 处置根因，add-web-ui blocked_stuck 实证）——
            # 与 _read_planner_result 同源修正。
            run_result_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            if not run_result_path.exists():
                run_result_path = (
                    self._pm.project_root / ".fenix" / ".fenix-run-result.json")
            verifier_result = self._pm._read_verifier_result(run_result_path)
            verifier_status = (
                verifier_result.status if verifier_result.ok else None)
            # fix-verdict-read-failclosed D5（legacy 同门）：旧版 verifier 结果不可读
            # （缺失/非法 JSON/白名单外）→ blocked + critical 告警，绝不晋级
            # verified。legacy 是降级通道（三阶段两连败才进），结果不可读说明结构性
            # 异常而非偶发——自动重派整轮 verifier 只会烧钱，交人工。例外：status 白
            # 名单外（如 implementer 共享残留的 "success"）文件本身可读，须先走既有
            # 陈旧/归属护栏（foreign-spec 残留 → re-dispatch）再决定 blocked。
            if not verifier_result.ok:
                if verifier_result.reason == "unknown-status":
                    # 白名单外 status：文件可读，可能是共享文件中的其它 spec 残留
                    # 或 implementer 残留——走既有陈旧/归属护栏（检测 spec stamp
                    # 不符 / mtime 陈旧），foreign → re-dispatch 不 blocked。
                    if self._pm._verifier_result_is_stale(
                            result, run_result_path, spec_name):
                        self._pm.state_machine.update_spec(spec_name, {
                            "status": "implemented",
                            "tester_run": None,
                            "error": (
                                "stale/foreign verifier result replayed"
                                " — re-dispatching fresh verify"),
                        })
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Stale/foreign verifier result for '{spec_name}' — "
                            f"re-dispatching fresh verification",
                        )
                        return
                    # 文件属当前 spec 且 mtime 新鲜，但 status 白名单外 → blocked
                    self._pm.logger.error(
                        "pm_engine",
                        f"Verifier (legacy) status 白名单外 '{spec_name}' — "
                        f"阻断为 blocked（reason={verifier_result.reason}）: "
                        f"{verifier_result.detail}",
                    )
                    self._pm.state_machine.update_spec(spec_name, {
                        "status": "blocked",
                        "tester_run": result.run_id,
                        "error": (
                            f"Verifier (legacy) 结果文件 status 白名单外"
                            f"（reason={verifier_result.reason}）："
                            f"{verifier_result.detail}"
                        ),
                    })
                    self._pm._send_human_escalation_alert(
                        spec_name=spec_name,
                        signal_type="verdict_result_unreadable",
                        severity="critical",
                        description=(
                            f"'{spec_name}' legacy 验证裁决结果 status "
                            f"白名单外，已 blocked 等待人工裁决"
                            f"（reason={verifier_result.reason}）"
                        ),
                        evidence=(
                            f"spec={spec_name}; result_file={run_result_path}; "
                            f"parse_error={verifier_result.detail}"
                        ),
                        recommended_action=(
                            "检查旧版 verifier 结果文件 status 是否在 "
                            "verified/bug-found/plan-ready/scenario-repaired "
                            "白名单内；修复后人工重置验证"
                        ),
                    )
                    return
                # 缺失 / 非法 JSON → D5 直接 blocked（不可读属结构性异常，
                # 自动重派整轮 verifier 只会烧钱，交人工）。
                self._pm.logger.error(
                    "pm_engine",
                    f"Verifier (legacy) 结果不可读 '{spec_name}' — 阻断为 blocked"
                    f"（reason={verifier_result.reason}）: "
                    f"{verifier_result.detail}",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "blocked",
                    "tester_run": result.run_id,
                    "error": (
                        f"Verifier (legacy) 结果文件不可读（reason="
                        f"{verifier_result.reason}）：{verifier_result.detail}"
                    ),
                })
                self._pm._send_human_escalation_alert(
                    spec_name=spec_name,
                    signal_type="verdict_result_unreadable",
                    severity="critical",
                    description=(
                        f"'{spec_name}' legacy 验证裁决结果文件不可读，已 blocked "
                        f"等待人工裁决（reason={verifier_result.reason}）"
                    ),
                    evidence=(
                        f"spec={spec_name}; result_file={run_result_path}; "
                        f"parse_error={verifier_result.detail}"
                    ),
                    recommended_action=(
                        "检查旧版 verifier 是否以合法 JSON 写入结果文件；修复后"
                        "人工重置验证"
                    ),
                )
                return
            # 结果文件新鲜度/归属护栏：共享单文件会被任何 spec 的后续运行覆写，
            # 陈旧或异 spec 的判定重放到当前轮次 = 假 bug-found / 假 verified
            # （2026-08-28 improve-failover-model-mapping-ui 09:41 旧判定 12:21 重放实证）。
            if self._pm._verifier_result_is_stale(result, run_result_path, spec_name):
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "implemented",
                    "tester_run": None,
                    "error": "stale/foreign verifier result replayed — re-dispatching fresh verify",
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Stale/foreign verifier result for '{spec_name}' — "
                    f"re-dispatching fresh verification",
                )
                return
            if verifier_status == "bug-found":
                # 验证报告产物闸门（add-verify-report-gate，legacy 路径同闸门）
                report_blocker = self._pm._ensure_verification_report(spec_name)
                if report_blocker:
                    self._pm.state_machine.update_spec(spec_name, {
                        "error": report_blocker,
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"验证报告闸门: '{spec_name}' 阻止推进 bug-found — {report_blocker}",
                    )
                    return

                # verified 洗白门禁（help-center 0/15 verified 事故防线）：
                # 0 通过或 env 失败不得放行，升级 admin 处置
                if not self._pm._env_whitewash_gate(spec_name):
                    return
                # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
                # 结果应用前 spec 已非 testing（stale-result 防护拨回 implemented /
                # 并发新 attempt 已接管 / 其它状态漂移）→ DEBUG 丢弃，不走失败迁移
                # 与 fallback 重派（拆除旧 reconcile：implemented→testing→bug-found
                # 回放 + 重复派发整轮 verifier）。正常路径 spec 恒为 testing。
                _cur = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                if _cur != "testing":
                    self._pm.logger.debug(
                        "pm_engine",
                        f"Stale/foreign verify result discarded for '{spec_name}' "
                        f"(run {result.run_id}, current state '{_cur}', result "
                        f"bug-found) — spec no longer in testing, result dropped",
                    )
                    return

                # ── 归因分级门禁（legacy 路径同门禁，add-verdict-credibility-gate / D2）──
                if self._pm._speculative_bug_found_gate(spec_name):
                    return

                self._pm.state_machine.transition(spec_name, "bug-found")
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": result.run_id,
                    "error": "Verification found bugs — see verification report",
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：bug-found 属健康轮，
                    # 降档并行度同轮复位（legacy 路径同语义）。
                    "_verify_parallel_override": None,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Verifier (legacy) found bugs in '{spec_name}'",
                )
                # ── 守卫二：spawn 抑制（fix-repair-lane-dedup / design 守卫二）──
                if self._pm._is_fix_spec(spec_name):
                    cur = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                    if cur in ("ready", "implementing"):
                        self._pm.logger.info(
                            "pm_engine",
                            f"守卫二：'{spec_name}' 为 fix spec 且自身 {cur}"
                            f"（重实现在飞）——跳过派生子 fix（legacy 路径）",
                        )
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": "修复由在飞重实现承载，跳过派生子 fix",
                        })
                        return
                self._pm._on_spec_bug_found(spec_name)
            else:
                # D6: legacy 路径同样前置进度核对：done>=total 才晋级
                vblocker = self._pm._check_verification_gate(spec_name)
                if vblocker:
                    self._pm.state_machine.update_spec(spec_name, {
                        "tester_run": result.run_id,
                        "error": vblocker,
                    })
                    self._pm.logger.warning(
                        "pm_engine",
                        f"验证未完成 (legacy) '{spec_name}'，阻止晋级 verified: {vblocker}",
                    )
                    return
                # 验证报告产物闸门（add-verify-report-gate，legacy 路径同闸门）
                report_blocker = self._pm._ensure_verification_report(spec_name)
                if report_blocker:
                    self._pm.state_machine.update_spec(spec_name, {
                        "tester_run": result.run_id,
                        "error": report_blocker,
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"验证报告闸门: '{spec_name}' 阻止晋级 verified — {report_blocker}",
                    )
                    return

                # verified 洗白门禁（help-center 0/15 verified 事故防线）：
                # 0 通过或 env 失败不得放行，升级 admin 处置
                if not self._pm._env_whitewash_gate(spec_name):
                    return
                # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
                # 结果应用前 spec 已非 testing → DEBUG 丢弃，不走迁移与 fallback
                # 重派（拆除旧 reconcile：implemented→testing→verified 回放 +
                # 重派整轮 verifier）。02:13 事故即此路径：拨回 implemented 后在飞
                # 旧 judge 完成，结果被丢弃而非回退重派。
                _cur = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                if _cur != "testing":
                    self._pm.logger.debug(
                        "pm_engine",
                        f"Stale/foreign verify result discarded for '{spec_name}' "
                        f"(run {result.run_id}, current state '{_cur}', result "
                        f"verified) — spec no longer in testing, result dropped",
                    )
                    return

                self._pm.state_machine.transition(spec_name, "verified")
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": result.run_id,
                    "error": None,
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：verified 属健康轮，
                    # 降档并行度同轮复位（legacy 路径同语义）。
                    "_verify_parallel_override": None,
                    # add-fail-counter-budget D1：PASS 唯一归零点（legacy 路径同语义）。
                    "_verify_fail_rounds": 0,
                    # fix-daemon-lifecycle-races D3：验证自然通过清零点（legacy 同语义）。
                    "_verify_redo_count": 0,
                    # add-blocked-reverify-lane D3：env 阻塞轮次清零点（legacy 同语义）。
                    ENV_BLOCK_ROUNDS_FIELD: 0,
                })
                # 失败历史侧车随 verified 终态清空（legacy 同语义，
                # fix-verdict-retry-misattribution D6）
                self._pm._clear_fail_history(spec_name)
                self._pm._on_spec_verified(spec_name)
        else:
            self._pm.state_machine.transition(spec_name, "bug-found")
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": result.run_id,
                "error": f"Verifier agent failed: {result.error}",
            })


    @staticmethod
    def _load_frozen_scenarios(verify_dir: Path):
        """读取冻结场景集（scenario-reuse-on-reenter）。

        frozen-scenario-schema-migration：损坏判定携带字段级差异清单
        （load_scenarios ValueError 已含场景 id/下标/缺失字段），升级告警
        可凭差异精准修复，不再吞为笼统 corrupt。

        Returns:
            list[TestScenario]：冻结集有效（验收通过的原班场景）；
            None：无冻结文件（首次出题，走 planner 设计流程）；
            tuple ('corrupt', <差异清单文本>)：文件存在但验收失败（损坏/
            结构非法/为空）——场景一经冻结跨轮一致，变更须 admin 裁决，
            绝不静默重新出题。
        """
        from core.verify_engine.scenarios import load_scenarios
        path = verify_dir / "test_scenarios.json"
        if not path.is_file():
            return None
        try:
            scenarios = load_scenarios(path)
        except ValueError as e:
            return ("corrupt", str(e))
        except Exception as e:
            return ("corrupt", f"load_scenarios 非验收路径异常: {type(e).__name__}: {e}")
        if not scenarios:
            return ("corrupt", "冻结场景文件为空（无任何场景）")
        return scenarios

    def _env_whitewash_gate(self, spec_name: str) -> bool:
        """verified 推进前的洗白不变量门禁（help-center 0/15 verified 事故防线）。

        verdict=verified 但 0 通过或存在 env 分类失败 → 阻断推进并升级：
        阻塞 spec → 自动呼叫 Administrator 处置环境 → 连续
        ENV_BLOCK_FREEZE_THRESHOLD 轮仍 env → 结构化冻结转人工。
        Returns: True=放行推进 verified；False=已升级处置（调用方直接 return）。
        """
        from core.verdict_check import load_report, whitewash_violations
        scenarios = []
        report = load_report(self._pm.project_root, spec_name)
        if report:
            scenarios = report.get("scenarios") or []
        if not scenarios:
            # report.json 缺位时回退结果文件场景（fast-track 等价路径）；
            # 读取异常一律视为无数据（门禁不制造新的失败模式）
            try:
                ft = self._pm._read_implementer_result(spec_name) or {}
                # fix-impl-tasks-completion-gate D6：partial 是「诚实申报未完成」
                # 的合法终态——其 verification 段是未完成形态，不得当作 verified
                # 洗白门禁的场景证据采信（partial 轮不会走到 verified 推进，此处
                # 为 fail-safe 兜底：按无数据处理，交既有闸门拦截）。
                if ft.get("status") == "partial":
                    scenarios = []
                else:
                    verification = ft.get("verification")
                    if isinstance(verification, dict):
                        scenarios = verification.get("scenarios") or []
            except Exception:
                scenarios = []
        if not scenarios:
            return True  # 无场景数据不拦（保守放行，交既有闸门兜底）
        violations = whitewash_violations(scenarios, "verified")
        if not violations:
            return True
        self._pm.logger.warning(
            "pm_engine",
            f"verified 洗白门禁拦截 '{spec_name}': {'；'.join(violations)}",
        )
        self._escalate_env_blocked(spec_name, violations)
        return False

    def _escalate_env_blocked(self, spec_name: str, violations: list,
                              title: str = "验证环境阻塞") -> None:
        """阻塞升级通道：阻塞 spec → 自动呼叫 Administrator → 达阈值冻结转人工。

        help-center 事故语义（0/15 verified 被全量 env 豁免后推成 pushed）：
        env 失败绝不放行。首轮阻塞并自动呼叫 Administrator（依赖安装/服务
        重启/端口清理在其权限内），处置完成走既有重验证；连续 2 轮仍阻塞 →
        frozen 结构化冻结 + 人工升级告警——admin 权限也无法处理时唯一出口是
        人工介入。title 区分升级类别（验证环境阻塞 / 场景计划争议）。

        冻结转人工（fix-frozen-scenario-orphan-reservoir D5）：告警描述追加
        上轮 planner run 实际成本（tokens/费用/时长）作为「删除冻结集重新出题」
        的裁决参考。
        """
        try:
            spec = self._pm.state_machine.read_one(spec_name) or {}
            rounds = int(spec.get(ENV_BLOCK_ROUNDS_FIELD) or 0) + 1
            frozen = rounds >= 2  # 阈值：连续 2 轮阻塞 → 冻结转人工
            planner_cost = (self._last_planner_run_cost(spec_name)
                            if frozen else "")
            cost_note = (f"\n\n> 🪙 重新出题成本参考：{planner_cost}"
                         if planner_cost else "")
            error_msg = (
                f"{FREEZE_ERROR_PREFIX}{title}连续 {rounds} 轮，"
                f"admin 处置未奏效，转人工 — {'；'.join(violations[:3])}"
                f"{cost_note}"
                if frozen else
                f"{title}（第 {rounds} 轮）：{'；'.join(violations[:3])}"
            )
            entry = {
                "status": "blocked",
                "error": error_msg,
                ENV_BLOCK_ROUNDS_FIELD: rounds,
            }
            if frozen:
                entry["frozen"] = True
            self._pm.state_machine.update_spec(spec_name, entry)
            if frozen:
                self._pm.logger.error(
                    "pm_engine",
                    f"'{spec_name}' {title}连续 {rounds} 轮，已冻结转人工",
                )
            else:
                self._pm.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' {title}第 {rounds} 轮，自动呼叫 Administrator 处置",
                )
            # 自动呼叫 Administrator：与 Dashboard 手动 invoke 同一信号通道
            # （.fenix/admin_invoke_request.json，daemon 主循环拾取派发）
            try:
                from core.dashboard.data import request_admin_invoke
                inv = request_admin_invoke(self._pm.project_root, spec_name, (
                    f"{title}自动升级（verified 洗白门禁/场景冻结复用）：{error_msg[:300]}。"
                    "请诊断并处置——处置范围仅限环境修复（依赖安装、被测服务"
                    "/dashboard 重启、端口占用清理、验证产物重建、裁决场景集"
                    "变更）。环境问题不是产品缺陷：不要打回实现分支、不要修改"
                    "产品代码，不要手动 reset spec 状态。处置完成后，框架将自动"
                    "判定复位路径并触发重验证。"
                ))
                if isinstance(inv, dict) and inv.get("conflict"):
                    self._pm.logger.info(
                        "pm_engine",
                        f"'{spec_name}' 已有进行中的 Admin 处置，跳过重复呼叫",
                    )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' admin 自动呼叫失败（不阻塞升级）: {e}",
                )
            try:
                self._pm._send_human_escalation_alert(
                    spec_name=spec_name,
                    signal_type="verify_env_blocked",
                    severity="critical" if frozen else "warning",
                    description=error_msg[:300],
                    evidence=(
                        f"spec={spec_name}; "
                        f"report=spec/changes/{spec_name}/verification-report.md"
                    ),
                    recommended_action=(
                        # add-blocked-reverify-lane D2：处置收尾框架自动复位——
                        # admin 无需手动 reset spec 状态（手动 StateMachine 旁路
                        # 写法失去必要性）。未冻结：等待框架自动重验；已冻结：
                        # 人工检查环境后 unfreeze 清零重试（解冻即清零 rounds）。
                        "无需手动 reset spec 状态：处置完成并写入 result 后，框架"
                        "自动判定复位路径（实现分支已合并→直接重验 testing；"
                        "否则→ready 重实现）"
                        + (f"；已冻结转人工：请检查环境（依赖/服务/端口）后"
                           f"unfreeze_spec 清零重试"
                           + (f"；删除冻结集重新出题将重付出题成本"
                              + (f"（{planner_cost}）" if planner_cost else "") if frozen else "")
                           if frozen else "")
                    ),
                )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine", f"env 阻塞人工告警失败: {e}")
        except Exception as e:
            # 升级通道自身失败不得抛穿裁决流程
            self._pm.logger.warning(
                "pm_engine", f"env 升级通道异常 '{spec_name}': {e}")

    def _last_planner_cost_usd(self, spec_name: str) -> float | None:
        """最近一次 planner-plan run 的网关回传成本（degrade 上下文用，D3）。

        从验证链侧车 ``.fenix/verify-progress/<spec>/tokens.json`` 取最后一个
        agent_type=planner-plan 条目的 cost_usd。网关不回传时为 None（不伪造）。

        Returns:
            cost_usd 或 None（侧车缺失/无 planner 条目/回传为 None）。
        """
        tokens_json = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "tokens.json"
        )
        if not tokens_json.is_file():
            return None
        try:
            data = json.loads(tokens_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        runs = data.get("runs")
        if not isinstance(runs, list):
            return None
        for r in reversed(runs):
            if not isinstance(r, dict):
                continue
            if r.get("agent_type") != "planner-plan":
                continue
            cost = r.get("cost_usd")
            if cost is None:
                return None
            try:
                return float(cost)
            except (TypeError, ValueError):
                return None
        return None

    def _write_degrade_context(self, spec_name: str, reason: str, run_id: str,
                               duration_seconds: float) -> None:
        """降级前落盘 degrade 上下文（add-planready-artifact-gate D3）。

        新验证流程降级 legacy verifier 的判定点调用：把降级原因与被降级轮次
        代价（时长/成本）持久化到 ``.fenix/verify-progress/<spec>/degrade_context.json``，
        供 verify_report 合成路径注入降级标注（G3）。写失败不阻断降级主流程
        （WARNING 留痕，观测增强）。

        Args:
            spec_name: spec 名。
            reason: 降级原因归因文案（planner 阶段失败归因，如
                「Planner 未生成有效场景，status=不可读(missing: ...)」）。
            run_id: 被降级的 planner run id。
            duration_seconds: 被降级轮次的时长（秒）。
        """
        ctx_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "degrade_context.json"
        )
        cost_usd = self._last_planner_cost_usd(spec_name)
        payload = {
            "reason": str(reason or ""),
            "run_id": str(run_id or ""),
            "duration_seconds": (float(duration_seconds or 0)
                                 if duration_seconds else 0.0),
            "cost_usd": (float(cost_usd) if cost_usd is not None else None),
            "degraded_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            ctx_path.parent.mkdir(parents=True, exist_ok=True)
            ctx_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as e:
            # 观测量写入绝不分叉降级主流程：MagicMock 泄漏/路径不可写/类型
            # 非法统一 WARNING 留痕（design D3「写失败不阻断」）。
            self._pm.logger.warning(
                "pm_engine",
                f"degrade_context 落盘失败（不阻断降级）'{spec_name}': {e}",
            )

    def _clear_degrade_context(self, spec_name: str) -> None:
        """新验证流程成功路径删除陈旧 degrade 上下文（add-planready-artifact-gate D3）。

        plan-ready 校验通过后调用——覆盖旧降级事实，防陈旧标注污染后续正常报告
        （D3：成功时删除；失败/重验路径之外不清，历史留痕）。删除失败仅 WARNING
        （陈旧标注风险窗口极小，不阻断验证主流程）。
        """
        ctx_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "degrade_context.json"
        )
        try:
            if ctx_path.exists():
                ctx_path.unlink()
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"陈旧 degrade_context 清理失败 '{spec_name}': {e}",
            )

    def _last_planner_run_cost(self, spec_name: str) -> str:
        """最近一次 planner run 的实际成本摘要（冻结转人工告警的裁决参考，D5）。

        从 STATE 累计 ``_cost_usd``/``_tokens_in`` 与 ``.fenix/runs/`` 中该 spec
        最近一次 planner-plan 产物（``planner-plan-<spec>-*.jsonl``）取时长。
        任一来源缺失 → 返回空串（告警附注段 fail-open，不因取数失败阻断升级）。

        Returns:
            人类可读成本摘要（如 ``累计 $176.65 / 2.61亿 tokens；最近 planner
            run 5.3 小时``）；无数据返回空串。
        """
        spec = self._pm.state_machine.read_one(spec_name) or {}
        parts: list[str] = []
        try:
            cost = float(spec.get("_cost_usd") or 0)
            tokens_in = int(spec.get("_tokens_in") or 0)
            if cost > 0 or tokens_in > 0:
                cost_txt = f"${cost:.2f}" if cost > 0 else "费用未回传"
                tokens_txt = f"{tokens_in/1e6:.1f}M tokens" if tokens_in else "tokens 未记录"
                parts.append(f"累计 {cost_txt} / {tokens_txt}")
        except (TypeError, ValueError):
            pass
        try:
            runs_dir = self._pm.project_root / ".fenix" / "runs"
            if runs_dir.is_dir():
                candidates = sorted(runs_dir.glob(f"planner-plan-{spec_name}-*.jsonl"))
                if candidates:
                    last = candidates[-1]
                    duration_s = None
                    for line in last.read_text(encoding="utf-8",
                                               errors="ignore").splitlines():
                        try:
                            d = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        if isinstance(d, dict) and d.get("type") == "result":
                            dur = d.get("duration_ms")
                            if dur:
                                duration_s = float(dur) / 1000.0
                    if duration_s:
                        hours = duration_s / 3600.0
                        parts.append(f"最近 planner run {hours:.1f} 小时")
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass
        return "；".join(parts)

    def _all_green_fast_path(self, spec_name: str, report: dict, fail_count: int):
        """全绿快道（judge 效率治理 A，2026-09-06）：0 失败 0 警告 → 机械 verified。

        返回合成 ``AgentRunResult``（run_id=mechanical-all-green）供既有采纳
        尾段原样消费；返回 None = 存在失败/警告，走常规 judge。结果文件写
        primary 路径并**覆盖上一轮 judge 残留**（防 ``_read_planner_result``
        读到旧裁决）。

        fix-verdict-read-failclosed D6（fail-closed 语义反转）：写回失败**不得**
        静默 verified——快道产物是机械合成，写回失败极罕见，此时按「本轮无裁决
        产物」退化为常规 judge（返回 None），由 judge 补一轮真实裁决；绝无
        「按 verified 兜底」的旧语义（读侧缺失文件按通过放行即历史事故根因）。
        """
        summary = report.get("summary") or {}
        if (fail_count != 0
                or (summary.get("warnings") or 0) != 0
                or (summary.get("passed") or 0) <= 0):
            return None
        result_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / ".fenix-run-result.json"
        )
        text = (
            f"全绿快道: {summary.get('passed')}/{summary.get('total')} 场景通过、"
            "0 失败 0 警告——无分类对象，跳过 judge 机械 verified"
        )
        payload = {"spec": spec_name, "status": "verified", "bugs": [],
                   "summary": text, "mechanical": True}
        try:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError as e:
            # fix-verdict-read-failclosed D6：机械写回失败 → 退化常规 judge（返回
            # None），不得按 verified 兜底放行（历史 fail-open 语义已清除）。
            self._pm.logger.error(
                "pm_engine",
                f"全绿快道结果文件写回失败 '{spec_name}' — 退化为常规 judge: {e}",
            )
            return None
        self._pm.logger.info(
            "pm_engine", f"[阶段3] 全绿快道 '{spec_name}' — {text}")
        from core.agent_runner.runner import AgentRunResult
        return AgentRunResult(
            run_id="mechanical-all-green", spec_name=spec_name,
            agent_type="planner-judge", success=True, duration_seconds=0.0,
            output=text)

    def _persist_verdict_cache(self, spec_name: str, report: dict) -> None:
        """采纳成功后持久化跨轮裁决缓存（judge 效率治理 E，2026-09-06）。

        每个已裁决 non-PASS 场景记 {fingerprint, classification, evidence,
        assertion_triage}；下轮派发 judge 前由 prompt_builder 按指纹命中注入，
        命中场景免复现。每轮整体重写（场景消失/变化自然出清）；失败静默
        （fail-open，缓存缺失只导致下轮全量重裁，不影响正确性）。
        """
        from core.verdict_check import scenario_fingerprint, save_verdict_cache
        cache = {}
        for sc in report.get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            if sc.get("status") in ("pass", "passed"):
                continue
            cls = sc.get("classification")
            if not cls:
                continue  # 未裁决条目不入缓存
            fp = scenario_fingerprint(sc)
            if not fp:
                continue
            cache[str(sc.get("scenario_id"))] = {
                "fingerprint": fp,
                "classification": cls,
                "evidence": sc.get("evidence"),
                "assertion_triage": sc.get("assertion_triage"),
            }
        save_verdict_cache(self._pm.project_root, spec_name, cache)
        if cache:
            self._pm.logger.info(
                "pm_engine",
                f"跨轮裁决缓存已更新 '{spec_name}': {len(cache)} 个场景结论入缓存",
            )

    def _verdict_violations_evidence(self, spec_name: str, violations: list) -> str:
        """格式化 verdict_evidence_invalid 告警 evidence：携带结构化 violations 明细。

        fix-verdict-retry-misattribution D5：每条 `scenario_id + reason`，超过 20 条
        截断并注明总数——人工无需读 report.json 即可定位违规形状。
        """
        shown = [v for v in (violations or []) if isinstance(v, dict)][:20]
        parts = [
            f"spec={spec_name}",
            f"report=spec/changes/{spec_name}/verification-report.md",
            f"violations_total={len(violations or [])}",
        ]
        for v in shown:
            sid = v.get("scenario_id") or v.get("id") or "?"
            reason = str(v.get("reason") or "?").strip()
            parts.append(f"violation[scenario_id={sid}; reason={reason}]")
        if len(violations or []) > 20:
            parts.append(f"violations_truncated=20/{len(violations)}")
        return "; ".join(parts)


    # ── 批量归因查重拒绝 → 重合成闭环（fix-verdict-dedup-resynthesis D1/D2）──
    # 2026-09-10 事故解剖（proposal）：查重门拒绝后框架「保持 testing 等重合成」
    # 但**不存在重合成回路**（不 requeue、不落盘违规清单、重试 prompt 收不到
    # 查重要求）→ spec 卡 testing 170 分钟撞 stuck 阈值全量重跑。本闭环：
    # 落盘违规清单 → 派发轻量重合成 judge run → 回灌同一校验入口 → 连续 2 次
    # 重合成仍被拒 → blocked + admin 升级（MUST NOT 无限重试）。
    _RESYNTHESIS_DIRECTIVE_FILENAME = "dedup_resynthesis_directive.json"
    # 重合成预算：连续 2 轮重合成产物仍被查重拒绝 → 升级人工（design D2）。
    _RESYNTHESIS_MAX_ATTEMPTS = 2

    def _resynthesis_directive_path(self, spec_name: str) -> Path:
        return (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / self._RESYNTHESIS_DIRECTIVE_FILENAME
        )

    def _read_resynthesis_directive(self, spec_name: str) -> dict:
        """读取重合成指令（缺失/损坏返回 {}，fail-open）。"""
        try:
            path = self._resynthesis_directive_path(spec_name)
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    def _clear_resynthesis_directive(self, spec_name: str) -> None:
        """合规采纳后清除重合成指令（防下轮误注入）。写失败静默。"""
        try:
            self._resynthesis_directive_path(spec_name).unlink(missing_ok=True)
        except OSError:
            pass

    def _clear_requeue_manifest(self, spec_name: str) -> None:
        """合规采纳后清除回炉清单（add-judge-incremental-attribution 2.2）。

        场景级回炉闭环完成（整轮查重校验通过）后清理，防下轮误注入；写失败
        静默（manifest 缺失只导致下轮零注入，不影响裁决正确性）。
        """
        try:
            from core.verify_engine.judge_files import clear_requeue_manifest
            clear_requeue_manifest(self._pm.project_root, spec_name)
        except OSError:
            pass

    def _resynthesis_directive_scenarios(self, report: dict,
                                         violations: list) -> list:
        """提取被拒场景的差异化素材（重合成指令输入）。

        对违规组内每个 scenario_id，从 report 取：分类、状态、
        first_failed_step 原文、失败步骤序号、断言 label 清单——judge 改写
        归因文本时必须引用本场景局部数据（MUST NOT 套用共享模板串）。
        """
        from core.verdict_check import _extract_step_number
        involved = set()
        for v in (violations or []):
            if not isinstance(v, dict):
                continue
            for sid in (v.get("scenario_ids") or []):
                if sid:
                    involved.add(str(sid))
        rows = []
        for sc in report.get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("scenario_id") or sc.get("id") or "")
            if sid not in involved:
                continue
            evidence = sc.get("evidence") or {}
            ffs_text = ""
            if isinstance(evidence, dict):
                ffs = evidence.get("first_failed_step") or ""
                if isinstance(ffs, str):
                    ffs_text = ffs
            triage = sc.get("assertion_triage") or []
            labels = []
            if isinstance(triage, list):
                for t in triage:
                    if isinstance(t, dict):
                        assertion = str(t.get("assertion") or "").strip()
                        if assertion:
                            labels.append(assertion)
            rows.append({
                "scenario_id": sid,
                "classification": str(sc.get("classification") or ""),
                "status": str(sc.get("status") or ""),
                "first_failed_step": ffs_text,
                "failed_step_number": _extract_step_number(ffs_text),
                "assertion_labels": labels,
            })
        return rows

    def _write_resynthesis_directive(self, spec_name: str, report: dict,
                                     violations: list, rejection_round: int,
                                     resynthesis_attempts: int) -> None:
        """写重合成指令文件（fix-verdict-dedup-resynthesis D1）。

        内容：被拒场景清单（scenario_ids + reason）、逐场景现有归因文本与
        框架已掌握的场景局部数据（失败步骤序号 / 断言 label）作为差异化素材、
        拒绝计数（rejection_round / resynthesis_attempts，独立轻量计数落在
        verify-progress 目录，不膨胀 STATE.md）。写失败静默降级（只影响
        重合成 prompt 注入，不阻断闭环）。
        """
        try:
            payload = {
                "spec": spec_name,
                "rejection_round": rejection_round,
                "resynthesis_attempts": resynthesis_attempts,
                "violations": violations,
                "scenarios": self._resynthesis_directive_scenarios(
                    report, violations),
            }
            path = self._resynthesis_directive_path(spec_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), prefix=".resynth.", suffix=".json.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    f.flush()
                os.replace(tmp_path, path)
            except OSError:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"重合成指令写盘失败 '{spec_name}': {e}",
            )

    def _escalate_dedup_resynthesis(self, spec_name: str, rejection_round: int,
                                    violations: list) -> dict:
        """重合成预算耗尽（连续 2 轮重合成仍被拒）→ blocked + admin 升级告警。

        error 携带多轮违规摘要；spec 置 blocked 后自动链路对 status 的改写被
        update_spec 剥离（人工接管），MUST NOT 无限重试重合成。
        """
        summary = "; ".join(
            str(v.get("reason") or "")[:160] for v in (violations or []))
        error = (
            f"批量归因查重连续 {rejection_round} 次拒绝采纳"
            f"（含 {self._RESYNTHESIS_MAX_ATTEMPTS} 轮轻量重合成仍同文），"
            f"已 blocked 等待人工裁决（违规摘要: {summary}）"
        )
        self._pm.state_machine.update_spec(spec_name, {
            "status": "blocked",
            "error": error,
        })
        self._pm._send_human_escalation_alert(
            spec_name=spec_name,
            signal_type="verdict_dedup_resynthesis_exhausted",
            severity="critical",
            description=(
                f"'{spec_name}' 批量归因查重连续拒绝（含 {self._RESYNTHESIS_MAX_ATTEMPTS} "
                f"轮轻量重合成）已 blocked，等待人工裁决"
            ),
            evidence=(
                f"spec={spec_name}; rejections={rejection_round}; "
                f"违规摘要: {summary}"
            ),
            recommended_action=(
                "人工核查归因模板偷懒或级联豁免误判；修正归因后解除 blocked"
            ),
        )
        return {
            "ok": False, "cause": "batch_attribution_dedup",
            "violations": violations, "dispatch_error": "",
        }

    def _handle_attr_dedup_rejection(self, spec_name: str, report: dict,
                                     dedup_violations: list) -> dict:
        """批量归因查重拒绝统一收口（首轮 + 重试轮共用）。

        ``_verify_verdict_evidence`` 的查重拒绝处（首轮 + 重试轮）全部经此闭环：
          1. 落盘违规清单（``_write_verdict_violations``，重试 prompt 经
             ``_verdict_rejection_section`` 注入定向修复纪律）+ 写
             ``dedup_resynthesis_directive.json``（重合成指令：被拒场景清单 +
             逐场景现有归因 + 步骤序号/断言 label 差异化素材）；
          2. 派发轻量重合成 judge run（``run_planner(spec_name, "judge")``——
             复用既有 judge 重试通道，frozen 门/取消旗标/stale-result 防护/产物
             硬门全部免费继承），只重写被拒场景的归因文本字段，不重做调查/复现；
          3. 重合成产物回灌完整校验链（load_report → validate_report → 归因
             分级门 → 查重门，与既有路径同源、非旁路），合规按既有语义采纳
             （清 violations + 清 directive + 状态映射重写 + 裁决缓存）；
          4. 重合成产物仍被查重拒绝 → 连续拒绝计数递增（directive 文件
             resynthesis_attempts 字段），达预算上限（2 轮）→ blocked +
             admin 升级告警，MUST NOT 无限重试。

        Returns:
            {"ok", "cause", "violations", "dispatch_error"}（与
            ``_verify_verdict_evidence`` 同契约；cause=pass 时重合成已闭环
            采纳，其余 cause 由调用方按既有语义处置）。
        """
        from core.verdict_check import (
            validate_report, enforce_status_mapping, load_report, save_report,
        )
        prior = self._read_resynthesis_directive(spec_name)
        prior_attempts = int(prior.get("resynthesis_attempts") or 0) \
            if isinstance(prior, dict) else 0
        rejection_round = int(prior.get("rejection_round") or 0) \
            if isinstance(prior, dict) else 0
        rejection_round += 1

        # 1) 违规清单落盘（verdict_violations.json 通道，与既有校验违规同源）
        violations_entries = [{
            "scenario_ids": [str(s) for s in (v.get("scenario_ids") or [])],
            "reason": str(v.get("reason") or ""),
        } for v in (dedup_violations or [])]
        self._pm._write_verdict_violations(spec_name, violations_entries)

        # 预算上限（design D2：连续 2 次重合成仍被拒 → 升级人工，MUST NOT 无限重试）
        if prior_attempts >= self._RESYNTHESIS_MAX_ATTEMPTS:
            self._pm.logger.error(
                "pm_engine",
                f"批量归因查重拒绝采纳（重合成预算耗尽）'{spec_name}'（第 "
                f"{rejection_round} 次）— 升级 blocked 等待人工裁决",
            )
            return self._escalate_dedup_resynthesis(
                spec_name, rejection_round, violations_entries)

        # 2) 重合成指令落盘（含差异化素材与拒绝计数：本轮派发计数 = prior + 1）
        self._write_resynthesis_directive(
            spec_name, report, violations_entries,
            rejection_round=rejection_round,
            resynthesis_attempts=prior_attempts + 1,
        )
        self._pm.logger.warning(
            "pm_engine",
            f"批量归因查重拒绝采纳 '{spec_name}'（第 {rejection_round} 次，"
            f"已重合成 {prior_attempts} 轮）— 派发轻量重合成 judge run"
            f"（只重写被拒场景归因字段，禁止复现/调查/改判定）",
        )

        # 3) 派发重合成 judge（复用 judge 通道；异常立即早退，禁止复读旧 report）
        try:
            re_judge = self._pm.agent_runner.run_planner(spec_name, "judge")
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"重合成 judge 异常 '{spec_name}': {e}",
            )
            return {
                "ok": False, "cause": "dispatch_exception",
                "violations": violations_entries, "dispatch_error": str(e),
            }
        if re_judge is not None and not re_judge.success:
            if (re_judge.error or "").startswith(FROZEN_TERMINATED_ERROR_PREFIX):
                self._pm.logger.info(
                    "pm_engine",
                    f"重合成 judge 派发被 frozen 门拦截 '{spec_name}'"
                    f"（人工已冻结，让位不写状态）: {re_judge.error}",
                )
                return {
                    "ok": False, "cause": "dispatch_frozen",
                    "violations": violations_entries,
                    "dispatch_error": re_judge.error,
                }
            if getattr(re_judge, "cancelled", False):
                self._pm.logger.info(
                    "pm_engine",
                    f"重合成 judge 派发被取消旗标拦截 '{spec_name}'"
                    f"（run 已人工取消，让位不写状态）: {re_judge.error}",
                )
                return {
                    "ok": False, "cause": "dispatch_cancelled",
                    "violations": violations_entries,
                    "dispatch_error": re_judge.error,
                }
            self._pm.logger.warning(
                "pm_engine",
                f"重合成 judge 派发失败 '{spec_name}': {re_judge.error}",
            )
            return {
                "ok": False, "cause": "dispatch_failed",
                "violations": violations_entries,
                "dispatch_error": re_judge.error,
            }

        # 4) 重合成产物回灌完整校验链（与 _verify_verdict_evidence 既有路径同源）
        report2 = load_report(self._pm.project_root, spec_name)
        if report2 is None:
            return {
                "ok": False, "cause": "report_missing",
                "violations": violations_entries, "dispatch_error": "",
            }
        result2 = validate_report(report2)
        if not result2["ok"]:
            # 重合成产物在分类/证据层仍不合规（非查重）→ 既有「二次违规」处置
            self._pm.logger.error(
                "pm_engine",
                f"重合成产物证据分类仍不合规 '{spec_name}'："
                f"{[v['scenario_id'] for v in result2['violations']]}",
            )
            return {
                "ok": False, "cause": "violations",
                "violations": result2["violations"], "dispatch_error": "",
            }
        # 归因分级门 + 查重门（同一入口位，非旁路）
        try:
            from core.verdict_check import (
                validate_attribution_levels,
                enforce_blank_screenshot_direction,
                check_batch_attribution_dedup_scenario,
                load_verdict_cache,
                tag_cached_attributions,
            )
            validate_attribution_levels(report2)
            for sc in report2.get("scenarios") or []:
                if not isinstance(sc, dict):
                    continue
                new_cls = enforce_blank_screenshot_direction(sc)
                if new_cls:
                    old_cls = sc.get("classification")
                    sc["classification"] = new_cls
                    sc["blank_direction_forced"] = True
                    self._pm.logger.info(
                        "pm_engine",
                        f"白屏方向约束（重合成）'{spec_name}' 场景 "
                        f"{sc.get('scenario_id')}: classification "
                        f"'{old_cls}' → '{new_cls}'（blank_screenshot 标签强制 env 方向）",
                    )
            dedup2 = check_batch_attribution_dedup_scenario(report2)
            if not dedup2["ok"]:
                for v in dedup2["violations"]:
                    self._pm.logger.error(
                        "pm_engine",
                        f"批量归因查重拒绝采纳（重合成轮）'{spec_name}': "
                        f"{v.get('reason')}",
                    )
                # 重合成产物再拒 → 递归进入下一轮场景级回炉（或达上限升级）
                return self._handle_scenario_requeue(
                    spec_name, report2, dedup2)
            cache = load_verdict_cache(self._pm.project_root, spec_name)
            tagged = tag_cached_attributions(report2, cache, spec_name)
            if tagged:
                self._pm.logger.info(
                    "pm_engine",
                    f"跨轮缓存归因打标（重合成）'{spec_name}': "
                    f"{len(tagged)} 个场景带 cached_from_previous_round 标",
                )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"归因分级校验异常跳过（重合成）'{spec_name}'"
                f"（不阻断裁决）: {type(e).__name__}: {e}",
            )

        # 5) 合规采纳：清 violations + 清 directive + 清回炉清单 + 状态映射
        #    重写 + 裁决缓存
        self._pm._clear_verdict_violations(spec_name)
        self._clear_resynthesis_directive(spec_name)
        self._clear_requeue_manifest(spec_name)
        self._persist_verdict_cache(spec_name, report2)
        mapping2 = enforce_status_mapping(report2)
        try:
            save_report(self._pm.project_root, spec_name, report2)
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"裁决映射重写写回失败 '{spec_name}': {e}",
            )
        for c in mapping2["corrected"]:
            self._pm.logger.info(
                "pm_engine",
                f"重合成采纳后映射强制重写 '{spec_name}' 场景 "
                f"{c['scenario_id']}: {c['from_status']} → failed",
            )
        self._pm.logger.warning(
            "pm_engine",
            f"重合成产物合规 '{spec_name}' — 已按既有语义采纳推进",
        )
        return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}

    def _handle_scenario_requeue(self, spec_name: str, report: dict,
                                 dedup: dict) -> dict:
        """场景级归因查重拒绝统一收口（add-judge-incremental-attribution 2.2 / D2-D3）。

        ``_verify_verdict_evidence`` 的查重拒绝处（首轮 + 重试轮 + 重合成轮）全部
        经此闭环。与 ``_handle_attr_dedup_rejection``（整批重合成）同构，但判定
        粒度降为场景（D2）：命中重复的归因置 ``requeue``，非重复置 ``accept``
        保留——MUST NOT 因子集重复废弃整轮已写盘归因。

        流程：
          1. 逐场景条目落盘（judge_attribution.json：id/attribution/status
             accept|requeue/timestamp）+ 回炉清单（requeue_manifest.json：
             requeue 子集清单）——已 accept 场景归因保留复用（design D2）；
          2. 回炉子集 = 全量（100% 重复，模板化硬编码）→ 记录全量回炉语境，
             escalation 告警沿既有预算路径照发（design D3：查重防御不弱化）；
          3. 部分重复 → 静默回炉子集：委托 ``_handle_attr_dedup_rejection``
             落盘违规清单 + 重合成指令（只含 requeue 子集差异化素材）→ 派发
             轻量重合成 judge run（只重做 requeue 子集）→ 回灌完整校验链；
             仍重复 → 预算内递归，达上限 blocked + admin 升级（MUST NOT 无限重试）。

        Returns:
            {"ok", "cause", "violations", "dispatch_error"}（与
            ``_verify_verdict_evidence`` 同契约）。
        """
        from core.verify_engine.judge_files import (
            save_attribution, build_requeue_manifest,
            ATTRIBUTION_STATUS_ACCEPT, ATTRIBUTION_STATUS_REQUEUE,
        )
        from core.verdict_check import scenario_attribution_summary
        requeue_ids = [str(s) for s in (dedup.get("requeue_ids") or [])]
        accept_ids = [str(s) for s in (dedup.get("accept_ids") or [])]
        counts = dedup.get("counts") or {}
        violations_entries = [{
            "scenario_ids": [str(s) for s in (v.get("scenario_ids") or [])],
            "reason": str(v.get("reason") or ""),
        } for v in (dedup.get("violations") or [])]

        # 1) 逐场景条目落盘：从 report 非 PASS 场景提取归因摘要，按查重结果
        #    置 accept/requeue（写失败静默降级——judge_attribution.json 是
        #    审计/回炉状态文件，不阻断既有重合成闭环）。
        try:
            entries = []
            requeue_set = set(requeue_ids)
            for sc in report.get("scenarios") or []:
                if not isinstance(sc, dict):
                    continue
                if sc.get("status") in ("pass", "passed"):
                    continue
                sid = str(sc.get("scenario_id") or sc.get("id") or "")
                if not sid:
                    continue
                entries.append({
                    "id": sid,
                    "attribution": scenario_attribution_summary(sc),
                    "status": (ATTRIBUTION_STATUS_REQUEUE
                               if sid in requeue_set
                               else ATTRIBUTION_STATUS_ACCEPT),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            if entries:
                save_attribution(self._pm.project_root, spec_name, entries)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"judge_attribution.json 逐场景条目落盘失败 '{spec_name}'"
                f"（不阻断回炉闭环）: {type(e).__name__}: {e}",
            )

        # 2) 回炉清单落盘（requeue 子集驱动下轮 judge 只重做该子集）
        prior = self._read_resynthesis_directive(spec_name)
        rejection_round = int(prior.get("rejection_round") or 0) \
            if isinstance(prior, dict) else 0
        try:
            build_requeue_manifest(
                self._pm.project_root, spec_name,
                rejection_round=rejection_round + 1,
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"回炉清单落盘失败 '{spec_name}'（不阻断回炉闭环）: "
                f"{type(e).__name__}: {e}",
            )

        # 3) 全量重复（回炉子集 = 全量，模板化硬编码）→ 记录全量回炉语境，
        #    escalation 沿既有预算路径照发（design D3，防御语义不弱化；与
        #    整批拒绝 escalation 同源，预算耗尽时触发 _escalate_dedup_resynthesis）。
        is_full = counts.get("total") and counts.get("requeue") \
            and counts.get("requeue") >= counts.get("total")
        if is_full:
            self._pm.logger.error(
                "pm_engine",
                f"批量归因查重拒绝采纳 '{spec_name}'（第 {rejection_round + 1} 次，"
                f"回炉子集=全量 {counts.get('requeue')}/{counts.get('total')} "
                f"100% 重复，模板化硬编码形态）— escalation 沿既有预算路径照发，"
                f"不静默回炉",
            )
        else:
            self._pm.logger.warning(
                "pm_engine",
                f"批量归因查重拒绝采纳 '{spec_name}'（第 {rejection_round + 1} 次，"
                f"回炉子集 {counts.get('requeue')}/{counts.get('total')}）— "
                f"已 accept 场景归因保留复用，派发轻量重合成只重做 requeue 子集",
            )

        # 4) 委托既有重合成闭环（违规清单 + directive + 重合成 judge + 回灌
        #    校验 + 预算升级全部免费继承；重合成轮再拒经场景级递归回此方法）
        return self._handle_attr_dedup_rejection(
            spec_name, report, violations_entries)

    def _verify_verdict_evidence(self, spec_name: str, retry_judge: bool = False) -> dict:
        """确定性校验裁决 report.json 的分类/证据合规，并按映射强制重写 status。

        流程（design D1-D3，fix-verdict-retry-misattribution D1）：
          1. 读 report.json（judge 应在其中增强 classification/evidence）；
          2. validate_report：每个非 PASS 场景 MUST 有合法 classification + 非空 evidence；
          3. 不合规且 ``retry_judge`` 为真 → 走既有 judge 重试一次（同 run_planner 调用），
             重试后再次校验；二次仍不合规 → 返回 ``cause=violations``（调用方
             blocked-env + 告警，与 verify-report-gate 阻断语义一致，宁可不推进也不
             带病采纳）。合规后按分类-状态映射强制重写 status（D3），原子写回
             report.json。
          4. 返回结构化结果 ``{"ok", "cause", "violations", "dispatch_error"}``：
             cause ∈ pass / violations / dispatch_frozen / dispatch_cancelled /
             dispatch_failed / dispatch_exception / report_missing。

        注意：judge 失败（process 级）已由调用方在 ``judge_result.success`` 处拦截，
        本方法只负责「judge 已成功但产物不合规」的确定性校验与重试。

        dispatch_frozen / dispatch_cancelled = 人工已接管（frozen 门/取消旗标拦截
        重试派发）→ 语义化返回供调用方静默让位（零写入零告警）；dispatch_exception
        = ``run_planner`` 抛异常立即早退，**禁止**落至 ``load_report`` 复读第一轮
        违规的旧文件（现路径假 ERROR 根除）。
        """
        from core.verdict_check import (
            validate_report, enforce_status_mapping, load_report, save_report,
        )
        report = load_report(self._pm.project_root, spec_name)
        if report is None:
            # 无 report.json：验证产物门禁（verify-report-gate）会兜底，此处不阻断
            # （不制造伪 violation），交由既有流程处理。
            return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}

        result = validate_report(report)
        if result["ok"]:
            # ── 归因分级门（add-verdict-credibility-gate / design D2）──
            # 框架侧机械计算 attribution_level，白屏方向约束强制改写分类；
            # 批量归因查重拒绝硬编码套用；缓存归因打新鲜度标。
            # 全部发生在报告落盘/打回上下文组装前（本方法即统一入口）。
            try:
                from core.verdict_check import (
                    validate_attribution_levels,
                    enforce_blank_screenshot_direction,
                    check_batch_attribution_dedup_scenario,
                    load_verdict_cache,
                    tag_cached_attributions,
                )
                validate_attribution_levels(report)
                # 白屏方向约束：blank_screenshot 标签强制 env 方向
                for sc in report.get("scenarios") or []:
                    if not isinstance(sc, dict):
                        continue
                    new_cls = enforce_blank_screenshot_direction(sc)
                    if new_cls:
                        old_cls = sc.get("classification")
                        sc["classification"] = new_cls
                        sc["blank_direction_forced"] = True
                        self._pm.logger.info(
                            "pm_engine",
                            f"白屏方向约束 '{spec_name}' 场景 "
                            f"{sc.get('scenario_id')}: classification "
                            f"'{old_cls}' → '{new_cls}'（blank_screenshot 标签强制 env 方向）",
                        )
                # 批量归因查重：≥3 场景逐字相同 → 场景级判定（add-judge-
                # incremental-attribution 2.1：命中重复的归因置 requeue 待回炉，
                # 非重复置 accept 保留；MUST NOT 因子集重复废弃整轮归因）。
                dedup = check_batch_attribution_dedup_scenario(report)
                if not dedup["ok"]:
                    for v in dedup["violations"]:
                        sids = v.get("scenario_ids") or []
                        self._pm.logger.error(
                            "pm_engine",
                            f"批量归因查重拒绝采纳 '{spec_name}': {v.get('reason')}",
                        )
                    # 场景级回炉闭环：标记 requeue/accept 状态 + 回炉清单 →
                    # 派发重合成（仅重做 requeue 子集）→ 回灌校验（fix-verdict-
                    # dedup-resynthesis D1/D2；返回 cause=pass 已闭环采纳）
                    return self._handle_scenario_requeue(
                        spec_name, report, dedup)
                # 跨轮缓存归因打标（design D3 / Task 3.1）
                cache = load_verdict_cache(self._pm.project_root, spec_name)
                tagged = tag_cached_attributions(report, cache, spec_name)
                if tagged:
                    self._pm.logger.info(
                        "pm_engine",
                        f"跨轮缓存归因打标 '{spec_name}': "
                        f"{len(tagged)} 个场景带 cached_from_previous_round 标",
                    )
            except Exception as e:
                # 归因分级自身异常不阻断既有裁决链（分级是附加治理，宁可缺失
                # 也不让增强流程因治理代码崩溃——judge 正常裁决继续）
                self._pm.logger.warning(
                    "pm_engine",
                    f"归因分级校验异常跳过 '{spec_name}'（不阻断裁决）: "
                    f"{type(e).__name__}: {e}",
                )
            # 合规：清掉历史驳回清单（若有）后强制重写 status 映射（D3）写回
            self._pm._clear_verdict_violations(spec_name)
            self._clear_requeue_manifest(spec_name)
            self._persist_verdict_cache(spec_name, report)
            mapping = enforce_status_mapping(report)
            if mapping["corrected"]:
                try:
                    save_report(self._pm.project_root, spec_name, report)
                except OSError as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"裁决映射重写写回失败 '{spec_name}': {e}",
                    )
                for c in mapping["corrected"]:
                    self._pm.logger.info(
                        "pm_engine",
                        f"裁决映射强制重写 '{spec_name}' 场景 {c['scenario_id']}: "
                        f"{c['from_status']} → failed ({c['classification']})",
                    )
            return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}

        # 一次不合规：judge 重试一次（design D2）；违规明细落盘供重试 prompt 注入
        if retry_judge:
            violations_1 = result["violations"]
            self._pm._write_verdict_violations(spec_name, violations_1)
            self._pm.logger.warning(
                "pm_engine",
                f"裁决证据分类校验未通过 '{spec_name}'（{len(violations_1)} 项），"
                f"重试 judge 一次：{[v['scenario_id'] for v in violations_1]}",
            )
            try:
                re_judge = self._pm.agent_runner.run_planner(spec_name, "judge")
            except Exception as e:
                # dispatch_exception：run_planner 抛异常（re_judge=None）→ 立即早退。
                # 禁止继续执行 load_report 复读第一轮违规的旧 report.json（现路径
                # 会据此打出「重试后仍不合规」假 ERROR）；是否写 blocked 由调用方
                # 按 cause 决定。
                self._pm.logger.warning(
                    "pm_engine", f"裁决重试 judge 异常 '{spec_name}': {e}",
                )
                return {
                    "ok": False, "cause": "dispatch_exception",
                    "violations": violations_1, "dispatch_error": str(e),
                }
            if re_judge is not None and not re_judge.success:
                # ── 重试派发失败三分支（fix-verdict-retry-misattribution）──
                # frozen 门拦截：spec 已人工冻结 → 让位（不写 blocked、不发告警），
                # 语义化返回供调用方 INFO 留痕。判据与 runner.py 门共用导出常量。
                if (re_judge.error or "").startswith(FROZEN_TERMINATED_ERROR_PREFIX):
                    self._pm.logger.info(
                        "pm_engine",
                        f"裁决重试 judge 派发被 frozen 门拦截 '{spec_name}'"
                        f"（人工已冻结，让位不写状态）: {re_judge.error}",
                    )
                    return {
                        "ok": False, "cause": "dispatch_frozen",
                        "violations": violations_1,
                        "dispatch_error": re_judge.error,
                    }
                # 取消旗标拦截：结构化字段判定（非字符串匹配，design D3）→ 同语义让位
                if getattr(re_judge, "cancelled", False):
                    self._pm.logger.info(
                        "pm_engine",
                        f"裁决重试 judge 派发被取消旗标拦截 '{spec_name}'"
                        f"（run 已人工取消，让位不写状态）: {re_judge.error}",
                    )
                    return {
                        "ok": False, "cause": "dispatch_cancelled",
                        "violations": violations_1,
                        "dispatch_error": re_judge.error,
                    }
                # 其它派发失败（网关拒绝/预算闸门等）：携带原始 error，由调用方按
                # dispatch_failed 温和处置——不得冒充「二次违反证据契约」。
                self._pm.logger.warning(
                    "pm_engine",
                    f"裁决重试 judge 派发失败 '{spec_name}': {re_judge.error}",
                )
                return {
                    "ok": False, "cause": "dispatch_failed",
                    "violations": violations_1,
                    "dispatch_error": re_judge.error,
                }
            report2 = load_report(self._pm.project_root, spec_name)
            if report2 is None:
                # 重试成功但 report.json 不可读 → report_missing（产物丢失，非违规）
                return {
                    "ok": False, "cause": "report_missing",
                    "violations": violations_1, "dispatch_error": "",
                }
            result2 = validate_report(report2)
            if result2["ok"]:
                # ── 归因分级门（重试轮同样执行，design D2 统一入口）──
                try:
                    from core.verdict_check import (
                        validate_attribution_levels,
                        enforce_blank_screenshot_direction,
                        check_batch_attribution_dedup_scenario,
                        load_verdict_cache,
                        tag_cached_attributions,
                    )
                    validate_attribution_levels(report2)
                    for sc in report2.get("scenarios") or []:
                        if not isinstance(sc, dict):
                            continue
                        new_cls = enforce_blank_screenshot_direction(sc)
                        if new_cls:
                            old_cls = sc.get("classification")
                            sc["classification"] = new_cls
                            sc["blank_direction_forced"] = True
                            self._pm.logger.info(
                                "pm_engine",
                                f"白屏方向约束（重试轮）'{spec_name}' 场景 "
                                f"{sc.get('scenario_id')}: classification "
                                f"'{old_cls}' → '{new_cls}'（blank_screenshot 标签强制 env 方向）",
                            )
                    dedup = check_batch_attribution_dedup_scenario(report2)
                    if not dedup["ok"]:
                        for v in dedup["violations"]:
                            self._pm.logger.error(
                                "pm_engine",
                                f"批量归因查重拒绝采纳（重试轮）'{spec_name}': "
                                f"{v.get('reason')}",
                            )
                        # 统一收口：场景级回炉闭环
                        return self._handle_scenario_requeue(
                            spec_name, report2, dedup)
                    cache = load_verdict_cache(self._pm.project_root, spec_name)
                    tagged = tag_cached_attributions(report2, cache, spec_name)
                    if tagged:
                        self._pm.logger.info(
                            "pm_engine",
                            f"跨轮缓存归因打标（重试轮）'{spec_name}': "
                            f"{len(tagged)} 个场景带 cached_from_previous_round 标",
                        )
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"归因分级校验异常跳过（重试轮）'{spec_name}'"
                        f"（不阻断裁决）: {type(e).__name__}: {e}",
                    )
                self._pm._clear_verdict_violations(spec_name)
                self._clear_requeue_manifest(spec_name)
                self._persist_verdict_cache(spec_name, report2)
                mapping2 = enforce_status_mapping(report2)
                try:
                    save_report(self._pm.project_root, spec_name, report2)
                except OSError as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"裁决映射重写写回失败 '{spec_name}': {e}",
                    )
                for c in mapping2["corrected"]:
                    self._pm.logger.info(
                        "pm_engine",
                        f"裁决重试后映射强制重写 '{spec_name}' 场景 "
                        f"{c['scenario_id']}: {c['from_status']} → failed",
                    )
                return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}
            # 真·二次违规（重试确实发生）：violations 携带 validate_report 原始明细，
            # 由调用方按既有语义处置（blocked + verdict_evidence_invalid 告警）。
            self._pm.logger.error(
                "pm_engine",
                f"裁决重试后证据分类仍不合规 '{spec_name}'："
                f"{[v['scenario_id'] for v in result2['violations']]}",
            )
            return {
                "ok": False, "cause": "violations",
                "violations": result2["violations"], "dispatch_error": "",
            }

        # 无重试预算的首轮不合规：按 violations 处置（调用方若未显式指定
        # retry_judge，语义即「首轮已违规」）。
        return {
            "ok": False, "cause": "violations",
            "violations": result["violations"], "dispatch_error": "",
        }


    # ── 失败历史侧车（fix-verdict-retry-misattribution D6）────────────────
    # `.fenix/verify-progress/<spec>/fail_history.json`：每轮裁决采纳失败时原子
    # 追加 {round, cause_type, failed_scenarios}；spec 进入 verified 终态或升级
    # 闸门告警消费后清空。写盘失败静默降级（缺侧车 → 升级告警分型 unknown），
    # 不阻断升级闸门。
    _FAIL_HISTORY_FILENAME = "fail_history.json"

    def _fail_history_path(self, spec_name: str) -> Path:
        return (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / self._FAIL_HISTORY_FILENAME
        )

    def _read_fail_history(self, spec_name: str) -> list:
        """读取失败历史侧车；缺失/损坏返回 []（升级告警据此标注 unknown）。"""
        try:
            path = self._fail_history_path(spec_name)
            if not path.exists():
                return []
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, list):
                return []
            return [r for r in loaded if isinstance(r, dict)]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []

    def _append_fail_history(self, spec_name: str, cause_type: str,
                             failed_scenarios: list) -> None:
        """原子追加一轮裁决采纳失败记录 {round, cause_type, failed_scenarios}。

        ``cause_type`` ∈ evidence-invalid（证据校验不合规） / real-bugs（真缺陷）。
        写盘失败（含读损坏）静默降级：仅 warning 留痕，不阻断调用方流程。
        """
        try:
            path = self._fail_history_path(spec_name)
            rounds = self._read_fail_history(spec_name)
            next_round = max(
                [int(r.get("round", 0) or 0) for r in rounds], default=0) + 1
            rounds.append({
                "round": next_round,
                "cause_type": cause_type,
                "failed_scenarios": [str(s) for s in (failed_scenarios or [])],
            })
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), prefix=".fail_history.",
                suffix=".json.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(rounds, f, ensure_ascii=False, indent=2)
                    f.flush()
                os.replace(tmp_path, path)
            except OSError:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fail_history 写回失败 '{spec_name}'（静默降级）: {e}",
            )

    def _clear_fail_history(self, spec_name: str) -> None:
        """清空失败历史侧车（verified 终态 / 升级告警消费后）。"""
        try:
            path = self._fail_history_path(spec_name)
            if path.exists():
                path.unlink()
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fail_history 清理失败 '{spec_name}'（静默降级）: {e}",
            )

    def _failed_scenario_ids(self, spec_name: str) -> list:
        """从当前 report.json 提取非 PASS 场景 id 列表（失败轮 failed_scenarios）。"""
        from core.verdict_check import load_report
        report = load_report(self._pm.project_root, spec_name)
        if not isinstance(report, dict):
            return []
        ids = []
        for sc in report.get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            if sc.get("status") not in ("pass", "passed"):
                sid = sc.get("scenario_id") or sc.get("id")
                if sid:
                    ids.append(str(sid))
        return ids


    # ── 场景缺陷改道门（add-scenario-defect-triage-gate D1/D2/D3）────────

    def _scenario_classification_distribution(self, spec_name: str) -> dict:
        """读 report.json 场景 classification 分布（改道门判定依据）。

        Returns:
            dict：{'total': n, 'failed_ids': [...], 'counts': {分类: 数},
                   'product_bug': int, 'all_scenario_defects': bool,
                   'unclassified': int}——任意读取/解析异常返回空统计
            （total=0，改道判定自然不触发，保守不改道）。
        """
        from collections import Counter
        dist = {
            "total": 0, "failed_ids": [],
            "counts": {}, "product_bug": 0,
            "all_scenario_defects": False, "unclassified": 0,
        }
        report = self._read_verify_report(spec_name)
        if not isinstance(report, dict):
            return dist
        scenarios = report.get("scenarios") or []
        if not isinstance(scenarios, list):
            return dist
        failed: list = []
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            if sc.get("status") in ("pass", "passed"):
                continue
            sid = sc.get("scenario_id") or sc.get("id") or "?"
            failed.append((str(sid), sc.get("classification")))
        if not failed:
            return dist
        counts = Counter(cls for _sid, cls in failed)
        product_bug = int(counts.get("product-bug", 0) or 0)
        unclassified = sum(
            1 for _sid, cls in failed if not isinstance(cls, str)
            or cls not in ("product-bug", "test-defect", "flaky", "env"))
        # 全场景缺陷判定：全部失败场景均为显式 test-defect/flaky 且 product-bug=0
        # （未显式分类 / 含 env / 含产品缺陷 → False，保守不改道）。
        all_scenario_defects = (
            len(failed) > 0
            and product_bug == 0
            and unclassified == 0
            and all(cls in ("test-defect", "flaky")
                    for _sid, cls in failed)
        )
        return {
            "total": len(failed),
            "failed_ids": [sid for sid, _cls in failed],
            "counts": dict(counts),
            "product_bug": product_bug,
            "unclassified": unclassified,
            "all_scenario_defects": all_scenario_defects,
        }


    def _scenario_defect_reroute_gate(self, spec_name: str, _repair_depth: int,
                                      judge_result) -> bool:
        """bug-found 申报打回 implementer 前的分类改道门。

        judge 申报 bug-found 后、打回 implementer 前插入（D1：框架侧机械判定，
        零 token）。report.json 非 PASS 场景全部显式 test-defect/flaky 且
        product-bug=0 → **拒绝打回 implementer**，定向重派 judge 一次（D2）：
        注入改道指令段，责令按原地修复协议申报 scenario-repaired；改道后
        scenario-repaired 沿用既有通道（冻结 diff 记账→重入阶段2/3）。

        预算（D2/D3）：改道重派计入 ``_SCENARIO_REPAIR_MAX_ROUNDS``，与
        scenario-repaired 重入共用 ``_repair_depth`` 计数（防两通道叠加无限重入）。
        预算耗尽仍 bug-found 且 product-bug=0 → 停止重派，升级人工
        （``_send_human_escalation_alert``，附失败清单/classification 分布/
        judge 申报记录），spec 保持 testing。改道路径不触碰 impl_run_budget。

        Returns:
            True 表示已按改道处置（调用方直接 return）；False 表示走现行
            bug-found 路由（打回 implementer）。
        """
        dist = self._scenario_classification_distribution(spec_name)
        if not dist["all_scenario_defects"]:
            self._pm.logger.info(
                "pm_engine",
                f"改道门不放行 '{spec_name}'（失败 "
                f"{dist['total']} 个，product-bug={dist['product_bug']}，"
                f"未分类 {dist['unclassified']}）— 走现行 bug-found 路由",
            )
            return False

        # 判定分布记日志留痕（3.1）
        self._pm.logger.warning(
            "pm_engine",
            f"场景缺陷改道门触发 '{spec_name}'：失败 {dist['total']} 个全部显式"
            f"test-defect/flaky（分布 {dist['counts']}），product-bug=0 ——"
            f"拒绝打回 implementer，改道重派 judge（深度 {_repair_depth}）",
        )

        if _repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS:
            return self._escalate_scenario_defect_reroute(
                spec_name, dist, _repair_depth)

        # 写改道指令文件（prompt_builder _scenario_reroute_directive_section 读取）
        directive_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "scenario_reroute_directive.json"
        )
        try:
            directive_path.parent.mkdir(parents=True, exist_ok=True)
            directive_path.write_text(
                json.dumps(dist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"改道指令文件写失败 '{spec_name}'（仍重派 judge）: {e}",
            )

        try:
            reroute_judge = self._pm.agent_runner.run_planner(spec_name, "judge")
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"改道重派 judge 异常 '{spec_name}'（保持 testing）: "
                f"{type(e).__name__}: {e}",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "error": f"场景缺陷改道重派 judge 异常（保持 testing）：{e}",
            })
            return True
        finally:
            try:
                directive_path.unlink()
            except OSError:
                pass

        if not reroute_judge.success:
            # 改道重派失败：取消/派发故障。保持 testing，不升级人工
            #（与裁决重试派发失败同型，温和处置留 error）。
            if getattr(reroute_judge, "cancelled", False):
                self._pm.logger.warning(
                    "pm_engine",
                    f"改道重派 judge 被取消 '{spec_name}' — hold-state（保持 testing）",
                )
            else:
                self._pm.logger.warning(
                    "pm_engine",
                    f"改道重派 judge 派发失败 '{spec_name}' — 保持 testing，"
                    f"留 error 待下轮重验: {reroute_judge.error}",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "error": f"改道重派 judge 派发失败（保持 testing）："
                             f"{reroute_judge.error}",
                })
            return True

        # 重派结果判定
        reroute_read = self._pm._read_planner_result(spec_name)
        if reroute_read.ok and reroute_read.status == "scenario-repaired":
            # 改道后 scenario-repaired：沿用既有通道（冻结 diff 记账 → 重入）
            try:
                freeze_result = self._pm._apply_scenario_freeze(spec_name)
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"改道后场景冻结记账跳过 '{spec_name}'（异常不阻断）: {e}",
                )
                freeze_result = None
            if isinstance(freeze_result, dict) and freeze_result.get("aborted"):
                # ── 空集显式兜底（evo-planner-scenario-schema-alignment 3.7）──
                # 改道重入路径与 judge 重入同语义：修复后场景集为空 → 拒绝
                # 本次重入、保持原状并留痕，MUST NOT 以空集/未过滤文件进入阶段2。
                reject_detail = "、".join(freeze_result.get("rejected") or [])[:400]
                self._pm.state_machine.update_spec(spec_name, {
                    "error": (
                        f"改道重派 judge 修复后场景集为空（写前预校验整批拒绝，"
                        f"共 {freeze_result.get('total', 0)} 条）— 拒绝本次重入，"
                        f"保持 testing 待人工/下轮处置: {reject_detail}"
                    ),
                })
                self._pm.logger.error(
                    "pm_engine",
                    f"改道重派后无合法场景 '{spec_name}' — 拒绝重入，0 场景不进入"
                    f"阶段2: {reject_detail}",
                )
                return True
            self._pm.logger.info(
                "pm_engine",
                f"[改道] judge 原地修复采纳 '{spec_name}' — 重入执行"
                f"（第 {_repair_depth + 1}/{_SCENARIO_REPAIR_MAX_ROUNDS} 次修复）",
            )
            self._run_three_stage_verification(
                spec_name, _repair_depth=_repair_depth + 1)
            return True

        if reroute_read.ok and reroute_read.status == "bug-found":
            # 改道后仍 bug-found：再读分布——
            # 若含 product-bug（judge 改判真产品缺陷）→ 正常打回 implementer 路由；
            # 若仍全场景缺陷且预算耗尽 → 升级人工。
            new_dist = self._scenario_classification_distribution(spec_name)
            if new_dist["product_bug"] > 0 or not new_dist[
                    "all_scenario_defects"]:
                self._pm.logger.warning(
                    "pm_engine",
                    f"改道后 judge 改判含产品缺陷 '{spec_name}'（product-bug="
                    f"{new_dist['product_bug']}）— 走现行 bug-found 路由",
                )
                return False
            return self._escalate_scenario_defect_reroute(
                spec_name, new_dist, _repair_depth + 1)

        # 结果不可读/其他状态：fail-closed 保守，保持 testing 等待下轮重验
        self._pm.logger.error(
            "pm_engine",
            f"改道重派结果不可读 '{spec_name}'（reason="
            f"{reroute_read.reason if reroute_read.ok is False else '?'}）— "
            f"保持 testing 等待下轮重验",
        )
        self._pm.state_machine.update_spec(spec_name, {
            "error": "改道重派 judge 结果不可读（保持 testing，等待下轮重验）",
        })
        return True


    def _escalate_scenario_defect_reroute(self, spec_name: str, dist: dict,
                                          _repair_depth: int) -> bool:
        """改道预算耗尽升级人工：附失败清单/classification 分布/申报记录。"""
        self._pm.state_machine.update_spec(spec_name, {
            "error": (
                f"场景缺陷改道预算耗尽（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮），"
                f"仍为纯场景缺陷（product-bug=0）— 已升级人工裁决，spec 保持"
                f"testing，不再消耗实现轮预算"
            ),
        })
        self._pm.logger.error(
            "pm_engine",
            f"场景缺陷改道预算耗尽 '{spec_name}'（深度 {_repair_depth}）— "
            f"升级人工，不等打回 implementer 修场景",
        )
        self._pm._send_human_escalation_alert(
            spec_name=spec_name,
            signal_type="scenario_defect_reroute_exhausted",
            severity="major",
            description=(
                f"'{spec_name}' 验证失败清单全部为场景缺陷（test-defect/flaky）"
                f"且 product-bug=0，改道重派 judge {_SCENARIO_REPAIR_MAX_ROUNDS} "
                f"轮后仍未原地修复完成——已停止重派，升级人工裁决。"
            ),
            evidence=(
                f"spec={spec_name}; classification_distribution="
                f"{json.dumps(dist.get('counts'), ensure_ascii=False)}; "
                f"failed_ids={','.join(dist.get('failed_ids') or [])[:500]}; "
                f"impl_run_budget 未消耗（改道路径不触碰实现预算）"
            ),
            recommended_action=(
                "检查失败场景文件（.fenix/verify-progress/"
                f"{spec_name}/test_scenarios.json）与验证报告，人工裁决："
                "① admin 场景修复通道修场景（schema 门内）；② 确认为真产品缺陷"
                "则重置分类/直接打回 implementer；③ 场景集已过时则删除冻结集批准"
                "重新出题。"
            ),
        )
        return True


    def _update_warning_streaks(self, spec_name: str) -> list:
        """更新 warning 连续悬置计数侧车（design D4 / D5）。

        采纳 report.json 后调用：扫描非 PASS 场景——
          - status == warning 且 classification ∈ {flaky, env} 的场景：连续计数 +1；
          - status 为 pass/failed（含被强制重写的 failed）或 classification 为
            product-bug/test-defect 的场景：计数清零。

        返回本轮回填后「连续计数 == 2」的场景 id 列表（即触发 triage 升级的候选），
        调用方据此发告警。侧车文件：``.fenix/verify-progress/<spec>/warning_streaks.json``，
        结构 {scenario_id: 连续轮数}。
        """
        from core.verdict_check import VERDICT_CLASSES, load_report, save_report
        streaks_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "warning_streaks.json"
        )
        streaks = {}
        if streaks_path.exists():
            try:
                loaded = json.loads(streaks_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    streaks = {k: int(v) for k, v in loaded.items()
                               if isinstance(k, str)}
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                streaks = {}

        report = load_report(self._pm.project_root, spec_name)
        if report is None:
            return []
        scenarios = report.get("scenarios")
        if not isinstance(scenarios, list):
            return []

        triage_candidates = []
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            sid = sc.get("scenario_id") or sc.get("id")
            if not sid:
                continue
            status = sc.get("status")
            classification = sc.get("classification")
            # 仅 flaky/env 的 warning 计入连续悬置；product-bug/test-defect 已强制
            # failed（D3），不悬置；pass/failed 清零（D4）。
            if status == "warning" and classification in ("flaky", "env"):
                streaks[sid] = streaks.get(sid, 0) + 1
                if streaks[sid] == 2:
                    triage_candidates.append(sid)
            else:
                streaks[sid] = 0

        # 写回侧车
        try:
            streaks_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(streaks_path.parent), prefix=".warning_streaks.",
                suffix=".json.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(streaks, f, ensure_ascii=False, indent=2)
                    f.flush()
                os.replace(tmp_path, streaks_path)
            except OSError:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"warning_streaks 写回失败 '{spec_name}': {e}",
            )
        return triage_candidates


    def _warning_stale_triage_alert(self, spec_name: str, scenario_ids: list) -> None:
        """连续 2 轮 warning 场景的 triage 升级告警（design D4 / D5）。

        signal_type=warning_stale_triage，含 spec/场景/轮次/最近证据摘要；
        同时把场景写入下一轮 planner prompt 的「优先复核」注入（与 scenario-freeze
        的基准集注入同一接入点——复用 _scenario_freeze_section 机制：把 triage 场景
        落盘到 verify-progress/<spec>/triage_recheck.json，planner prompt 读取后注入）。
        """
        from core.verdict_check import load_report
        # 证据摘要：从该场景的 evidence.failed_assertions / first_failed_step 摘取
        evidence_lines = []
        report = load_report(self._pm.project_root, spec_name)
        latest_round = 2
        if isinstance(report, dict):
            for sc in report.get("scenarios", []) or []:
                if not isinstance(sc, dict):
                    continue
                sid = sc.get("scenario_id") or sc.get("id")
                if sid not in scenario_ids:
                    continue
                ev = sc.get("evidence") if isinstance(sc.get("evidence"), dict) else {}
                ffs = ev.get("first_failed_step") or ""
                fa = ev.get("failed_assertions") or []
                fa_summary = "; ".join(
                    f"{a.get('type','?')}({a.get('selector','')})"
                    for a in fa if isinstance(a, dict)
                ) if isinstance(fa, list) else ""
                evidence_lines.append(
                    f"场景 {sid}（classification={sc.get('classification')}, "
                    f"连续 {latest_round} 轮 warning）：{ffs}"
                    + (f"；失败断言：{fa_summary}" if fa_summary else "")
                )
        evidence = "\n".join(evidence_lines) or (
            f"连续 2 轮 warning 场景：{', '.join(scenario_ids)}"
        )

        self._pm._send_human_escalation_alert(
            spec_name=spec_name,
            signal_type="warning_stale_triage",
            severity="critical",
            description=(
                f"'{spec_name}' 以下场景连续 {latest_round} 轮均为 warning，"
                f"需人工 triage 甄别是否真缺陷被悬置：{', '.join(scenario_ids)}"
            ),
            evidence=evidence,
            recommended_action=(
                f"人工复核 {', '.join(scenario_ids)} 的真实根因；下一轮验证已将其"
                f"列入优先复核清单（triage_recheck.json）"
            ),
        )
        # 下一轮 planner prompt 优先复核注入（design D5）：落盘 triage_recheck.json
        recheck_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "triage_recheck.json"
        )
        try:
            recheck_path.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if recheck_path.exists():
                try:
                    data = json.loads(recheck_path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        existing = data
                except (json.JSONDecodeError, OSError):
                    existing = []
            merged = list(dict.fromkeys(existing + scenario_ids))
            recheck_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"triage_recheck 写盘失败 '{spec_name}': {e}",
            )


    def _ensure_verification_report(self, spec_name: str) -> str | None:
        """验证报告产物闸门（add-verify-report-gate）。

        在验证裁决采纳处（verified / bug-found 即将推进）调用：校验
        spec/changes/<spec>/verification-report.md 存在；缺失时由框架从
        结构化数据确定性合成（不重跑验证、不覆盖既有文件）并发人工升级告警；
        结构化数据也不可用时 fail-closed。

        返回 None 表示放行（报告已存在或合成成功）；返回非空字符串为阻断原因，
        调用方须阻止状态推进并把原因写入 error 字段。
        """
        from core.verify_report import ensure_verification_report
        try:
            result = ensure_verification_report(
                self._pm.project_root, spec_name, logger=self._pm.logger,
            )
        except Exception as e:
            # 合成器自身异常等同数据不可用：fail-closed，不凭空放行
            return f"验证报告缺失且无法合成：闸门异常 {e}"
        if result.get("ok"):
            return None
        return result.get("error") or "验证报告缺失且无法合成"


    def _check_verification_gate(self, spec_name: str) -> str | None:
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
        from core.dashboard.data import parse_verify_progress
        vp = parse_verify_progress(self._pm.project_root, spec_name)
        if not vp.get("exists"):
            return None
        total = vp.get("total") or 0
        done = vp.get("done") or 0
        if vp.get("error") == "corrupt" or total <= 0 or done < total:
            current = vp.get("current") or ""
            tail = f"（当前：{current}）" if current else ""
            return f"验证未完成：{done}/{total}{tail}"
        return None


    def _read_verifier_result(self, result_path: Path) -> VerdictReadResult:
        """读取 verifier 写入的 .fenix-run-result.json，返回结构化三态结果。

        fix-verdict-read-failclosed（fail-closed 语义反转）：
        结果文件缺失 / 非法 JSON / status 白名单外一律返回 ok=False 的不可读结果
        （reason ∈ missing / parse / unknown-status），**绝不**返回 None 表示
        「视为 verified」——裁决读不出来 = 按通过放行是历史事故根因
        （add-verify-contract-autodraft：裸换行非法 JSON → None → else 分支
        → verified → done → auto-push）。不可读的处置（重试/blocked）由调用方
        决定，本方法只负责如实归因。

        ok=True 时的 status 取值：
        - "verified" 表示全部通过；
        - "bug-found" 表示验证发现 Bug；
        - "plan-ready" 表示 Planner 已生成场景；
        - "scenario-repaired" 表示 judge 原地修复了场景文件（judge-scenario-repair）。
        """
        if not result_path.exists():
            self._pm.logger.warning(
                "pm_engine",
                f"Verifier result file not found: {result_path}",
            )
            return VerdictReadResult.failure("missing", f"{result_path}")
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"Failed to read verifier result (fail-closed): {e}",
            )
            return VerdictReadResult.failure("parse", f"{e}")
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"Failed to read verifier result (fail-closed): {e}",
            )
            return VerdictReadResult.failure("parse", f"{e}")
        if not isinstance(data, dict):
            self._pm.logger.warning(
                "pm_engine",
                f"Unknown verifier result structure (fail-closed): {result_path}",
            )
            return VerdictReadResult.failure("parse", f"顶层非对象: {result_path}")
        status = data.get("status", "")
        if status not in planner_result_status_whitelist:
            # fail-closed：白名单外 status（如 implementer 共享文件残留的
            # success/error）不得被当成 verified 放行（历史日志：
            # "Unknown verifier status: 'success', treating as verified"）。
            self._pm.logger.warning(
                "pm_engine",
                f"Unknown verifier status: '{status}' (fail-closed, not treating "
                "as verified)",
            )
            return VerdictReadResult.failure("unknown-status", f"status='{status}'")
        bugs = data.get("bugs", [])
        bug_count = len(bugs) if isinstance(bugs, list) else 0
        self._pm.logger.info(
            "pm_engine",
            f"Verifier result: status={status}, bugs={bug_count}",
        )
        return VerdictReadResult.success(status)


    def _read_planner_result(self, spec_name: str) -> VerdictReadResult:
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
        primary = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / ".fenix-run-result.json"
        )
        if primary.exists():
            return self._pm._read_verifier_result(primary)
        fallback = self._pm.project_root / ".fenix" / ".fenix-run-result.json"
        # 共享结果文件护栏：主树共享文件携带的 spec 与当前 spec 不符时视为残留忽略
        # （与 _read_implementer_result 相同语义），避免误读其它 spec 的
        # implementer 残留状态。
        if fallback.exists():
            try:
                fb_data = json.loads(fallback.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                return VerdictReadResult.failure("parse", f"{fallback}: {e}")
            stamped = fb_data.get("spec") if isinstance(fb_data, dict) else None
            if isinstance(stamped, str) and stamped and stamped != spec_name:
                self._pm.logger.warning(
                    "pm_engine",
                    f"Ignoring stale result file {fallback}: "
                    f"spec='{stamped}' != '{spec_name}'",
                )
                return VerdictReadResult.failure(
                    "foreign-stamp", f"{fallback}: spec='{stamped}'")
        return self._pm._read_verifier_result(fallback)


    def _judge_bugs_declare_env(self, spec_name: str) -> bool:
        """judge 判 bug-found 但其自述根因全部为环境/基础设施问题时返回 True。

        2026-08-28 实证：planner 重新生成的场景用相对 URL "/dashboard"（无效
        URL）+ 幻觉 testid，12 个场景全部在导航步失败；judge 在结果文件中
        自述「这是一个环境问题，而非产品 Bug」，却把 status 标为 bug-found，
        pm_engine 据此派生伪 fix 级联。此处以 judge 自己的根因描述为准：
        所有 bug 均自述环境/基础设施问题时，按「验证没能发生」处理。
        """
        primary = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / ".fenix-run-result.json"
        )
        if not primary.exists():
            return False
        try:
            data = json.loads(primary.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        bugs = data.get("bugs") if isinstance(data, dict) else None
        if not isinstance(bugs, list) or not bugs:
            return False

        def _declares_env(bug) -> bool:
            if not isinstance(bug, dict):
                return False
            text = f"{bug.get('root_cause', '')} {bug.get('description', '')}"
            return any(marker in text for marker in self._pm._ENV_INFRA_MARKERS)

        return all(_declares_env(bug) for bug in bugs)


    def _handle_judge_env_declared(self, spec_name: str) -> bool:
        """judge 自述环境问题时按 inconclusive 处理（不派生 fix）。

        与 _handle_env_blocked_inconclusive 同语义：回 implemented 重派新
        attempt，不 transition bug-found、不派生 fix spec；超限后暂停自动
        重验并暴露错误等待人工（无界重验会烧 token）。
        """
        spec = self._pm.state_machine.read_one(spec_name) or {}
        try:
            attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        max_attempts = int(
            self._pm._get_config("verify_engine.inconclusive_max_attempts", 3) or 3
        )
        escalate_attempts = int(
            self._pm._get_config(
                "verify_engine.inconclusive_escalate_attempts", 4) or 4
        )
        note = (
            f"judge 判定 bug-found 但所有 bug 根因均自述为环境/基础设施问题"
            f"（伪失败，不派生 fix），第 {attempts}/{max_attempts} 次重验"
        )

        # ── B7 升级通道（design D6）──
        if attempts >= escalate_attempts:
            # 构造一个简化 report（blocked-env 场景信息从 state 读）：
            # judge 自述环境问题时，blocked-env 数需要从上轮 report 提取，
            # 此处用 _inconclusive_attempts 作为上下文。
            self._write_inconclusive_loop_signal(
                spec_name, attempts, 0,
                {"scenarios": [], "summary": {"blocked_env": 0}})
            self._pm.logger.error(
                "pm_engine",
                f"'{spec_name}' judge 连续 {attempts} 轮均自述环境问题，"
                f"已达升级阈值 {escalate_attempts}，SIGNAL 已写 admin store，"
                f"暂停自动重验等待人工处置",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "status": "implemented",
                "tester_run": None,
                "error": (f"连续 {attempts} 轮验证均因环境/基础设施问题未完成"
                          f"（judge 自述），已呼叫 Administrator 核查验证环境；"
                          f"人工处置后需清 _inconclusive_attempts 才能恢复自动重验"),
                "_inconclusive_attempts": attempts,
                "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
            })
            return True

        if attempts < max_attempts:
            self._pm.logger.warning("pm_engine", f"'{spec_name}' {note}")
            self._pm.state_machine.update_spec(spec_name, {
                "status": "implemented",
                "tester_run": None,
                "error": note,
                "_inconclusive_attempts": attempts,
            })
            self._pm._enqueue(spec_name, "verifier")
            return True

        # 连续 ≥max_attempts 轮均自述环境问题：停止自动重验，暴露错误等待人工。
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' 连续 {attempts} 轮 judge 均自述环境问题（伪失败），"
            f"暂停自动重验，请人工检查验证场景/环境",
        )
        self._pm.state_machine.update_spec(spec_name, {
            "status": "implemented",
            "tester_run": None,
            "error": (f"连续 {attempts} 轮验证均因环境/基础设施问题未完成"
                      f"（judge 自述），请人工检查验证场景/环境；不派生 fix"),
            "_inconclusive_attempts": attempts,
            "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
        })
        return True


    def _verdict_violations_path(self, spec_name: str) -> Path:
        return (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "verdict_violations.json"
        )


    def _write_verdict_violations(self, spec_name: str, violations: list) -> None:
        """落盘裁决驳回清单（verdict-rejection-retry：judge 重试幂等陷阱修复）。

        fix-budget-counting-semantics 复盘：judge 首轮补齐 classification/evidence
        但漏 assertion_triage，重试 judge 读到已增强的 report 后判定「无需改写」
        再次跳过，校验必然复败 → blocked。将违规明细落盘，由 agent_runner 注入
        重试 prompt（见 _verdict_rejection_section），告知重试 judge 缺口所在。
        """
        try:
            path = self._pm._verdict_violations_path(spec_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(violations, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"裁决驳回清单写盘失败 '{spec_name}': {e}",
            )


    def _clear_verdict_violations(self, spec_name: str) -> None:
        try:
            self._pm._verdict_violations_path(spec_name).unlink(missing_ok=True)
        except OSError:
            pass

# ── env 阻塞复位判定（add-blocked-reverify-lane D2）────────────────
# 决定 env 阻塞 spec 在 admin 处置完成后走哪条复位路径：BLOCKED→TESTING 重验
# 直通道（实现分支已合并）还是既有 BLOCKED→READY 全量重实现。模块级函数（非
# VerificationPipeline 方法）：admin_monitor 处置收尾消费点直接 import 复用，
# 两处共享同一守卫判定，避免语义漂移。

# env 族信号类型：仅这些信号触发的 blocking 复位才适用重验直通道判定，其余
# 信号（如 blocked_stuck 等）的复位语义不动。
ENV_BLOCK_SIGNAL_TYPES = ("verify_env_blocked", "verify_env_inconclusive")

# git 合并判定超时（subprocess timeout；异常/超时按「未合并」fail-safe 回退
# ready 通道——宁可多重实现不可错误直达 testing）。
ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS = 10


def resolve_env_blocked_reset_path(spec: dict, project_root) -> str | None:
    """env 阻塞复位路径判定（D1 守卫链）。

    Args:
        spec: STATE.md spec entry（须含 status/error/frozen/branch）。
        project_root: 主树 project_root——git 合并判定统一在此执行
            （subprocess cwd，与验证引擎其他 git 操作同侧）。

    Returns:
        "testing": branch 非空且 merge commit 已在主树历史（实现分支已合并）——
            可走 BLOCKED→TESTING 重验直通道（transition_gate）。
        "ready":   branch 为空（实现阶段熔断）或 branch 未合并——走既有
            BLOCKED→READY 重实现通道（transition）。
        None:      spec 非 blocked，或人工冻结（frozen=True / error 以冻结前缀
            开头），或无法判定——调用方不应触发任何复位转换。
    """
    if not isinstance(spec, dict) or spec.get("status") != "blocked":
        return None
    # 人工冻结：frozen 结构化标记或 error 文本契约（FREEZE_ERROR_PREFIX）任一
    # 命中即视为人工冻结，不走自动复位（人工处置是唯一出路）。
    if spec.get("frozen"):
        return None
    error = str(spec.get("error") or "")
    if error.startswith(FREEZE_ERROR_PREFIX):
        return None
    branch = spec.get("branch")
    if not branch:
        return "ready"
    if _branch_merged_into_tree(branch, project_root):
        return "testing"
    return "ready"


def _branch_merged_into_tree(branch: str, project_root) -> bool:
    """branch 的 merge commit 是否存在于主树历史（git merge-base --is-ancestor）。

    统一在主树 project_root 执行（design D4：worktree 布局差异不影响判定）；
    subprocess 异常（git 不可用/仓库异常/超时）一律按「未合并」fail-safe 处理——
    宁可回退 ready 全量重实现，不可错误直达 testing 造成验证前置缺失。
    """
    try:
        from pathlib import Path
        root = Path(project_root)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", str(branch), "HEAD"],
            cwd=str(root),
            capture_output=True,
            timeout=ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except Exception:
        return False
