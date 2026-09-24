"""token_budget.py — TokenAccountant：token 用量累计/预算检查/告警/验证链侧车（refactor-core-packages 阶段 2）。

无状态组件：STATE 累计与告警都实时经门面回引（self._pm.state_machine 等），
测试在构造后替换 runner.state_machine / runner.logger 的路径保持有效。
"""

from datetime import datetime, timezone
import fcntl
import json
import os
import tempfile
import threading

# code-review item 7f6062e65ecb：_accumulate_token_usage 的「read_one 读旧值 →
# 内存相加 → update_spec 写回」跨两次 state_machine 调用，state_machine 的锁
# 只护单次调用（update_spec 单次原子、read_one 无锁），同 spec 并发收工时后写
# 者会用陈旧 prev_* 覆盖先写者的累计。per-spec 进程内锁把该读改写对串行化；
# 锁表本身用全局锁保护（锁只覆盖同进程线程，跨进程字段级覆盖由 update_spec
# 自身 flock 兜底单次写原子）。
_ACCUM_LOCKS_GUARD = threading.Lock()
_ACCUM_LOCKS = {}  # spec_name -> threading.Lock


def _spec_accumulate_lock(spec_name: str) -> threading.Lock:
    with _ACCUM_LOCKS_GUARD:
        lock = _ACCUM_LOCKS.get(spec_name)
        if lock is None:
            lock = threading.Lock()
            _ACCUM_LOCKS[spec_name] = lock
        return lock


class TokenAccountant:
    """token 用量与预算告警组件（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）
        # add-turn-limit-anchor-c（D4）：unobserved usage 跳过累计的 DEBUG 留痕
        # 计数——供成本审计区分「确认为零」与「观测不到」（强杀路径真实消耗
        # 大概率非零）。仅内存计数 + DEBUG 日志，不新增 STATE 字段（展示层
        # 不伪造原则：无可展示的真实数字就不展示）。
        self._unobserved_runs = 0

    def _accumulate_token_usage(self, spec_name: str, usage_info: dict) -> None:
        """收工处累加本次 run 的 usage 到 STATE 内部字段（add-cost-observability D1）。

        ``_tokens_in`` = input + cache_creation + cache_read（保守计入缓存读，design D-风险）；
        ``_tokens_out`` = output。成本仅网关回传 total_cost_usd 时累计到 ``_cost_usd``，
        否则不写（不伪造，spec「金额展示不伪造」）。累加后触发预算阈值检查。

        unobserved 语义（add-turn-limit-anchor-c D4）：usage_info 带
        ``"unobserved": True``（强杀路径无 result 终态，四数值键全零只是观测
        兜底而非确认零）时**跳过累计**（全零本就不增），并计入 DEBUG 留痕计数
        供审计区分「零消耗」与「未观测」——不凭空补数、不把不可观测当零入账。

        state_machine 缺失（测试/未初始化）时安全跳过；STATE 条目缺失不写（spec 必已注册）。
        """
        if self._pm.state_machine is None:
            return
        if not isinstance(usage_info, dict):
            usage_info = {}
        if usage_info.get("unobserved"):
            self._unobserved_runs += 1
            self._pm.logger.debug(
                "agent_runner",
                f"token usage unobserved for '{spec_name}' — skipped accumulation "
                f"(unobserved total: {self._unobserved_runs}, "
                f"add-turn-limit-anchor-c D4)",
            )
            return
        tokens_in = (
            int(usage_info.get("input_tokens", 0) or 0)
            + int(usage_info.get("cache_creation_input_tokens", 0) or 0)
            + int(usage_info.get("cache_read_input_tokens", 0) or 0)
        )
        tokens_out = int(usage_info.get("output_tokens", 0) or 0)
        cost = usage_info.get("cost_usd")

        # code-review item 7f6062e65ecb：同 spec 并发收工（impl-ocr 并行车道等
        # 同 spec 多 run 在飞，或 dashboard 线程同时 update_spec 同条目）时，
        # 跨两次调用的读改写不串行会导致后写者拿陈旧 prev_* 覆盖先写者的累计。
        # per-spec 锁内完成「读 → 相加 → 写回」整体。
        with _spec_accumulate_lock(spec_name):
            try:
                entry = self._pm.state_machine.read_one(spec_name) or {}
            except Exception:
                return
            if not isinstance(entry, dict):
                return
            prev_in = int(entry.get("_tokens_in", 0) or 0)
            prev_out = int(entry.get("_tokens_out", 0) or 0)
            new_in = prev_in + tokens_in
            new_out = prev_out + tokens_out
            # 缓存分项累计（spec 详情「缓存命中/命中率」展示）：字段缺失（历史 spec）从 0 起步
            prev_cache_read = int(entry.get("_cache_read_tokens", 0) or 0)
            prev_cache_creation = int(entry.get("_cache_creation_tokens", 0) or 0)
            updates = {
                "_tokens_in": new_in,
                "_tokens_out": new_out,
                "_cache_read_tokens": prev_cache_read
                + int(usage_info.get("cache_read_input_tokens", 0) or 0),
                "_cache_creation_tokens": prev_cache_creation
                + int(usage_info.get("cache_creation_input_tokens", 0) or 0),
            }
            # 成本：仅网关真实回传时累计；网关不回传则不写 _cost_usd（保持缺失语义）
            if cost is not None:
                try:
                    prev_cost = float(entry.get("_cost_usd", 0) or 0)
                    updates["_cost_usd"] = prev_cost + float(cost)
                except (TypeError, ValueError):
                    pass
            try:
                self._pm.state_machine.update_spec(spec_name, updates)
            except Exception as e:
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 累计写 STATE 失败 '{spec_name}': {e}",
                )
                return
        # 预算阈值检查（D4）：80% / 100% 均为警告级，不自动冻结
        self._check_token_budget(spec_name, new_in)

    def _check_token_budget(self, spec_name: str, tokens_in: int) -> None:
        """预算阈值告警（add-cost-observability D4）：80% / 100% 均为警告级，幂等不重复。

        配置 ``agents.token_budget_millions``（缺省 50，0=关闭）。越过 80% 线发警告级告警
        并置位 ``_token_warn_80``；越过 100% 线发警告级告警并置位 ``_token_alert_100``
        （2026-09-01 用户决策：两档均降为警告，不发严重事件）。
        告警 MUST NOT 修改 spec 状态（不自动冻结，design 决策有意为之）。
        """
        budget = self._pm._get_config("agents.token_budget_millions", 50)
        if not budget or budget <= 0:
            return  # 0 = 关闭
        budget_tokens = float(budget) * 1_000_000
        if budget_tokens <= 0:
            return
        ratio = tokens_in / budget_tokens

        try:
            entry = self._pm.state_machine.read_one(spec_name) or {}
        except Exception:
            entry = {}
        if not isinstance(entry, dict):
            entry = {}
        warn_flag = bool(entry.get("_token_warn_80", False))
        alert_flag = bool(entry.get("_token_alert_100", False))

        if ratio >= 1.0 and not alert_flag:
            self._send_token_alert(spec_name, tokens_in, budget, "warning", "预算 100% 警告")
            try:
                self._pm.state_machine.update_spec(spec_name, {"_token_alert_100": True})
            except Exception:
                pass
        elif ratio >= 0.8 and not warn_flag:
            self._send_token_alert(spec_name, tokens_in, budget, "warning", "预算 80% 提醒告警")
            try:
                self._pm.state_machine.update_spec(spec_name, {"_token_warn_80": True})
            except Exception:
                pass

    def _send_token_alert(
        self, spec_name: str, tokens_in: int, budget: float, severity: str, title: str
    ) -> None:
        """写一条 token 预算 human-escalation-alert（复用 AdminStore，与 pm_engine 同管道）。

        severity 统一为 warning（80%/100% 两档均为警告级，2026-09-01 用户降噪决策）。
        告警携带裁决注册表 choices（ignore/freeze_stop_loss/raise_budget）时保持
        未处理进待处理队列——前端告警区只对 unhandled 记录渲染裁决下拉，且
        alert-resolve 对 handled 记录 409 拒绝，born-handled 会让快照的 choices
        永不可消费、注册表与 alert-resolve 的 token_budget 场景全部落空
        （code-review item ded34cd04dc5；对本信号有意调整 2026-09-01
        「警告级不进待办」的降噪口径——「知情确认」选项本身即降噪出口）。
        choices 为空（信号未来退出注册表）时维持旧降噪决策：写入即标记
        handled，仅留历史记录。不修改 spec 状态。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION, severity_needs_human

            store = AdminStore(self._pm.project_root, self._pm.logger)
            pct = tokens_in / (float(budget) * 1_000_000) * 100.0
            payload = {
                "kind": ESCALATION,
                "signal_type": "token_budget",
                "spec": spec_name,
                "severity": severity,
                "description": (
                    f"{title}：spec '{spec_name}' 累计 input token 已用 "
                    f"{tokens_in / 1_000_000:.2f}M / 预算 {budget:.0f}M（{pct:.0f}%）"
                ),
                "evidence": (
                    f"_tokens_in={tokens_in}; budget_millions={budget}; " f"ratio={pct:.1f}%"
                ),
                "recommended_action": (
                    "检查是否失控烧钱；如需冻结请在 Dashboard / STATE.md 人工处置"
                    "（本告警不自动冻结 spec）"
                ),
            }
            # add-human-adjudication-choices 2.6：token_budget 在裁决注册表内
            # （ignore/freeze_stop_loss/raise_budget）——发射点快照 choices 进
            # 告警记录（本路径直写 AdminStore，不经 _send_human_escalation_alert）。
            from core.dashboard.data.adjudication_choices import choices_for

            choices = choices_for("token_budget")
            if choices:
                payload["choices"] = list(choices)
            rec = store.append(payload)
            # 注册表覆盖（choices 已快照）→ 保持未处理进待办队列，选项才有人可
            # 执行（item ded34cd04dc5）；无 choices 的警告级仍按 2026-09-01 降噪
            # 决策 born-handled，不占待办
            if not choices and not severity_needs_human(severity):
                store.mark_handled(rec["id"])
            self._pm.logger.warning(
                "agent_runner",
                f"token budget alert ({severity}) for '{spec_name}': "
                f"{tokens_in / 1_000_000:.2f}M / {budget:.0f}M",
            )
        except Exception as e:
            self._pm.logger.error(
                "agent_runner",
                f"Failed to send token budget alert for '{spec_name}': {e}",
            )

    def _record_verify_progress_tokens(
        self, spec_name: str, agent_type: str, usage_info: dict
    ) -> None:
        """验证链侧车：把 planner/judge run 的 usage 逐轮追加到 tokens.json（D3）。

        路径 ``.fenix/verify-progress/<spec>/tokens.json``，结构：
            {"runs": [{"agent_type": "planner-plan", "timestamp": "...",
                       "input_tokens": N, "output_tokens": M, "cost_usd": X|null}, ...]}
        场景执行为 Python 无 LLM，不入。报告合成时按本侧车求和（task 2.2）。

        仅 agent_type 以 ``planner`` 开头时记录；非 LLM run（verifier 场景执行）不计。
        写入失败静默跳过（观测增强，不能阻断主流程）。
        """
        if not isinstance(agent_type, str) or not agent_type.startswith("planner"):
            return
        if not isinstance(usage_info, dict):
            usage_info = {}
        tokens_json = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name / "tokens.json"
        )
        try:
            tokens_json.parent.mkdir(parents=True, exist_ok=True)
            # code-review item c01047460508：read_text → 内存 append → write_text
            # 整文件覆盖，既非原子（写中途崩溃留下半个 JSON，下次读取 JSONDecodeError
            # 回退 {} 后首写即清空既有全部历史）也无文件锁（并发两个 run 收工互相
            # 覆盖丢记录）。对齐同目录 maintenance_runs._append_token_run（item
            # d1836827425e 同病同方）：``.tokens.json.lock`` 做 fcntl.flock 互斥 +
            # tempfile + fsync + os.replace 原子落盘；读侧 JSONDecodeError 回退 {}
            # 语义不变（原子写后不再产生半文件）。
            lock_path = tokens_json.parent / f".{tokens_json.name}.lock"
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    data = {}
                    if tokens_json.is_file():
                        try:
                            loaded = json.loads(tokens_json.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            loaded = {}
                        if isinstance(loaded, dict):
                            data = loaded
                    runs = data.get("runs")
                    if not isinstance(runs, list):
                        runs = []
                    runs.append(
                        {
                            "agent_type": agent_type,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "input_tokens": int(usage_info.get("input_tokens", 0) or 0)
                            + int(usage_info.get("cache_creation_input_tokens", 0) or 0)
                            + int(usage_info.get("cache_read_input_tokens", 0) or 0),
                            "output_tokens": int(usage_info.get("output_tokens", 0) or 0),
                            "cost_usd": usage_info.get("cost_usd"),
                        }
                    )
                    data["runs"] = runs
                    content = json.dumps(data, ensure_ascii=False, indent=2)
                    # 原子替换：同目录进程唯一临时名 + fsync + os.replace
                    fd, tmp_str = tempfile.mkstemp(
                        prefix=f".{tokens_json.name}.",
                        suffix=".tmp",
                        dir=str(tokens_json.parent),
                    )
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as f:
                            f.write(content)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(tmp_str, str(tokens_json))
                    finally:
                        if os.path.exists(tmp_str):
                            try:
                                os.unlink(tmp_str)
                            except OSError:
                                pass
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
        except (OSError, json.JSONDecodeError):
            pass
