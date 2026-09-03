"""
runner.py — AgentRunner 门面（Agent execution engine for fenixd）.

Spawns claude CLI subprocesses to run implementer and verifier Agents.
Handles result parsing, retry logic, and token/turn budget control.
"""

import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from core.agent_runner.prompt_builder import PromptBuilder
from core.agent_runner.liveness import (
    AGENT_TERMINATE_GRACE_SECONDS,
    LIVE_ATTEMPT_STREAM_WINDOW_SECONDS,
    SUPERVISION_DEFAULTS,
    JUDGE_TIMEOUT_SECONDS,
    LIVENESS_SNIPPET_CHARS,
    LivenessSupervisor,
)
from core.agent_runner.liveness import LivenessSupervisor
from core.agent_runner.session import SessionTracker
from core.agent_runner.provider_circuit import (
    PROVIDER_CIRCUIT_4XX,
    PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
    PROVIDER_CIRCUIT_PROBE_SUCCESS_CODE,
    PROVIDER_CIRCUIT_THRESHOLD,
    PROVIDER_CIRCUIT_WINDOW_SECONDS,
    PROVIDER_DAILY_ATTEMPTS_WARN,
    PROVIDER_SWITCH_COOLDOWN_SECONDS,
    SWITCH_ERROR_CONN_PATTERNS,
    SWITCH_ERROR_TEXT_PATTERNS,
    ProviderCircuit,
)
from core.agent_runner.run_files import (
    archive_spec_runs,
    append_run_error,
    append_run_line,
    run_spec_part,
)
from core.agent_runner.token_budget import TokenAccountant
from core.agent_runner.v2_server import V2ServerManager
from core.v2_dev_server import (
    V2DevServerError,
    start as v2_start_dev_server,
    stop as v2_stop_dev_server,
    base_url as v2_base_url,
    cleanup_orphans as v2_cleanup_orphans,
)


# 无 provider 分配的 agent（含 Administrator）走默认网关（cc-switch）时 --model 用的
# 官方模型名。provider 已分配的 agent，其 --model 直接取该 agent 分配的网关模型名
# （model 字段，如 deepseek-v4-flash）——见 fenixd-sdk-model-routing：--model 即实际
# 发给网关的模型名，ANTHROPIC_MODEL 被 --model 覆盖不生效。本常量只作 fallback。
DEFAULT_GATEWAY_MODEL = "claude-sonnet-5"

# ── Administrator 处置状态实例文件（fix-admin-run-blocks-mainloop D3）─────
# 处置状态文件按 run 实例分离：每个 admin run 使用独立文件
# .fenix/admin_disposition-<run_id>.json，并行实例互不覆盖。
# 旧全局路径 .fenix/admin_disposition.json 不再读写（残留文件由拾取侧清扫）。
ADMIN_DISPOSITION_PREFIX = "admin_disposition-"
ADMIN_DISPOSITION_GLOB = "admin_disposition-*.json"


def admin_disposition_path(project_root: Path, run_id: str) -> Path:
    """某次 admin run 的处置状态实例文件路径。"""
    return Path(project_root) / ".fenix" / f"{ADMIN_DISPOSITION_PREFIX}{run_id}.json"


# ── V2 测试服务器（add-worktree-test-server）────────────────────────────
# per-run 隔离测试服务的端口分配基数，范围 [V2_TEST_PORT_BASE, V2_TEST_PORT_BASE+19]
# 主服务 8787 排除在外，并发运行（并行度 2，预留余量取 20 个高位端口段）不冲突。
V2_TEST_PORT_BASE = 19000
V2_TEST_PORT_RANGE = 20
V2_DEV_SERVER_MARKER = "fenix-v2-dev-server"

class AgentRunResult:
    """Result of a single Agent run."""

    def __init__(self, run_id: str, spec_name: str, agent_type: str,
                 success: bool, duration_seconds: float,
                 turns_used: int = 0, error: str = None, output: str = "",
                 branch: str | None = None,
                 provider_used: str | None = None, model_used: str | None = None,
                 chain_exhausted: bool = False,
                 worktree_dirty: list | None = None,
                 worktree_path=None, worktree_kept: bool = False):
        self.run_id = run_id
        self.spec_name = spec_name
        self.agent_type = agent_type
        self.success = success
        self.duration_seconds = duration_seconds
        self.turns_used = turns_used
        self.error = error
        self.output = output
        self.branch = branch  # worktree 分支名（成功时由 _execute_agent 填入）
        # add-provider-failover（design D5 / spec failover-dispatch「切换可观测」）：
        # 本次 run 实际使用的 provider 名与 model 名（链选择/切换后落盘可查）。
        self.provider_used = provider_used
        self.model_used = model_used
        # chain_exhausted：链上全部候选均处于 switch 冷却期，attempt 直接失败返回
        # （不启动进程、不计入 spec 重试消耗；design D3 / spec failover-dispatch）。
        self.chain_exhausted = chain_exhausted
        # fix-zero-change-blindspot：implementer 成功收工时、worktree cleanup **前**
        # 取证的 `git status --porcelain` 非空行清单。零变更哨需要「agent 是否真的
        # 动过文件」的证据；cleanup 后证据即销毁（曾致 Bash 写文件的真实工作被
        # 误判为空转、2.11h/$10 全丢）。None/空 = 无脏文件或非 implementer。
        self.worktree_dirty = worktree_dirty
        # worktree 继承（fast-track 打回重派复用）：worktree_path = 本轮使用的
        # worktree（fast-track 成功路径延迟清理、由 dispatch 层判定后处置）；
        # worktree_kept = runner 终态失败时已保留为复用遗产（dispatch 无需重复保留）。
        self.worktree_path = worktree_path
        self.worktree_kept = worktree_kept

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "spec_name": self.spec_name,
            "agent_type": self.agent_type,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "turns_used": self.turns_used,
            "error": self.error,
            "branch": self.branch,
            "provider_used": self.provider_used,
            "model_used": self.model_used,
            "chain_exhausted": self.chain_exhausted,
            "output_summary": self.output[-500:] if self.output else "",
        }


class AdminDisposition:
    """Administrator Agent 一次处置的结果（run_administrator 返回）。"""

    def __init__(self, run_id: str, spec: str | None = None, success: bool = True,
                 problem: str = "", actions_taken: str = "", result: str = "",
                 escalate: bool = False, recommended_action: str = "",
                 summary: str = "", error: str = "", output: str = "",
                 family_waiver: bool = False):
        self.run_id = run_id
        self.spec = spec
        self.success = success
        self.problem = problem
        self.actions_taken = actions_taken
        self.result = result
        self.escalate = escalate
        self.recommended_action = recommended_action
        self.summary = summary
        self.error = error
        self.output = output
        # family_explosion 处置：Administrator 对该父 SPEC「放行一次」。
        # 由 admin_monitor 落成 _family_waiver=true（单次豁免，用后复位）。
        self.family_waiver = family_waiver

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "spec": self.spec,
            "success": self.success,
            "problem": self.problem,
            "actions_taken": self.actions_taken,
            "result": self.result,
            "escalate": self.escalate,
            "recommended_action": self.recommended_action,
            "summary": self.summary,
            "error": self.error,
        }



class AgentRunner:
    """
    Execute Agents via claude CLI subprocess.

    Manages retry logic, run limits, and result tracking.
    """

    def __init__(self, config: dict, worktree_manager, state_machine,
                 project_root: Path, logger):
        self.config = config
        self.worktree_manager = worktree_manager
        self.state_machine = state_machine
        self.project_root = project_root
        self.logger = logger

        # 在跑 agent 登记表（run_id → Popen）。跨线程共享（fix-admin-run-blocks-
        # mainloop tasks 4.4）：admin run 在 worker 池线程登记/摘除，主循环派发的
        # implementer/verifier 在主线程登记；liveness 监督与 shutdown 关停均以
        # list(...) 快照迭代、pop 带 default——全部单键原子操作，无读改写竞态，
        # 不加锁（持锁跨 grace 等待窗口反而引入死锁面）。
        # _daily_run_count 仅在 _execute_agent（implementer/verifier/planner）路径
        # 自增，admin run 不经过该路径，无跨线程写。
        self._running_agents: Dict[str, subprocess.Popen] = {}
        self._daily_run_count = 0


    # ── V2 per-run 隔离测试服务（add-worktree-test-server）─────────────────────






    # ── provider 熔断（fix-stashpop-deadlock：provider-fault-fuse） ──────────────



    def _now(self) -> float:
        """单调时间戳（测试可覆写）。用 time.monotonic 避免时钟回拨影响窗口。"""
        return time.monotonic()



    # ── provider 切换冷却（add-provider-failover：failover-dispatch） ──────────








    def run_implementer(self, spec_name: str) -> AgentRunResult:
        """
        Run the implementer Agent for a SPEC.

        Steps:
        1. Create worktree
        2. Build claude prompt
        3. Execute via subprocess
        4. Parse result
        5. Clean up worktree
        6. Return result
        """
        run_id = f"impl-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, "implementer", run_id)

    def run_verifier(self, spec_name: str) -> AgentRunResult:
        """Run the verifier Agent for a SPEC."""
        run_id = f"verify-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, "verifier", run_id)

    def run_planner(self, spec_name: str, mode: str) -> AgentRunResult:
        """Run the Planner Agent for a SPEC.

        Args:
            spec_name: SPEC名称
            mode: "plan"（生成测试场景）或 "judge"（判定验证结果）
        """
        if mode not in ("plan", "judge"):
            raise ValueError(f"mode 必须是 'plan' 或 'judge'，实际: {mode}")
        run_id = f"planner-{mode}-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, f"planner-{mode}", run_id)

    def run_fast_track(self, spec_name: str) -> AgentRunResult:
        """Run the Fast-Track Agent for a SPEC (single run: implement + verify).

        Fast-track run 同时完成实现与验证（实现+场景设计+验证+判定）。
        生成的分支与成功路径 merge 语义与 implementer 一致；budget 沿用
        impl_run_budget（走 impl- 前缀 run_id，复用既有计数/对账路径）。
        """
        run_id = f"impl-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, "fast-track", run_id)

    def run_repair(self, spec_name: str, wt_path: Path,
                   conflict_summary: dict | None = None) -> AgentRunResult:
        """Run the Repair Agent for a SPEC in an existing worktree.

        add-merge-back-repair-lane D5：merge-back 语义冲突失败后，在实现分支
        一侧原地修复（把 main 合进分支、解决冲突、跑测试、commit）。与普通
        implementer 的差异：
        - run_id 前缀 ``repair-<spec>-<ts>``（Dashboard/runs 可辨识，不计入
          fix 族谱；repair<->fix 异名不触发同根互斥）；
        - **不创建新 worktree**：使用调度层解析好的 repair 载体（原地或换壳）；
        - token 记所属 spec 名下（走既有 ``_accumulate_token_usage`` ——
          repair agent 的消耗计入实现预算，design「repair 轮计入该 spec 的
          实现预算」）；
        - worktree 生命周期交由调用层（dispatch）管理：成功与失败都不清理
          worktree（worktree_kept=True），保证多轮 repair 可原地复用或终态回收。

        Args:
            spec_name: SPEC 名称。
            wt_path: repair 载体 worktree 路径（调度层经三态解析）。
            conflict_summary: 冲突分类摘要 dict（prompt 注入，缺省 {}）。
        """
        run_id = f"repair-{spec_name}-{int(time.time())}"
        return self._execute_agent(
            spec_name, "repair", run_id,
            pre_wt_path=wt_path,
            conflict_summary=conflict_summary or {},
        )

    def run_administrator(self, signal: dict) -> AdminDisposition:
        """唤起 Administrator Agent 处置困境信号（administrator-agent spec）。

        与 implementer/verifier 不同：Administrator 是运维角色，直接在 main 树
        （project_root）操作框架，不创建 worktree（design D4）。产物写入
        .fenix/runs/admin-<spec>-<ts>.jsonl；处置结果从管理员按 prompt 写入的
        实例文件 .fenix/admin_disposition-<run_id>.json 读取，由 daemon 落盘到
        admin_alerts.json。

        fix-admin-run-blocks-mainloop D3：处置状态文件按 run 实例分离——并行
        多实例（worker 池）各自 clear/write/read 自己的文件，互不覆盖。

        Args:
            signal: admin_monitor 检测到的困境信号 dict
                （signal_type/spec/severity/description/evidence/recommended_action）。
        """
        spec = signal.get("spec") or "global"
        run_id = f"admin-{spec}-{int(time.time())}"
        # 实例路径注入提示词（prompt_builder 把写入指令指向该文件）
        disp_path = admin_disposition_path(self.project_root, run_id)
        prompt_detail = dict(signal)
        prompt_detail["disposition_path"] = str(disp_path)
        prompt = self._build_prompt(spec, "administrator", detail=prompt_detail)

        # improve-config-ui-tabs：Administrator 运行时解析链（design D4）
        #   1. agents.models.administrator assignment → 用分配 model 并注入 provider env（直连）
        #   2. 无 assignment → 沿用旧逻辑 _get_admin_model()（admin.agent_model → 默认网关）
        assignment = self._get_agent_model_assignment("administrator")
        env_overrides: Dict[str, str] = {}
        if assignment:
            # 取链首选（Administrator 不接入 attempt 级 failover，仅用首选直连）
            provider, model_override = assignment[0]
            env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
            env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
            env_overrides["ANTHROPIC_MODEL"] = model_override
            env_overrides["CLAUDE_CONFIG_DIR"] = str(
                self._ensure_agent_config_dir(provider["name"])
            )
            for k, v in (provider.get("env") or {}).items():
                env_overrides[k] = v
            # 观测：run jsonl 写 provider_marker，与 dispatch attempt 路径同口径，
            # 时间轴才能展示 Administrator 实际驱动的 model@provider；
            # Administrator 不接 failover，链内下标恒 0/1
            self._write_provider_marker(
                run_id, spec, "administrator",
                provider["name"], model_override, 0, 1,
            )
        else:
            model_override = self._get_admin_model()

        # fix-admin-self-heal：唤起前先落 pending disposition，保证即使 admin 被
        # kill（如 daemon 重启/崩溃）也有记录可回溯；monitor 会检测无最终结果的
        # pending 并升级人工，避免「admin 死了但没有任何告警」。
        try:
            from core.admin_store import AdminStore, DISPOSITION
            AdminStore(self.project_root, getattr(self, "logger", None)).append({
                "kind": DISPOSITION,
                "status": "pending",
                "signal_type": signal.get("signal_type"),
                "spec": spec,
                "admin_run_id": run_id,
                "description": (f"Administrator 处置中（run {run_id}），尚未完成；"
                                f"若长时间无最终结果，AdminMonitor 会自动升级人工"),
                "result": "pending",
                "recommended_action": signal.get("recommended_action"),
            })
        except Exception:
            pass

        self._clear_admin_disposition(disp_path)
        try:
            output, turns, _session_id = self._run_claude(
                prompt, self.project_root, run_id, model_override, env_overrides,
                max_turns=self._get_config("agents.max_turns", 300),
                spec_name=spec,
            )
            success = True
            error = ""
        except Exception as e:
            output = ""
            success = False
            error = str(e)

        disp = self._read_admin_disposition(disp_path)
        # 读取即清理自身实例文件：内容已捕获进 AdminDisposition 返回给调用方落
        # final 记录，文件不再有读者；不清理会随并行实例累积成垃圾。
        self._delete_admin_disposition(disp_path)
        return AdminDisposition(
            run_id=run_id,
            spec=disp.get("spec") or signal.get("spec"),
            success=success,
            problem=disp.get("problem") or signal.get("description", ""),
            actions_taken=disp.get("actions_taken") or "",
            result=disp.get("result") or ("resolved" if success else "failed"),
            escalate=bool(disp.get("escalate", False)),
            recommended_action=disp.get("recommended_action") or "",
            summary=disp.get("summary") or "",
            error=error,
            output=output,
            family_waiver=bool(disp.get("family_waiver", False)),
        )

    def _clear_admin_disposition(self, disp_path: Path):
        """清空本次 run 的处置状态文件（若残留），避免读到陈旧数据。

        fix-admin-run-blocks-mainloop D3：路径按 run 实例传入，不再使用全局
        固定文件名——并行实例只清理自己的文件。
        """
        try:
            if disp_path.exists():
                disp_path.unlink()
        except OSError:
            pass

    def _delete_admin_disposition(self, disp_path: Path):
        """run 结束后删除自己的处置状态实例文件（内容已在内存中/已落 final）。"""
        try:
            disp_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_admin_disposition(self, disp_path: Path) -> dict:
        """读取管理员按 prompt 写入的处置记录（实例文件，路径按 run 注入）。

        文件缺失/损坏返回空 dict（调用方用信号详情兜底）。
        """
        try:
            data = json.loads(disp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        at = data.get("actions_taken")
        if isinstance(at, list):
            # 列表型动作以换行符连接，每条动作独立一行（design D5）
            data["actions_taken"] = "\n".join(str(x) for x in at if x)
        elif at is None:
            data["actions_taken"] = ""
        elif not isinstance(at, str):
            data["actions_taken"] = str(at)
        sm = data.get("summary")
        if isinstance(sm, list):
            # 列表型叙述以换行符连接，每段独立一行
            data["summary"] = "\n".join(str(x) for x in sm if x)
        elif sm is None:
            data["summary"] = ""
        elif not isinstance(sm, str):
            data["summary"] = str(sm)
        return data

    def _get_admin_model(self) -> str:
        """Administrator 模型名：admin.agent_model > 默认网关 fallback 常量。"""
        admin_model = self._get_config("admin.agent_model", None)
        if admin_model:
            return admin_model
        return DEFAULT_GATEWAY_MODEL

    def _build_isolated_settings(self) -> dict:
        """构造隔离 settings.json：enabledPlugins / hooks（spec D2/D3）。

        从 ~/.claude/settings.json 复制 enabledPlugins（缺省 superpowers）。hooks 从
        .fenix/agent-settings.json 复制（PreToolUse block-image-read）。不复制任何 env
        模型名映射——那属于 cc-switch 网关、对直连 Provider 无用且有毒化子代理解析的
        风险（如陈旧 hy3）。Provider 的 ANTHROPIC_MODEL/BASE_URL/API_KEY 经进程 env 注入。
        """
        settings: Dict[str, Any] = {}
        source: Dict[str, Any] = {}
        home_settings = Path.home() / ".claude" / "settings.json"
        try:
            if home_settings.is_file():
                loaded = json.loads(home_settings.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    source = loaded
        except (OSError, json.JSONDecodeError):
            source = {}

        plugins = source.get("enabledPlugins")
        if isinstance(plugins, dict) and plugins:
            settings["enabledPlugins"] = plugins
        else:
            settings["enabledPlugins"] = {"superpowers@claude-plugins-official": True}

        agent_settings = self.project_root / ".fenix" / "agent-settings.json"
        if agent_settings.is_file():
            try:
                loaded = json.loads(agent_settings.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("hooks"), dict):
                    settings["hooks"] = loaded["hooks"]
            except (OSError, json.JSONDecodeError):
                pass

        # 不复制 ~/.claude/settings.json 的 env（ANTHROPIC_DEFAULT_* / CLAUDE_CODE_SUBAGENT_MODEL
        # 等 cc-switch 网关映射）——直连 Provider 不需要，且会毒化子代理模型解析（陈旧 hy3）。
        return settings

    def _ensure_agent_config_dir(self, provider_name: str) -> Path:
        """按需生成并返回 Provider 的隔离配置目录（spec D1/D2/D5）。

        目录：.fenix/agent-config/<provider_name>/，含 settings.json 与指向
        ~/.claude 的 skills/plugins symlink（源目录不存在则跳过，优雅降级）。
        幂等：settings.json 已存在则跳过重建；并发首次创建由原子 mkdir +
        temp+rename 写文件兜底，内容确定无副作用。
        """
        cfg_dir = self.project_root / ".fenix" / "agent-config" / provider_name
        marker = cfg_dir / "settings.json"
        if marker.is_file():
            return cfg_dir
        try:
            cfg_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return cfg_dir

        settings = self._build_isolated_settings()
        try:
            tmp = cfg_dir / ".settings.tmp"
            tmp.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, marker)
        except OSError:
            pass

        for name in ("skills", "plugins"):
            src = Path.home() / ".claude" / name
            dst = cfg_dir / name
            try:
                if src.is_dir() and not dst.exists():
                    dst.symlink_to(src, target_is_directory=True)
            except OSError:
                pass
        return cfg_dir

    def _select_chain_candidate(self, chain, spec_name: str, agent_type: str,
                                 now: float | None = None) -> int:
        """在候选链上选择首个「未熔断且未处于 switch 冷却」的候选下标（add-provider-failover）。

        design D3：链选择跳过 switch-cooldown 中或 4xx 熔断中的候选；返回值用于落点。
        全部候选都冷却 → 返回 -1（调用方据 chain_exhausted 失败语义处理，不启动进程、
        不计入 spec 重试消耗）。

        Args:
            chain: ConfigLoader.get_agent_model_assignment 返回的候选链
                （list[(provider_dict, model)]），可为空。
        """
        now = self._now() if now is None else now
        for idx, (provider, _model) in enumerate(chain):
            name = provider["name"]
            if self.is_circuit_open(name, now=now):
                continue
            if self.is_switch_cooldown(name, now=now):
                continue
            return idx
        return -1

    def _execute_agent(self, spec_name: str, agent_type: str, run_id: str,
                       pre_wt_path: Path | None = None,
                       conflict_summary: dict | None = None) -> AgentRunResult:
        """Core agent execution logic with retry support.

        fix-fenix-token-waste：
        - 每次 attempt 使用独立 run_id（-a<attempt>），产物文件与尝试一一对应
        - implementer 失败重试复用同一 worktree + `claude --resume` 续跑，不从零
          全量重跑；其余 agent_type 维持每次全新 worktree
        - max_turns 在 _run_claude 内强制

        add-provider-failover（design D1/D2/D3/D4/D5）：
        - 该 agent_type 的 provider 分配为**按序候选链**；每次 attempt 启动前用
          _select_chain_candidate 选首个未冷却候选（链指针按 agent_type 记忆于本实例）。
        - 切换类错误（classify_switch_error）失败 → 该 provider 进入 switch 短冷却，同 run
          后续 attempt 自动前进到下一候选；仅当 provider 未变时才 --resume 原会话
          （fix 跨 provider resume：session 在旧 CLAUDE_CONFIG_DIR，切换后续跑必然
          'No conversation found' 秒挂）；4xx 配额类维持既有熔断不前进。
        - 全链冷却 → 直接失败返回（chain_exhausted，不启动进程、不消耗 spec 重试）。
        - 切换后 CLAUDE_CONFIG_DIR 隔离目录随候选同步切换；run jsonl 写 provider_marker；
          AgentRunResult 带 provider_used/model_used；每 provider 当日计数超阈值告警。

        add-merge-back-repair-lane（D5）：repair run 传入 ``pre_wt_path``
        （调度层解析好的实现分支载体 worktree）与 ``conflict_summary``
        （prompt 注入）。pre_wt_path 非 None 时**不创建新 worktree**，
        直接在该 worktree 内工作——repair 原地修复语义。
        """
        max_retries = self._get_config("agents.max_retries", 3)
        start_time = time.time()
        wt_path = pre_wt_path
        session_id = None
        # session_id 所属 provider（None=默认网关）：session 存在于其创建时的
        # CLAUDE_CONFIG_DIR，跨 provider 续跑必然 'No conversation found'（fix）。
        session_provider = None
        # 实例级链指针（design D1：cursor 按 agent_type 记忆）。-1 表示尚未选定。
        chain_cursor = -1
        last_provider_used = None  # 用于 "provider switched" 跨 attempt 打点
        kept_wt_path = None  # worktree-reuse：fast-track 终态失败保留的复用遗产路径
        self._last_model_used = None  # 用于 model_changed 日志留痕（design D3）

        for attempt in range(1, max_retries + 1):
            attempt_run_id = f"{run_id}-a{attempt}"
            self.logger.info(
                "agent_runner",
                f"Running {agent_type} for '{spec_name}' (attempt {attempt}/{max_retries})",
                {"run_id": attempt_run_id},
            )

            # Check daily run limit
            self._check_daily_limit()

            # ── 候选链解析与选择（add-provider-failover） ──
            chain = self._get_agent_model_assignment(agent_type) or []
            if not chain:
                # 无 provider 分配：走默认网关（cc-switch），无链可选。provider_name=None。
                provider_name = None
                provider = None
                model = None
            else:
                # 链指针推进：上次因切换类失败已前移的，保持前移（design D1/D3）；
                # 否则从头选首个未冷却候选。4xx 熔断拦截态也算"不可用"跳过。
                if chain_cursor < 0:
                    chain_cursor = self._select_chain_candidate(chain, spec_name, agent_type)
                if chain_cursor < 0:
                    # 无可用候选。区分两类根因（design D3 / spec failover-dispatch）：
                    # - 全部候选仅因 4xx 熔断（is_circuit_open）被跳过 → 维持既有
                    #   "provider circuit open" 错误语义（不污染 error 文本、便于 admin/dashboard
                    #   区分 provider 故障），报告首个 4xx 熔断候选。
                    # - 否则（含 switch 冷却 / 全链冷却）→ chain_exhausted 失败语义，
                    #   不启动进程、不计入 spec 重试消耗。
                    first_4xx_open = None
                    for (provider, _m) in chain:
                        if self.is_circuit_open(provider["name"]):
                            first_4xx_open = provider["name"]
                            break
                    if first_4xx_open is not None:
                        circuit_err = self._circuit_open_error(first_4xx_open)
                        self.logger.warning(
                            "agent_runner",
                            f"Suppressed {agent_type} dispatch for '{spec_name}': {circuit_err}",
                        )
                        return AgentRunResult(
                            attempt_run_id, spec_name, agent_type,
                            success=False, duration_seconds=time.time() - start_time,
                            error=circuit_err, provider_used=first_4xx_open,
                        )
                    exhausted_err = (
                        f"provider chain exhausted for {agent_type} '{spec_name}': "
                        f"all {len(chain)} candidates in switch/4xx cooldown"
                    )
                    self.logger.error("agent_runner", exhausted_err)
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=exhausted_err, chain_exhausted=True,
                    )
                provider, model = chain[chain_cursor]
                provider_name = provider["name"]

                # ── 4xx 熔断拦截（fix-stashpop-deadlock：provider-fault-fuse） ──
                # 仅对当前选中候选生效；若已熔断（冷却未到期），直接失败返回、不启动 claude、
                # 不创建 worktree/autostash、不计入 spec 连续失败重试（design D5）。冷却到期后
                # 首个真实派发作为半开探针（design D4）。
                if self.is_circuit_open(provider_name):
                    circuit_err = self._circuit_open_error(provider_name)
                    self.logger.warning(
                        "agent_runner",
                        f"Suppressed {agent_type} dispatch for '{spec_name}': {circuit_err}",
                    )
                    # 不创建 worktree、不进入重试计数。直接以熔断错误返回。
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=circuit_err, provider_used=provider_name, model_used=model,
                    )

                # 选中且未熔断 → 计一次当日 attempt（design D5 / spec 4.2），后续跨 attempt
                # 切换打点依赖 last_provider_used。
                self._record_daily_provider_attempt(provider_name)

            # fast-track 与 implementer 同语义：跨 attempt 复用同一 worktree（失败续跑）。
            # repair 沿用同一语义：repair run 的 attempt 复用同一个 repair worktree
            #（add-merge-back-repair-lane——worktree 由调度层解析，内部 attempt 不重造）。
            reuse_worktree = (
                agent_type in ("implementer", "fast-track", "repair")
                and wt_path is not None
            )

            # 跨 attempt 切换打点（design D5 / spec failover-dispatch「切换留痕」）：
            # 本次实际使用的 provider 与上一次不同 → 输出 "provider switched" 日志；
            # 当 model 也发生变更时附带 `model_changed: <old>→<new>`（design D3）。
            # 放在 reuse_worktree 判断之后、运行之前，确保本次 dispatch 的 provider 已确定。
            if last_provider_used is not None and provider_name is not None \
                    and provider_name != last_provider_used:
                switch_msg = (
                    f"provider switched {last_provider_used} → {provider_name} "
                    f"for '{spec_name}'"
                )
                last_model = getattr(self, "_last_model_used", None)
                if model and last_model and model != last_model:
                    switch_msg += f" — model_changed: {last_model}→{model}"
                self.logger.info("agent_runner", switch_msg)
            # 记忆本次使用的模型名（供下次 attempt 切换时判定 model_changed，design D3）
            if model:
                self._last_model_used = model
            # 更新记忆：下次 attempt 据以判断切换并打点（design D5）。
            last_provider_used = provider_name

            # Create or reuse worktree
            if wt_path is None:
                wt_path = self.worktree_manager.create(spec_name, agent_type)
                if wt_path is None:
                    error_msg = "Failed to create worktree"
                    self.logger.error("agent_runner", error_msg)
                    if attempt < max_retries:
                        time.sleep(5)
                        continue
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=error_msg, provider_used=provider_name, model_used=model,
                    )
                # add-worktree-test-server（D2 派发前启动）：worktree 创建成功后立即
                # 为其启动专属 dev-server，供本次 attempt 的测试请求命中 worktree 副本。
                self._v2_launch_for_worktree(wt_path)
            else:
                self.logger.info(
                    "agent_runner",
                    f"Reusing worktree {wt_path} for '{spec_name}' (attempt {attempt}, resume)",
                )
                if agent_type == "fast-track":
                    # 跨 attempt 复用同一 worktree：补记继承痕迹（prompt 注入用）
                    self.worktree_manager.mark_reused(
                        spec_name, wt_path,
                        self.worktree_manager.get_branch_name(wt_path) or "",
                    )

            # ── 观测：run jsonl 写 provider_marker（design D5 / spec failover-dispatch） ──
            # attempt 启动时写入，指明所用 provider/model 与链内下标，事后可追溯实际网关。
            if provider_name is not None:
                self._write_provider_marker(
                    attempt_run_id, spec_name, agent_type,
                    provider_name, model, chain_cursor, len(chain),
                )

            # Build and execute the prompt
            try:
                if agent_type == "repair":
                    # repair prompt 注入冲突摘要（add-merge-back-repair-lane D5）
                    prompt = self._build_prompt(
                        spec_name, agent_type, detail=conflict_summary or {},
                    )
                else:
                    prompt = self._build_prompt(spec_name, agent_type)
                env_overrides: Dict[str, str] = {}
                # add-worktree-test-server（D1 注入）：把该 worktree 专属 dev-server 地址
                # 注入 agent 运行环境，使 Playwright baseURL 指向 worktree 副本而非主 8787。
                # 未启动 dev-server（端口冲突/启动失败）时不注入，测试回退缺省 8787。
                env_overrides.update(self._v2_inject_env(wt_path))
                if provider is not None:
                    env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
                    env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
                    env_overrides["ANTHROPIC_MODEL"] = model
                    # add-agent-llm-isolation：Provider 生效时完全隔离——CLAUDE_CONFIG_DIR
                    # 指向独立配置目录，彻底绕过 ~/.claude/settings.json 的 env 覆盖，
                    # 使 Provider 的 baseurl/apikey/model 绝对生效（spec D1）。
                    # add-provider-failover：隔离目录随候选同步切换（design D4 / task 3.2）。
                    env_overrides["CLAUDE_CONFIG_DIR"] = str(
                        self._ensure_agent_config_dir(provider["name"])
                    )
                    # 注入 provider 自定义环境变量（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）
                    for k, v in (provider.get("env") or {}).items():
                        env_overrides[k] = v
                    model_override = model
                else:
                    # 未分配 agent（含 Administrator）走默认网关（cc-switch），--model 用
                    # 官方模型名常量，由 cc-switch 网关自行映射到可用模型。
                    model_override = DEFAULT_GATEWAY_MODEL
                output, turns, run_session_id, usage_info = self._run_claude(
                    prompt, wt_path, attempt_run_id, model_override, env_overrides,
                    resume_session_id=self._resumable_session_id(
                        session_id, session_provider, provider_name, reuse_worktree,
                    ),
                    max_turns=self._get_config("agents.max_turns", 300),
                    spec_name=spec_name,
                )
                if run_session_id:
                    session_id = run_session_id
                    session_provider = provider_name
                success = True
                error = None
            except Exception as e:
                output = ""
                turns = 0
                success = False
                error = str(e)
                # add-cost-observability（D1）：_run_claude 抛错（超时/kill/非 0 退出/
                # rc==0 但 result 标记 error），stream-json 终态已被丢弃，按 0 计 usage，
                # 仅 DEBUG 留痕（异常早夭的 run 消耗小，与 jsonl 考古一致偏差可接受）。
                usage_info = self._extract_usage_info(None)
                self.logger.debug(
                    "agent_runner",
                    f"{agent_type} for '{spec_name}' ended in error — tokens counted "
                    f"as 0 (add-cost-observability): {error}",
                )
                # 4xx 熔断计数（fix-stashpop-deadlock：provider-fault-fuse）。
                # 仅对「已分配 provider」且错误文本能解析出 HTTP 4xx 的情况计数（design D4）；
                # 5xx/网络错误不计数（瞬态，走既有 retry）。解析不到 code 视为失败、不计数。
                if provider_name:
                    code = self.parse_api_error_status(error)
                    if code is not None and code in PROVIDER_CIRCUIT_4XX:
                        was_half_open = False
                        st = self.provider_circuits.get(provider_name)
                        if st and st.get("count", 0) >= PROVIDER_CIRCUIT_THRESHOLD \
                                and st.get("cooldown_until", 0) > 0 \
                                and st["cooldown_until"] <= self._now():
                            # 半开探针仍 4xx → 重新冷却（design D4），不重复计数。
                            was_half_open = True
                        self._record_provider_4xx(provider_name, code)
                        if was_half_open:
                            self._record_provider_probe(provider_name, success=False)
                    # add-provider-failover（design D2/D3）：切换类错误 → 该 provider 进入
                    # switch 短冷却，同 run 后续 attempt 前进到下一候选（跨 provider 不 resume，
                    # 见 _resumable_session_id）。
                    # 4xx 配额/鉴权类不触发（维持既有熔断语义、链指针不动）。
                    elif self.classify_switch_error(error):
                        self._record_switch_cooldown(provider_name)
                        # 仅当链上还有后续候选才前进指针；否则保持当前（全链耗尽将在下一
                        # attempt 的 _select_chain_candidate 中判定为 chain_exhausted）。
                        if chain_cursor + 1 < len(chain):
                            chain_cursor += 1
                # implementer 失败后从产物尾部提取 session_id，供下一次 attempt --resume 续跑
                if agent_type == "implementer":
                    run_file = self.project_root / ".fenix" / "runs" / f"{attempt_run_id}.jsonl"
                    sid = self._extract_session_id(run_file)
                    if sid:
                        session_id = sid
                        session_provider = provider_name
                # fix 跨 provider resume：resume 报「会话不存在」说明该 session_id 已失效
                # （典型：上一次 attempt 切换了 provider，session 在旧 CLAUDE_CONFIG_DIR 里），
                # 若不清除，后续 attempt 会带着死 id 反复秒挂、烧尽全部重试。
                if error and "No conversation found with session ID" in error:
                    session_id = None
                    session_provider = None

            # 记录分支名（在 cleanup 之前，cleanup 会从 _wt_branches 中移除）
            branch = self.worktree_manager.get_branch_name(wt_path) if success else None

            # 成功时，把 worktree 中的 .fenix-run-result.json 复制到主树。
            if success:
                wt_result = wt_path / ".fenix-run-result.json"
                root_result = self.project_root / ".fenix-run-result.json"
                if wt_result.exists():
                    try:
                        root_result.write_text(
                            wt_result.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                    except OSError:
                        pass

            if success:
                # 半开探针闭合（fix-stashpop-deadlock）：若该 provider 此前已进入熔断但
                # 冷却已到期（半开），此派发成功即视为网关恢复，闭合熔断（design D4）。
                if provider_name:
                    st = self.provider_circuits.get(provider_name)
                    if st and st.get("cooldown_until", 0) > 0 and st["cooldown_until"] <= self._now():
                        self._record_provider_probe(provider_name, success=True)
                # add-worktree-test-server（D2 终态回收）：worktree 清理前先回收其 dev-server。
                # fast-track 例外：成功不清理——硬校验/守卫在 dispatch 层判定，失败时
                # 保留 worktree 供重派继承（worktree-reuse）；通过则由 dispatch 在
                # merge 后统一清理。dev-server 随 dispatch 层处置一并回收。
                wt_dirty: list = []
                if agent_type in ("implementer", "fast-track"):
                    # fix-zero-change-blindspot：cleanup 前取证 worktree dirty 状态
                    #（仅 implementer / fast-track——零变更哨对两者都生效）。
                    st = subprocess.run(
                        ["git", "-C", str(wt_path), "status", "--porcelain"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if st.returncode == 0:
                        wt_dirty = [l for l in st.stdout.splitlines() if l.strip()]
                elif agent_type == "repair":
                    # repair 现场取证：冲突解决是否已 commit（dispatch 层据此
                    # 判断 re-merge-back 前的现场状态，add-merge-back-repair-lane）。
                    st = subprocess.run(
                        ["git", "-C", str(wt_path), "status", "--porcelain"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if st.returncode == 0:
                        wt_dirty = [l for l in st.stdout.splitlines() if l.strip()]
                # add-merge-back-repair-lane：repair 与 fast-track 同语义，
                # 成功不清理 worktree——冲突解决成果仍在分支上，交给 dispatch
                # 层的 re-merge-back 决定终态；多轮 repair 需原地复用现场。
                if agent_type in ("fast-track", "repair"):
                    pass  # 延迟清理：worktree 与 dev-server 均由 dispatch 层处置
                else:
                    self._v2_stop_for_worktree(wt_path)
                    # 成功：清理 worktree（保留分支供 merge-back），返回结果
                    self.worktree_manager.cleanup(wt_path, success=True)
                duration = time.time() - start_time
                self._daily_run_count += 1
                self.logger.info(
                    "agent_runner",
                    f"{agent_type} succeeded for '{spec_name}'",
                    {"run_id": attempt_run_id, "attempt": attempt, "turns": turns,
                     "provider": provider_name, "model": model},
                )
                # add-cost-observability（D1）：收工成功 → 累加 usage 到 STATE 内部字段
                self._accumulate_token_usage(spec_name, usage_info)
                # 验证链侧车：planner/judge run 的 usage 逐轮追加（D3）
                self._record_verify_progress_tokens(spec_name, agent_type, usage_info)
                return AgentRunResult(
                    attempt_run_id, spec_name, agent_type,
                    success=True, duration_seconds=duration,
                    turns_used=turns, output=output,
                    branch=branch, provider_used=provider_name, model_used=model,
                    worktree_dirty=wt_dirty,
                    worktree_path=(wt_path if agent_type in ("fast-track", "repair") else None),
                )
            else:
                self.logger.warning(
                    "agent_runner",
                    f"{agent_type} failed for '{spec_name}' (attempt {attempt})",
                    {"run_id": attempt_run_id, "error": error, "provider": provider_name},
                )
                # 失败后的 worktree 处理（worktree-reuse：fast-track 与 implementer
                # 同语义，跨 attempt 复用同一 worktree 续跑）：
                # - implementer / fast-track / repair 且还有重试：保留 worktree（连同其
                #   dev-server），下次 attempt 续跑；dev-server 随之复用，不重复启停。
                # - fast-track 终态失败：保留目录与分支登记为复用遗产，下轮重派在同一
                #   worktree 继承上一轮成果（不再从零重做）。
                # - repair 终态失败：保留 worktree（add-merge-back-repair-lane：
                #   worktree 生命周期交由 dispatch 层——fallback 或下一轮复用）。
                # - 其他 / 终态失败：清理 worktree 并回收其 dev-server，下次 attempt 全新创建。
                if attempt < max_retries:
                    time.sleep(10)  # Wait before retry
                    if agent_type not in ("implementer", "fast-track", "repair"):
                        self._v2_stop_for_worktree(wt_path)
                        self.worktree_manager.cleanup(wt_path, success=False)
                        wt_path = None
                else:
                    self._v2_stop_for_worktree(wt_path)
                    if agent_type == "fast-track":
                        self.worktree_manager.keep_for_reuse(spec_name, wt_path)
                        kept_wt_path = wt_path
                    elif agent_type == "repair":
                        # 终态失败保留现场：dispatch 层负责回收（fallback 清理）
                        kept_wt_path = wt_path
                    else:
                        self.worktree_manager.cleanup(wt_path, success=False)
                    wt_path = None

        # All retries exhausted
        duration = time.time() - start_time
        # add-cost-observability（D1）：终态失败也累加（末次 attempt 的 usage，
        # 异常早夭时为 0），保证预算告警在失败轮同样累计、不漏计。
        self._accumulate_token_usage(spec_name, usage_info)
        # 验证链侧车（D3）：终态失败的 planner run 同样逐轮追加
        self._record_verify_progress_tokens(spec_name, agent_type, usage_info)
        return AgentRunResult(
            run_id, spec_name, agent_type,
            success=False, duration_seconds=duration,
            error=f"All {max_retries} attempts failed. Last error: {error}",
            provider_used=provider_name, model_used=model,
            worktree_path=kept_wt_path,
            worktree_kept=kept_wt_path is not None,
        )

    # ── token 累计与预算告警（add-cost-observability D1 / D4）──────────────────












    def _run_claude(self, prompt: str, cwd: Path, run_id: str,
                    model_override: str | None = None,
                    env_overrides: Dict[str, str] | None = None,
                    resume_session_id: str | None = None,
                    max_turns: int | None = None,
                    spec_name: str | None = None) -> tuple:
        from core.config import ConfigLoader
        """
        Execute claude CLI with the given prompt, streaming events to disk.

        与旧版 `--output-format json` + subprocess.run 的差异（见 D1 / agent-run-artifacts）：
        - 改用 `subprocess.Popen` + `--output-format stream-json`，将运行期间逐行
          JSON 事件（system/assistant/user/tool_use/tool_result/result）原样追加写入
          `.fenix/runs/<run_id>.jsonl`，供 Web Dashboard 实时轮询。
        - stdout/stderr 各由一条守护线程逐行读取；非 JSON 行（stderr 噪声）以
          `{"type":"stderr","line":...}` 兜底写入，保证产物文件始终可逐行解析。
        - 结束时从流中最后一个 `result` 事件还原 `output`（result 文本）与 `turns`
          （num_turns），与旧版解析结果等价。
        - 超时/kill/非零退出时向产物文件追加 `{"type":"error",...}` 终态行，并仍按
          现状语义抛出 RuntimeError。

        fix-fenix-token-waste：
        - `thinking_tokens` 遥测事件不再落盘（占旧转录 ~75% 的纯噪音）
        - `max_turns` 由本方法强制：统计流中 assistant 事件数，达到上限即 kill，
          按失败路径触发重试（claude CLI 无 --max-turns flag，故在 daemon 侧强制）
        - `resume_session_id` 传入时追加 `--resume`，从失败处续跑而非全量重跑

        Args:
            prompt: The instruction prompt for the agent.
            cwd: Worktree directory the agent operates in.
            run_id: 本次运行唯一 id（如 `impl-<spec>-<ts>-a<attempt>`），决定产物文件名。
            model_override: Pass `--model <value>` explicitly. 这是**实际发给网关的模型名**
                （claude CLI 的 --model 覆盖 ANTHROPIC_MODEL，见 fenixd-sdk-model-routing）。
                已分配 provider 的 agent 传该 agent 的 `model`（网关模型名，如
                deepseek-v4-flash）；未分配（含 Administrator）传 DEFAULT_GATEWAY_MODEL
                （默认网关 cc-switch 的官方模型名）。
            env_overrides: 额外注入到子进程的环境变量（每线程独立 env 副本，不串扰）。
                用于按 agent_type 注入不同 Provider 的 baseurl/apikey/model。
            resume_session_id: 非 None 时以 `--resume <id>` 续跑该 session。
            max_turns: 单次运行轮次上限；达到即 kill（None 表示不限制）。

        Returns: (output, turns_used, session_id)
        """
        timeout = self._get_config("agents.run_timeout_seconds", 3600)
        # fix-stuck-threshold-unify D5：supervision 激活路径读取 absolute_max 兜底值，
        # 不直接读原始配置（防止与 run 超时脱钩）。返回 None 表示未启用 supervision。
        sup_abs_max = ConfigLoader.effective_supervision_absolute_max_seconds(self.config)
        if sup_abs_max is not None and sup_abs_max < timeout:
            # 护栏兜底已保证 sup_abs_max ≥ run_timeout + 7200，正常不应进此分支；
            # 极端情况下仍以兜底值覆盖，确保 supervision 不早于 run 超时终止运行。
            self.logger.debug(
                "agent_runner",
                f"supervision absolute_max({int(sup_abs_max)}s) 低于 run_timeout({timeout}s)，"
                "以兜底值优先",
            )

        # 每线程独立 env 副本，多 agent_type 并发时环境覆盖互不串扰
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
            # Provider 覆盖生效时清除继承的 ANTHROPIC_AUTH_TOKEN（如 supervisor/tmux 环境
            # 里残留的火山 ark token）。claude-code 认证时 AUTH_TOKEN 优先于 API_KEY，
            # 残留 token 会让请求以错误的 Bearer 认证打到 Provider → 401。
            if "ANTHROPIC_API_KEY" in env_overrides:
                env.pop("ANTHROPIC_AUTH_TOKEN", None)

        # Progress dir for verifier to write incremental progress
        progress_dir = self.project_root / ".fenix" / "verify-progress"
        progress_dir.mkdir(parents=True, exist_ok=True)

        # 运行产物目录（.fenix/runs/），加入模板 gitignore，不入版本控制
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{run_id}.jsonl"

        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",  # claude CLI 要求: --print + --output-format=stream-json 必须带 --verbose
            "--add-dir", str(cwd),
            "--add-dir", str(progress_dir),
            "--permission-mode", "bypassPermissions",
        ]
        # 注入 agent 专用 settings（PreToolUse hook：阻止 Read 图片文件）。
        # 模型（deepseek-v4-flash 经本地代理）不支持图像输入，verifier/planner
        # 读截图会把图片送进对话导致 400 整轮失败。
        agent_settings = self.project_root / ".fenix" / "agent-settings.json"
        if agent_settings.exists():
            cmd += ["--settings", str(agent_settings)]
        if model_override:
            cmd += ["--model", model_override]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]

        self.logger.debug(
            "agent_runner",
            f"Running: claude -p '...' --output-format stream-json --add-dir {cwd}"
            + (" (resume)" if resume_session_id else ""),
            {"run_id": run_id, "run_file": str(run_file)},
        )

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # 行缓冲，保证实时可读
            env=env,
            cwd=str(cwd),
        )
        self._running_agents[run_id] = proc

        # 两条守护线程分别读 stdout / stderr，避免单线程 readline 卡死。
        # 共享状态由主线程在 join 之后读取，天然构成 happens-before。
        last_result: Dict[str, Any] = {}
        turn_count = [0]  # 被读线程递增；主线程轮询读取（GIL 保证可见性）
        stdout_lines: list = []
        stderr_lines: list = []

        def _read_stream(stream, is_stderr: bool) -> None:
            try:
                for line in iter(stream.readline, ""):
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue
                    if is_stderr:
                        # stderr 噪声：不保证是 JSON，一律按 stderr 兜底写入
                        stderr_lines.append(line)
                        append_run_line(run_file, {"type": "stderr", "line": line})
                        continue
                    stdout_lines.append(line)
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        entry = {"type": "stderr", "line": line}
                    if isinstance(entry, dict):
                        # fix-fenix-token-waste：thinking_tokens 遥测噪音不落盘
                        if (entry.get("type") == "system"
                                and entry.get("subtype") == "thinking_tokens"):
                            continue
                        if entry.get("type") == "assistant":
                            turn_count[0] += 1
                        if entry.get("type") == "result":
                            # 记录最后一个 result 事件（含 num_turns / result 文本 / session_id）；
                            # 落盘推迟到读线程 join 后，保证 result 终态是文件最后一行
                            # （并发 stderr 噪声不会落在其后，Dashboard 状态分类不受干扰）
                            last_result.clear()
                            last_result.update(entry)
                            continue
                    append_run_line(run_file, entry)
            except Exception:
                # 读取线程异常不应导致主流程崩溃；半成品产物仍可被 Dashboard 读取
                pass

        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, False), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, True), daemon=True)
        t_out.start()
        t_err.start()

        # 轮询等待：同时支持超时与 max_turns 强制（claude CLI 无 --max-turns flag）
        returncode = None
        timeout_error = None
        turn_limit_error = None
        started_at = time.time()
        deadline = started_at + timeout
        extensions_used = 0  # 本 run 已续期次数（D3 封闭矩阵）
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    # 超时活性监督（improve-run-lifecycle-governance D3）：到点不
                    # 立即杀——按封闭决策矩阵判定（硬上限 → 次数上限 → 活性）。
                    action = self._supervision_deadline_action(
                        run_file, spec_name, run_id, started_at, extensions_used)
                    if action["action"] == "extend":
                        extensions_used = int(action["extension_index"])
                        deadline += float(action["extension_seconds"])
                        append_run_line(run_file, {
                            "type": "timeout_extension",
                            "extension": extensions_used,
                            "extension_seconds": action["extension_seconds"],
                            "evidence": str(action.get("evidence") or "")[:400],
                            "new_deadline": deadline,
                        })
                        if spec_name:
                            self.note_run_extension(
                                spec_name, run_id, extensions_used, deadline)
                        continue
                    timeout_error = (
                        f"Timeout after {int(time.time() - started_at)}s — "
                        f"{action['reason']}"
                    )
                    if action.get("evidence"):
                        timeout_error += f" | evidence: {action['evidence']}"
                    proc.kill()
                    break
                if max_turns and turn_count[0] >= max_turns:
                    proc.kill()
                    turn_limit_error = f"Max turns ({max_turns}) reached"
                    break
                rc = proc.poll()
                if rc is not None:
                    returncode = rc
                    break
                time.sleep(1)
            if timeout_error or turn_limit_error:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                returncode = -9
        finally:
            # 等待读线程把残留行刷完，再决定终态，保证 error 终态行是文件最后一行
            t_out.join(timeout=5)
            t_err.join(timeout=5)
            self._running_agents.pop(run_id, None)
            # result 终态事件最后落盘（读线程里跳过内联写），保证是文件最后一行
            if last_result:
                append_run_line(run_file, dict(last_result))
            # 产物文件可能因崩溃等遗留为"活动但不再增长"，清理时按时间淘汰即可

        if timeout_error is not None:
            append_run_error(run_file, timeout_error, returncode)
            raise RuntimeError(f"claude CLI {timeout_error}")

        if turn_limit_error is not None:
            append_run_error(run_file, turn_limit_error, returncode)
            raise RuntimeError(f"claude CLI {turn_limit_error}")

        output = last_result.get("result", "") if last_result else ""
        turns = last_result.get("num_turns", 0)
        session_id = last_result.get("session_id") if last_result else None

        if returncode != 0:
            error_msg = "\n".join(stderr_lines[-5:])[:500] if stderr_lines else f"Exit code: {returncode}"
            append_run_error(run_file, error_msg, returncode)
            raise RuntimeError(f"claude CLI failed: {error_msg}")

        # D5: 终态语义校验前置 —— rc==0 但 last_result 标记为 error 时仍判失败
        # （Claude CLI 可能把 API 错误包装成 result/success 终止事件且 exit 0）
        if last_result:
            result_is_error = last_result.get("is_error", False)
            result_subtype = last_result.get("subtype", "success")
            if result_is_error or result_subtype in ("error", "error_during_execution"):
                err_text = last_result.get("result", "") or f"is_error={result_is_error}, subtype={result_subtype}"
                append_run_error(run_file, f"API error disguised as success: {err_text}", returncode)
                raise RuntimeError(f"claude CLI rc==0 but result indicates error: {err_text}")

        # add-cost-observability（D1）：从 stream-json 终态 result 事件提取 usage 与
        # 成本字段；失败/异常路径上 _run_claude 已抛错，此处仅成功终态能拿到 usage。
        return output, turns, session_id, self._extract_usage_info(last_result)




    # ── attempt 存活探测（improve-run-lifecycle-governance D4）────────────────




    # ── 超时续期基准（improve-run-lifecycle-governance 3.2 / D3）──────────────



    # ── 超时活性监督（improve-run-lifecycle-governance 4.1–4.3 / D1–D3）────────


    @staticmethod
    def _parse_event_timestamp(entry: dict) -> float | None:
        """解析 run 事件的 timestamp（ISO 字符串或 epoch 数值）；缺失返回 None。"""
        raw = entry.get("timestamp")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return None







    def _check_daily_limit(self):
        """Check and reset daily run counter."""
        today = datetime.now(timezone.utc).date()
        if today != self._daily_reset_date:
            self._daily_run_count = 0
            self._daily_reset_date = today

        limit = self._get_config("agents.daily_run_limit", 50)
        if limit > 0 and self._daily_run_count >= limit:
            raise RuntimeError(f"Daily agent run limit ({limit}) reached")

    def _get_agent_model_assignment(self, agent_type: str):
        """Return (provider_dict, model_name) for agent_type, or None if unassigned.

        Wraps ConfigLoader.get_agent_model_assignment. 每次调用都从 config 重新解析，
        避免缓存状态不一致；同时保证每线程拿到独立的 env 覆盖字典。
        """
        from core.config import ConfigLoader
        return ConfigLoader.get_agent_model_assignment(self.config, agent_type)

    def _get_config(self, key: str, default=None):
        """Get a nested config value."""
        from core.config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

    def _read_verify_progress(self, spec_name: str) -> dict | None:
        """读取 verifier 断点进度文件（verifier-checkpoint-resume spec）。

        返回解析后的 dict（含 total/done/current），用于构造续跑提示词；以下情况
        返回 None（视作无断点、全新开始）：
        - 文件不存在
        - 内容不是合法 JSON
        - 缺少 done / total 字段，或 done 非整数
        文件损坏时移除该文件，避免污染后续 attempt（设计 D1 / 安全降级）。
        """
        progress_path = self.project_root / ".fenix" / "verify-progress" / f"{spec_name}.json"
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 损坏文件：移除以免后续 attempt 读到半截内容
            try:
                if progress_path.exists():
                    progress_path.unlink()
            except OSError:
                pass
            return None
        if not isinstance(data, dict):
            try:
                if progress_path.exists():
                    progress_path.unlink()
            except OSError:
                pass
            return None
        done = data.get("done")
        total = data.get("total")
        if not isinstance(total, int) or not isinstance(done, int):
            return None
        return data
    @property
    def _prompt_builder(self) -> PromptBuilder:
        """组合组件（refactor-core-packages 阶段 1）：提示词构建器。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_prompt_builder_instance")
        if inst is None:
            inst = PromptBuilder(self)
            self.__dict__["_prompt_builder_instance"] = inst
        return inst


    # ── 组合组件委托（refactor-core-packages 阶段 1：PromptBuilder）──────
    # 测试引用方法（runner._build_prompt 等）保持调用路径可用（design D3 规则 4）。

    def _build_prompt(self, spec_name: str, agent_type: str, detail: dict | None = None) -> str:
        return self._prompt_builder._build_prompt(spec_name, agent_type, detail)

    def _build_legacy_section(self, spec_name: str) -> str:
        return self._prompt_builder._build_legacy_section(spec_name)

    def _legacy_dirty_snapshot(self, wt_path: str) -> str:
        return self._prompt_builder._legacy_dirty_snapshot(wt_path)

    def _scenario_freeze_section(self, spec_name: str) -> str:
        return self._prompt_builder._scenario_freeze_section(spec_name)

    def _interaction_contract_section(self, spec_name: str) -> str:
        return self._prompt_builder._interaction_contract_section(spec_name)

    def _triage_recheck_section(self, spec_name: str) -> str:
        return self._prompt_builder._triage_recheck_section(spec_name)

    def _verdict_rejection_section(self, spec_name: str) -> str:
        return self._prompt_builder._verdict_rejection_section(spec_name)

    # ── 组合组件（refactor-core-packages 阶段 2）────────────────────────

    @property
    def _provider_circuit(self) -> ProviderCircuit:
        """组合组件（refactor-core-packages 阶段 2）：ProviderCircuit。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_provider_circuit_instance")
        if inst is None:
            inst = ProviderCircuit(self)
            self.__dict__["_provider_circuit_instance"] = inst
        return inst

    @property
    def _token_accountant(self) -> TokenAccountant:
        """组合组件（refactor-core-packages 阶段 2）：TokenAccountant。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_token_accountant_instance")
        if inst is None:
            inst = TokenAccountant(self)
            self.__dict__["_token_accountant_instance"] = inst
        return inst

    @property
    def _v2_server(self) -> V2ServerManager:
        """组合组件（refactor-core-packages 阶段 2）：V2ServerManager。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_v2_server_instance")
        if inst is None:
            inst = V2ServerManager(self)
            self.__dict__["_v2_server_instance"] = inst
        return inst


    # ── 组合组件委托（阶段 2：状态/方法已迁组件，门面保持调用路径）──────

    @staticmethod
    def parse_api_error_status(error_text: str) -> Optional[int]:
        return ProviderCircuit.parse_api_error_status(error_text)

    @staticmethod
    def classify_switch_error(error_text: str) -> bool:
        return ProviderCircuit.classify_switch_error(error_text)

    def _circuit_state(self, provider_name: str) -> dict:
        return self._provider_circuit._circuit_state(provider_name)

    def is_circuit_open(self, provider_name: str, now: float | None = None) -> bool:
        return self._provider_circuit.is_circuit_open(provider_name, now)

    def is_switch_cooldown(self, provider_name: str, now: float | None = None) -> bool:
        return self._provider_circuit.is_switch_cooldown(provider_name, now)

    def _record_switch_cooldown(self, provider_name: str, now: float | None = None) -> None:
        return self._provider_circuit._record_switch_cooldown(provider_name, now)

    def _write_provider_marker(self, run_id: str, spec_name: str, agent_type: str,
                               provider_name: str, model: str, chain_index: int,
                               chain_len: int) -> None:
        return self._provider_circuit._write_provider_marker(run_id, spec_name, agent_type, provider_name, model, chain_index, chain_len)

    def _record_daily_provider_attempt(self, provider_name: str) -> None:
        return self._provider_circuit._record_daily_provider_attempt(provider_name)

    def _circuit_open_error(self, provider_name: str, now: float | None = None) -> str:
        return self._provider_circuit._circuit_open_error(provider_name, now)

    def _record_provider_4xx(self, provider_name: str, code: int,
                             now: float | None = None) -> None:
        return self._provider_circuit._record_provider_4xx(provider_name, code, now)

    def _record_provider_probe(self, provider_name: str, success: bool,
                               now: float | None = None) -> None:
        return self._provider_circuit._record_provider_probe(provider_name, success, now)

    def _accumulate_token_usage(self, spec_name: str, usage_info: dict) -> None:
        return self._token_accountant._accumulate_token_usage(spec_name, usage_info)

    def _check_token_budget(self, spec_name: str, tokens_in: int) -> None:
        return self._token_accountant._check_token_budget(spec_name, tokens_in)

    def _send_token_alert(self, spec_name: str, tokens_in: int, budget: float,
                          severity: str, title: str) -> None:
        return self._token_accountant._send_token_alert(spec_name, tokens_in, budget, severity, title)

    def _record_verify_progress_tokens(self, spec_name: str, agent_type: str,
                                         usage_info: dict) -> None:
        return self._token_accountant._record_verify_progress_tokens(spec_name, agent_type, usage_info)

    def _v2_ensure_state(self) -> None:
        return self._v2_server._v2_ensure_state()

    def _v2_launch_for_worktree(self, wt_path: Path) -> None:
        return self._v2_server._v2_launch_for_worktree(wt_path)

    def _v2_inject_env(self, wt_path: Path) -> Dict[str, str]:
        return self._v2_server._v2_inject_env(wt_path)

    def _v2_stop_for_worktree(self, wt_path: Path) -> None:
        return self._v2_server._v2_stop_for_worktree(wt_path)

    def _v2_stop_all(self) -> None:
        return self._v2_server._v2_stop_all()

    @property
    def provider_circuits(self):
        return self._provider_circuit.provider_circuits

    @provider_circuits.setter
    def provider_circuits(self, value):
        self._provider_circuit.provider_circuits = value

    @provider_circuits.deleter
    def provider_circuits(self):
        del self._provider_circuit.provider_circuits

    @property
    def _daily_provider_attempts(self):
        return self._provider_circuit._daily_provider_attempts

    @_daily_provider_attempts.setter
    def _daily_provider_attempts(self, value):
        self._provider_circuit._daily_provider_attempts = value

    @_daily_provider_attempts.deleter
    def _daily_provider_attempts(self):
        del self._provider_circuit._daily_provider_attempts

    @property
    def _daily_provider_warned(self):
        return self._provider_circuit._daily_provider_warned

    @_daily_provider_warned.setter
    def _daily_provider_warned(self, value):
        self._provider_circuit._daily_provider_warned = value

    @_daily_provider_warned.deleter
    def _daily_provider_warned(self):
        del self._provider_circuit._daily_provider_warned

    @property
    def _daily_reset_date(self):
        return self._provider_circuit._daily_reset_date

    @_daily_reset_date.setter
    def _daily_reset_date(self, value):
        self._provider_circuit._daily_reset_date = value

    @_daily_reset_date.deleter
    def _daily_reset_date(self):
        del self._provider_circuit._daily_reset_date

    @property
    def _v2_servers(self):
        return self._v2_server._v2_servers

    @_v2_servers.setter
    def _v2_servers(self, value):
        self._v2_server._v2_servers = value

    @_v2_servers.deleter
    def _v2_servers(self):
        del self._v2_server._v2_servers

    @property
    def _v2_used_ports(self):
        return self._v2_server._v2_used_ports

    @_v2_used_ports.setter
    def _v2_used_ports(self, value):
        self._v2_server._v2_used_ports = value

    @_v2_used_ports.deleter
    def _v2_used_ports(self):
        del self._v2_server._v2_used_ports

    @property
    def _v2_run_seq(self):
        return self._v2_server._v2_run_seq

    @_v2_run_seq.setter
    def _v2_run_seq(self, value):
        self._v2_server._v2_run_seq = value

    @_v2_run_seq.deleter
    def _v2_run_seq(self):
        del self._v2_server._v2_run_seq

    # ── 组合组件（refactor-core-packages 阶段 3）────────────────────────

    @property
    def _liveness(self) -> LivenessSupervisor:
        """组合组件（refactor-core-packages 阶段 3）：LivenessSupervisor。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_liveness_instance")
        if inst is None:
            inst = LivenessSupervisor(self)
            self.__dict__["_liveness_instance"] = inst
        return inst

    @property
    def _session(self) -> SessionTracker:
        """组合组件（refactor-core-packages 阶段 3）：SessionTracker。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_session_instance")
        if inst is None:
            inst = SessionTracker(self)
            self.__dict__["_session_instance"] = inst
        return inst


    # ── 组合组件委托（阶段 3：存活/监督/session 已迁组件）────────────────

    def has_live_attempt(self, spec_name: str) -> bool:
        return self._liveness.has_live_attempt(spec_name)

    def _pgrep_live_attempt(self, spec_name: str) -> bool:
        return self._liveness._pgrep_live_attempt(spec_name)

    def _stream_recent(self, spec_name: str, seconds: int) -> bool:
        return self._liveness._stream_recent(spec_name, seconds)

    def note_run_extension(self, spec_name: str, run_id: str,
                           extension_index: int, new_deadline: float) -> None:
        return self._liveness.note_run_extension(spec_name, run_id, extension_index, new_deadline)

    def get_extension_baseline(self, spec_name: str) -> float | None:
        return self._liveness.get_extension_baseline(spec_name)

    def _liveness_snapshot(self, run_file: Path, window_seconds: float,
                           now: float | None = None) -> dict:
        return self._liveness._liveness_snapshot(run_file, window_seconds, now)

    @staticmethod
    def _summarize_snapshot(snapshot: dict) -> str:
        return LivenessSupervisor._summarize_snapshot(snapshot)

    def _judge_liveness(self, snapshot: dict, spec_name: str | None,
                        run_id: str) -> dict:
        return self._liveness._judge_liveness(snapshot, spec_name, run_id)

    @staticmethod
    def _parse_verdict_json(text: str) -> dict | None:
        return LivenessSupervisor._parse_verdict_json(text)

    def _supervision_settings(self) -> dict:
        return self._liveness._supervision_settings()

    def _supervision_deadline_action(self, run_file: Path, spec_name: str | None,
                                     run_id: str, started_at: float,
                                     extensions_used: int,
                                     judge=None) -> dict:
        return self._liveness._supervision_deadline_action(run_file, spec_name, run_id, started_at, extensions_used, judge)

    def wait_for_running_agents(self, timeout: int = AGENT_TERMINATE_GRACE_SECONDS):
        return self._liveness.wait_for_running_agents(timeout)

    @staticmethod
    def _resumable_session_id(
        session_id: str | None,
        session_provider: str | None,
        current_provider: str | None,
        reuse_worktree: bool,
    ) -> str | None:
        return SessionTracker._resumable_session_id(session_id, session_provider, current_provider, reuse_worktree)

    @staticmethod
    def _extract_session_id(run_file: Path) -> str | None:
        return SessionTracker._extract_session_id(run_file)

    @staticmethod
    def _extract_usage_info(result_event: dict | None) -> dict:
        return SessionTracker._extract_usage_info(result_event)

    @property
    def _extension_baselines(self):
        return self._liveness._extension_baselines

    @_extension_baselines.setter
    def _extension_baselines(self, value):
        self._liveness._extension_baselines = value

    @_extension_baselines.deleter
    def _extension_baselines(self):
        del self._liveness._extension_baselines

