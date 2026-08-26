"""
agent_runner.py — Agent execution engine for fenixd.

Spawns claude CLI subprocesses to run implementer and verifier Agents.
Handles result parsing, retry logic, and token/turn budget control.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

# .fenix/runs/ 保留的最近运行产物数量上限（默认 20，见 D1 / spec agent-run-artifacts）
RUNS_KEEP = 20


class AgentRunResult:
    """Result of a single Agent run."""

    def __init__(self, run_id: str, spec_name: str, agent_type: str,
                 success: bool, duration_seconds: float,
                 turns_used: int = 0, error: str = None, output: str = "",
                 branch: str | None = None):
        self.run_id = run_id
        self.spec_name = spec_name
        self.agent_type = agent_type
        self.success = success
        self.duration_seconds = duration_seconds
        self.turns_used = turns_used
        self.error = error
        self.output = output
        self.branch = branch  # worktree 分支名（成功时由 _execute_agent 填入）

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
            "output_summary": self.output[-500:] if self.output else "",
        }


class AdminDisposition:
    """Administrator Agent 一次处置的结果（run_administrator 返回）。"""

    def __init__(self, run_id: str, spec: str | None = None, success: bool = True,
                 problem: str = "", actions_taken: str = "", result: str = "",
                 escalate: bool = False, recommended_action: str = "",
                 summary: str = "", error: str = "", output: str = ""):
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


def append_run_line(run_file: Path, entry: dict) -> None:
    """向运行产物文件追加一行 JSON 并立即 flush，保证运行期间 Dashboard 可读。

    每行独立 open("a") + flush，两个读线程并发写入时依赖 O_APPEND 的原子性，
    避免长行被交错切碎。
    """
    with run_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()


def append_run_error(run_file: Path, error: str, exit_code: int) -> None:
    """异常/超时/kill 终止时向产物文件追加 error 终态行。"""
    append_run_line(run_file, {"type": "error", "error": error, "exit_code": exit_code})


def clean_old_runs(runs_dir: Path, keep: int = RUNS_KEEP, active_ids=None) -> int:
    """清理 .fenix/runs/ 中超出保留上限的最旧产物，跳过正在增长的活动产物。

    Args:
        runs_dir: .fenix/runs/ 目录。
        keep: 保留的最近产物数量。
        active_ids: 仍处于运行中的 run_id 集合，其产物一律跳过不删。

    Returns: 删除的文件数。
    """
    if not runs_dir.is_dir():
        return 0
    active_ids = set(active_ids or ())
    try:
        candidates = [
            p for p in runs_dir.glob("*.jsonl")
            if p.stem not in active_ids
        ]
    except OSError:
        return 0
    # 按最近修改时间排序，旧的在前
    candidates.sort(key=lambda p: p.stat().st_mtime)
    removed = 0
    while len(candidates) > keep:
        victim = candidates.pop(0)
        try:
            victim.unlink()
            removed += 1
        except OSError:
            continue
    return removed


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

        self._running_agents: Dict[str, subprocess.Popen] = {}
        self._daily_run_count = 0
        self._daily_reset_date = datetime.now(timezone.utc).date()

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

    def run_administrator(self, signal: dict) -> AdminDisposition:
        """唤起 Administrator Agent 处置困境信号（administrator-agent spec）。

        与 implementer/verifier 不同：Administrator 是运维角色，直接在 main 树
        （project_root）操作框架，不创建 worktree（design D4）。产物写入
        .fenix/runs/admin-<spec>-<ts>.jsonl；处置结果从管理员按 prompt 写入的
        .fenix/admin_disposition.json 读取，由 daemon 落盘到 admin_alerts.json。

        Args:
            signal: admin_monitor 检测到的困境信号 dict
                （signal_type/spec/severity/description/evidence/recommended_action）。
        """
        spec = signal.get("spec") or "global"
        run_id = f"admin-{spec}-{int(time.time())}"
        prompt = self._build_prompt(spec, "administrator", detail=signal)
        model_override = self._get_admin_model()

        # fix-admin-self-heal：唤起前先落 pending disposition，保证即使 admin 被
        # kill（如 daemon 重启/崩溃）也有记录可回溯；monitor 会检测无最终结果的
        # pending 并升级人工，避免「admin 死了但没有任何告警」。
        try:
            from .admin_store import AdminStore, DISPOSITION
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

        self._clear_admin_disposition()
        try:
            output, turns, _session_id = self._run_claude(
                prompt, self.project_root, run_id, model_override,
                max_turns=self._get_config("agents.max_turns", 50),
            )
            success = True
            error = ""
        except Exception as e:
            output = ""
            success = False
            error = str(e)

        disp = self._read_admin_disposition()
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
        )

    def _clear_admin_disposition(self):
        """清空上次的处置记录，避免运行失败时读到陈旧数据。"""
        disp_path = self.project_root / ".fenix" / "admin_disposition.json"
        try:
            if disp_path.exists():
                disp_path.unlink()
        except OSError:
            pass

    def _read_admin_disposition(self) -> dict:
        """读取管理员按 prompt 写入的处置记录 .fenix/admin_disposition.json。

        文件缺失/损坏返回空 dict（调用方用信号详情兜底）。
        """
        disp_path = self.project_root / ".fenix" / "admin_disposition.json"
        try:
            data = json.loads(disp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        at = data.get("actions_taken")
        if isinstance(at, list):
            data["actions_taken"] = "；".join(str(x) for x in at if x)
        elif at is None:
            data["actions_taken"] = ""
        elif not isinstance(at, str):
            data["actions_taken"] = str(at)
        sm = data.get("summary")
        if isinstance(sm, list):
            data["summary"] = "；".join(str(x) for x in sm if x)
        elif sm is None:
            data["summary"] = ""
        elif not isinstance(sm, str):
            data["summary"] = str(sm)
        return data

    def _get_admin_model(self) -> str:
        """Administrator 模型名：admin.agent_model > agents.subagent_model > 默认。"""
        admin_model = self._get_config("admin.agent_model", None)
        if admin_model:
            return admin_model
        return self._get_config("agents.subagent_model", "claude-sonnet-5")

    def _execute_agent(self, spec_name: str, agent_type: str, run_id: str) -> AgentRunResult:
        """Core agent execution logic with retry support.

        fix-fenix-token-waste：
        - 每次 attempt 使用独立 run_id（-a<attempt>），产物文件与尝试一一对应
        - implementer 失败重试复用同一 worktree + `claude --resume` 续跑，不从零
          全量重跑；其余 agent_type 维持每次全新 worktree
        - max_turns 在 _run_claude 内强制
        """
        max_retries = self._get_config("agents.max_retries", 3)
        start_time = time.time()
        wt_path = None
        session_id = None

        for attempt in range(1, max_retries + 1):
            attempt_run_id = f"{run_id}-a{attempt}"
            self.logger.info(
                "agent_runner",
                f"Running {agent_type} for '{spec_name}' (attempt {attempt}/{max_retries})",
                {"run_id": attempt_run_id},
            )

            # Check daily run limit
            self._check_daily_limit()

            reuse_worktree = (agent_type == "implementer" and wt_path is not None)

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
                        error=error_msg,
                    )
            else:
                self.logger.info(
                    "agent_runner",
                    f"Reusing worktree {wt_path} for '{spec_name}' (attempt {attempt}, resume)",
                )

            # Build and execute the prompt
            try:
                prompt = self._build_prompt(spec_name, agent_type)
                # 解析该 agent_type 的模型分配：
                # - 已分配：注入 ANTHROPIC_BASE_URL/API_KEY/MODEL 环境变量，
                #   --model 取 provider.sdk_model 或 agents.subagent_model（官方名过 SDK 校验）
                # - 未分配：完全维持现状（不注入覆盖，--model 用 agents.subagent_model）
                assignment = self._get_agent_model_assignment(agent_type)
                env_overrides: Dict[str, str] = {}
                if assignment is not None:
                    provider, model = assignment
                    env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
                    env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
                    env_overrides["ANTHROPIC_MODEL"] = model
                    # 注入 provider 自定义环境变量（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）
                    for k, v in (provider.get("env") or {}).items():
                        env_overrides[k] = v
                    model_override = provider.get("sdk_model") or self._get_config(
                        "agents.subagent_model", "claude-sonnet-5"
                    )
                else:
                    # 统一显式指定官方 Claude model 名。环境通过 ANTHROPIC_MODEL=deepseek-v4-flash
                    # 走火山代理，但 claude-code SDK 只识别官方 model 名；任何 agent 一旦在内部
                    # 通过 Agent SDK 派生子代理（verifier/planner-judge 必触发，fix implementer
                    # 也会触发），未识别的 model 名即报 unrecognized_model 致命错误。用官方 model
                    # 名覆盖可彻底规避（实际请求仍走 ANTHROPIC_BASE_URL 代理）。
                    # 未配置 agents.subagent_model 时默认 claude-sonnet-5（官方 model 名，仅用于
                    # 通过 SDK 校验），保证子代理派发始终可用。
                    model_override = self._get_config("agents.subagent_model", "claude-sonnet-5")
                output, turns, run_session_id = self._run_claude(
                    prompt, wt_path, attempt_run_id, model_override, env_overrides,
                    resume_session_id=session_id if reuse_worktree else None,
                    max_turns=self._get_config("agents.max_turns", 50),
                )
                if run_session_id:
                    session_id = run_session_id
                success = True
                error = None
            except Exception as e:
                output = ""
                turns = 0
                success = False
                error = str(e)
                # implementer 失败后从产物尾部提取 session_id，供下一次 attempt --resume 续跑
                if agent_type == "implementer":
                    run_file = self.project_root / ".fenix" / "runs" / f"{attempt_run_id}.jsonl"
                    sid = self._extract_session_id(run_file)
                    if sid:
                        session_id = sid

            # 记录分支名（在 cleanup 之前，cleanup 会从 _wt_branches 中移除）
            branch = self.worktree_manager.get_branch_name(wt_path) if success else None

            # 成功时，把 worktree 中的 .fenix-run-result.json 复制到主树。
            # 原因：implementer 的 cwd 现在是 worktree，结果文件写在 worktree 内；
            # cleanup 后 worktree 被删除，pm_engine._read_implementer_result 回退读主树。
            # 复制一份到主树，既保证 pm_engine 读得到，也让 merge 后结果保留在主树历史中。
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
                # 成功：清理 worktree（保留分支供 merge-back），返回结果
                self.worktree_manager.cleanup(wt_path, success=True)
                duration = time.time() - start_time
                self._daily_run_count += 1
                self.logger.info(
                    "agent_runner",
                    f"{agent_type} succeeded for '{spec_name}'",
                    {"run_id": attempt_run_id, "attempt": attempt, "turns": turns},
                )
                return AgentRunResult(
                    attempt_run_id, spec_name, agent_type,
                    success=True, duration_seconds=duration,
                    turns_used=turns, output=output,
                    branch=branch,
                )
            else:
                self.logger.warning(
                    "agent_runner",
                    f"{agent_type} failed for '{spec_name}' (attempt {attempt})",
                    {"run_id": attempt_run_id, "error": error},
                )
                # 失败后的 worktree 处理：
                # - implementer 且还有重试：保留 worktree，下次 attempt 用 --resume 续跑
                # - 其他：清理 worktree 并删除分支，下次 attempt 全新创建
                if attempt < max_retries:
                    time.sleep(10)  # Wait before retry
                    if agent_type != "implementer":
                        self.worktree_manager.cleanup(wt_path, success=False)
                        wt_path = None
                else:
                    self.worktree_manager.cleanup(wt_path, success=False)
                    wt_path = None

        # All retries exhausted
        duration = time.time() - start_time
        return AgentRunResult(
            run_id, spec_name, agent_type,
            success=False, duration_seconds=duration,
            error=f"All {max_retries} attempts failed. Last error: {error}",
        )

    def _build_prompt(self, spec_name: str, agent_type: str, detail: dict | None = None) -> str:
        """Build the claude CLI prompt for the Agent.

        detail: 可选。administrator 分支接收困境信号 dict。
        """
        spec_dir = f"openspec/changes/{spec_name}"

        if agent_type == "implementer":
            return (
                f"You are the Fenix Implementer Agent. Your job is to implement the SPEC "
                f"located at {spec_dir}/.\n\n"
                f"1. Read {spec_dir}/proposal.md, {spec_dir}/design.md, and {spec_dir}/specs/\\*.md "
                f"to understand what needs to be built.\n"
                f"2. Read {spec_dir}/tasks.md and identify the next unchecked task.\n"
                f"3. Implement that task. Write actual production code, not stubs.\n"
                f"4. Run the project's tests after implementation. Fix any failures.\n"
                f"5. Commit your changes with message: [fenix] {spec_name}: <task description>\n"
                f"6. Mark the task as complete in tasks.md (- [x])\n"
                f"7. If all tasks are done, write a file .fenix-run-result.json with: "
                f'{{"status": "success", "spec": "{spec_name}", "summary": "<brief summary>"}}\n'
                f"8. If you encounter an error you cannot fix after 3 attempts, write "
                f".fenix-run-result.json with: "
                f'{{"status": "error", "spec": "{spec_name}", "error": "<description>"}}\n\n'
                f"IMPORTANT: Do NOT modify STATE.md directly. The daemon handles that."
            )
        elif agent_type == "verifier":
            progress_path = self.project_root / ".fenix" / "verify-progress" / f"{spec_name}.json"
            return (
                f"You are the Fenix Verifier Agent. Independently verify the SPEC at {spec_dir}/.\n\n"
                f"CRITICAL: You MUST test in a REAL browser/user environment.\n"
                f"Code analysis alone = INCOMPLETE = FAILURE. Use playwright-cli for web projects.\n\n"
                f"WORKFLOW — write progress to {progress_path} at EVERY step:\n"
                f"  Step 0: Write done=0, current='初始化: 读取SPEC'\n"
                f"  Step 1: Read specs, count scenarios. Write total=N.\n"
                f"  Step 2: Build and START the project in its real runtime.\n"
                f"    Web: npm run dev, open in browser via playwright-cli.\n"
                f"    Extension: npm run build, load in Chrome (if possible) or npm run dev.\n"
                f"  Step 3: MANDATORY click-through UI regression test — test EVERY panel:\n"
                f"    - Quick Links: CLICK '+', fill form, SUBMIT → verify new link appears in grid\n"
                f"    - Notes: CLICK '+', type note, SAVE → verify note appears in list\n"
                f"    - Stock: TYPE 'sh600036', CLICK 'add' → verify stock appears in list\n"
                f"    - Calculator: TYPE '2+3', ENTER → verify '5' result is visible and readable\n"
                f"    - Email: CLICK settings, add account → verify form works\n"
                f"    After EACH interaction, TAKE SCREENSHOT as evidence.\n"
                f"    If any button click produces NO visible result = BLOCKING BUG.\n"
                f"  Step 4: Test scenarios ONE BY ONE as a REAL USER.\n"
                f"    USE PLAYWRIGHT-CLI: navigate, click, type, scroll, take screenshots.\n"
                f"    After EACH scenario, increment done and write progress.\n"
                f"    Format: {{\"total\": N, \"done\": D, \"current\": \"scenario description\"}}\n"
                f"  Step 4: Test edge cases (empty input, long input, resize, rapid clicks).\n"
                f"  Step 5: Write {spec_dir}/verification-report.md with screenshots.\n"
                f"  Step 6: All pass → write .fenix-run-result.json: "
                f'{{"status":"verified","spec":"{spec_name}","bugs":[]}}\n'
                f"  Step 7: Bugs found → write .fenix-run-result.json: "
                f'{{"status":"bug-found","spec":"{spec_name}","bugs":[...]}}\n\n'
                f"MANDATORY: Write progress after EVERY step and EVERY scenario.\n"
                f"MANDATORY: Use playwright-cli for browser testing. NO shortcuts.\n"
                f"MANDATORY: If you cannot start the REAL project, report it as a failure.\n"
                f"IMPORTANT: Do NOT Read image/screenshot files (.png/.jpg) — 当前模型不支持图像输入，"
                f"读图会被 hook 拦截；截图仅作为证据文件保存到报告，验证用 DOM snapshot 文本。\n"
                f"IMPORTANT: Do NOT modify STATE.md."
            )

        elif agent_type == "planner-plan":
            scenarios_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            result_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            return (
                f"你是 Fenix Planner Agent。你的任务是将 SPEC 文档转化为结构化的浏览器测试场景。\n\n"
                f"## 步骤\n"
                f"1. 读取 {spec_dir}/proposal.md, {spec_dir}/design.md, {spec_dir}/specs/*.md\n"
                f"2. 分析所有功能点，为每个功能生成至少一个测试场景\n"
                f"3. 将生成的场景保存到 {scenarios_path}\n"
                f"4. 将运行结果写入 {result_path}（绝对路径，与场景文件同目录，"
                f"不要写别处）："
                f'{{"status":"plan-ready","spec":"{spec_name}"}}\n\n'
                f"## 场景覆盖规则\n"
                f"- 功能正向路径：每个SPEC功能点的完整操作流程\n"
                f"- 异常路径：空输入、超长输入、特殊字符\n"
                f"- 交互流程：多步骤操作序列，验证中间状态\n"
                f"- 回归点：操作后状态与操作前对比\n"
                f"- 空状态：列表/面板在无数据时的显示\n"
                f"- 删除/撤销：删除操作后的状态验证\n\n"
                f"## 真实云端端到端场景（同步/云端/数据隔离相关 SPEC 必须）\n"
                f"- 对「同步 / 云端存储 / 上传下载 / 数据加密 / 数据隔离」相关 SPEC，"
                f"必须生成至少一个「真实创建用户 → 解锁 → 点击下载」的端到端场景，"
                f"触发真实云端请求（腾讯云 COS）。\n"
                f"- 这类场景用 no_auth_error 断言「无签名/认证错误」，用于捕获"
                f"数据加解密/签名正确性 bug（纯 UI 断言无法覆盖）。\n"
                f"- 约束：只做「下载」（读取云端，安全），不做「上传」（避免污染真实云端数据）。\n"
                f"- 示例步骤：seed 清空用户与同步键 → 创建用户（密码 test-password-123）→ "
                f"解锁 → 点击「下载云端数据」→ 断言 no_auth_error。\n\n"
                f"## 选择器规范\n"
                f"- 优先使用 data-testid 属性\n"
                f"- 其次使用语义选择器：button[name=\"提交\"], input[placeholder=\"搜索\"]\n"
                f"- 避免使用：CSS类名、第n个子元素、绝对路径\n\n"
                f"## 断言规范（每个场景至少包含）\n"
                f"- 1个 element_visible（操作结果可见）\n"
                f"- 如涉及点击：1个 no_click_interception（点击不被拦截）\n"
                f"- 如涉及输入：1个 text_match（输入内容正确）\n"
                f"- 如涉及表单：1个 element_enabled（提交按钮状态正确）\n\n"
                f"## 对话框处理（window.confirm/alert/prompt）\n"
                f"- 点击若触发 window.confirm 等浏览器对话框，必须显式处理，否则被默认 dismiss 会误判：\n"
                f"  - 确认场景：在触发对话框的 click 步骤加 \"dialog\": \"accept\"，"
                f"或在 click 前加一步 {{\"action\": \"dialog\", \"value\": \"accept\"}}\n"
                f"  - 取消场景：同理用 \"dismiss\"\n"
                f"- 示例：{{\"action\": \"click\", \"target\": \".user-chip\", "
                f"\"dialog\": \"accept\", \"description\": \"点击切换并确认\"}}\n\n"
                f"## no_click_interception 时机规范\n"
                f"- 只在「即将点击某元素」前断言该元素不被遮挡；一旦打开 modal/overlay，"
                f"其覆盖的底层按钮被遮挡是正常交互，不得再对其断言 no_click_interception。\n\n"
                f"## 弹窗/对话框关闭后的断言规范（时序）\n"
                f"- 若某操作（如点击「保存」「取消」）会关闭弹窗/对话框，则关闭之后"
                f"弹窗内元素已从 DOM 移除，**不得再断言弹窗内元素**（如输入框的值）。\n"
                f"- 应改为断言弹窗外持久 DOM 的交互结果（如面板主体区的文本/元素），"
                f"或在触发关闭的操作**之前**断言弹窗内输入框的值。\n"
                f"- 示例：输入地点 → 点「保存」（弹窗关闭）→ 断言面板天气区文本，"
                f"而非断言弹窗内输入框。\n\n"
                f"## seed 数据规范\n"
                f"- seed 写入的 localStorage 值必须是目标键的合法格式：base64 键"
                f"（如 fenix:sync:persisted-key）必须使用合法 base64，不得使用 "
                f"\"some-base64-key\" 这类占位符。\n\n"
                f"## 输出JSON格式\n"
                f'[\n'
                f'  {{\n'
                f'    "id": "kebab-case-unique-id",\n'
                f'    "description": "中文场景描述",\n'
                f'    "depends_on": ["前置场景ID"],\n'
                f'    "steps": [\n'
                f'      {{"action": "navigate", "value": "https://..."}},\n'
                f'      {{"action": "click", "target": "[data-testid=\'add-btn\']", "description": "点击添加按钮"}},\n'
                f'      {{"action": "type", "target": "[data-testid=\'title-input\']", "value": "测试标题"}},\n'
                f'      {{"action": "click", "target": "[data-testid=\'submit-btn\']", "description": "提交表单"}}\n'
                f'    ],\n'
                f'    "assertions": [\n'
                f'      {{"type": "element_visible", "selector": ".result-item", "label": "新增项可见"}},\n'
                f'      {{"type": "text_match", "selector": ".result-item .title", "expected": "测试标题"}},\n'
                f'      {{"type": "no_click_interception", "selector": "[data-testid=\'add-btn\']"}},\n'
                f'      {{"type": "no_console_error"}}\n'
                f'    ],\n'
                f'    "visual_baseline": "scenario_id_baseline"\n'
                f'  }}\n'
                f']\n\n'
                f"支持的断言类型: element_visible, element_count, element_not_exist, "
                f"element_focused, element_enabled, no_click_interception, no_overlap, "
                f"in_viewport, z_index_order, text_match, text_contains, attribute_match, "
                f"no_console_error, no_network_error, no_auth_error, dom_structure, no_overflow, alignment\n\n"
                f"支持的操作类型: navigate, click, type, clear, select, scroll, wait, dialog, seed, mock_api\n"
                f"（click 步骤可携带 \"dialog\": \"accept\" | \"dismiss\" 处理浏览器对话框）\n"
                f"## 外部 API 场景规范（真实网络请求 / mock）\n"
                f"- 涉及外部 API 真实请求的场景（如 open-meteo 天气、时间服务器），在场景 JSON "
                f"顶层声明 \"external_net_errors_ok\": true，表示允许 no_console_error 过滤 "
                f"net::ERR_ 等网络层错误（测试环境不可达属环境因素，非产品缺陷）；"
                f"签名/认证类错误仍严格失败。\n"
                f"- 若需离线完整验证外部 API 请求→解析→渲染链路，可在场景 steps 中加入 "
                f"mock_api 步骤：{{\"action\": \"mock_api\", \"target\": \"https://api.open-meteo.com/**\", "
                f"\"value\": \"{{\\\"current\\\": ...}}\"}}（target 为 URL 模式，value 为 JSON 响应体；"
                f"注意 Playwright glob 中 `*` 不匹配 `/`，多段路径需用 `**`，引擎会自动把结尾 "
                f"`/*` 补成 `/**`）。mock 注册在 page 上，reload/导航后仍保留；仅作用于当前场景。\n\n"
                f"IMPORTANT: 当前模型不支持图像输入——不要 Read 图片/截图文件（会被 hook 拦截），"
                f"截图仅作为证据文件。\n"
                f"IMPORTANT: Do NOT modify STATE.md."
            )

        elif agent_type == "planner-judge":
            report_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / "report.json"
            )
            result_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            return (
                f"你是 Fenix Planner Agent。你的任务是分析验证引擎的测试报告，判定验证是否通过。\n\n"
                f"## 步骤\n"
                f"1. 读取 {report_path}\n"
                f"2. 按照判定规则分析每个断言结果\n"
                f"3. 聚合同类型失败，避免重复报告\n"
                f"4. 将运行结果写入 {result_path}（绝对路径，与场景/报告文件同目录，"
                f"不要写别处）\n"
                f"5. 写入 {spec_dir}/verification-report.md（人类可读的验证报告）\n\n"
                f"## 判定规则\n\n"
                f"### 第1-2层断言失败 → 一定是Bug\n"
                f"元素不存在、不可见、点击被拦截、重叠等。直接记录，不需要额外判断。\n\n"
                f"### 第3层断言失败 → 大概率是Bug\n"
                f"文字不匹配、属性错误、DOM结构错误。除非有明显理由（如SPEC允许动态内容），否则记为Bug。\n\n"
                f"### no_auth_error 特判（真实云端端到端场景）\n"
                f"- 出现「签名验证失败」「InvalidAccessKeyId」「SignatureDoesNotMatch」等"
                f"密钥/签名错误 → 产品 Bug（密钥派生或加解密正确性问题）。\n"
                f"- 仅网络不可达（超时、连接失败、DNS 错误），且无上述密钥/签名关键词 → "
                f"环境问题，不记为产品 Bug，报告中标注「网络环境不可达，无法验证」。\n\n"
                f"### no_console_error 外部 API 网络错误特判\n"
                f"- 断言结果含 `filtered_network` 字段且 `errors` 为空 → 该断言通过："
                f"涉及外部 API 的场景已声明豁免，net::ERR_ 等网络层错误按环境因素过滤，"
                f"不记为 Bug。\n\n"
                f"### 断言时序特判（弹窗/对话框关闭后查询弹窗内元素）\n"
                f"- 断言失败原因为「元素随弹窗/对话框关闭而从 DOM 移除」（如 Locator 超时、"
                f"evaluate 找不到节点），且同场景其他功能性断言通过 → 判为断言时序问题"
                f"（测试场景设计缺陷），不记为产品 Bug；报告中标注「断言时序问题：应在"
                f"交互前校验或改断言弹窗外持久 DOM」。\n"
                f"- 典型模式：点击「保存」后弹窗立即关闭，后续仍断言弹窗内输入框的值。\n\n"
                f"### 第4层断言失败 → 需结合上下文\n"
                f"- SSIM低于阈值：检查是否为动态内容区域（时间戳/随机推荐）。是→忽略，不是→Bug。\n"
                f"- 元素溢出：检查是否在预期视口尺寸内。是→忽略，不是→Bug。\n\n"
                f"### 聚合规则\n"
                f"- 同一场景同一类型的失败 → 合并为1个Bug\n"
                f"- 同一元素在多个场景中同一类失败 → 标记为\"系统性问题\"\n"
                f"- 3个以上场景出现相同root cause → 只报1个Bug，标注影响范围\n\n"
                f"### .fenix-run-result.json 格式\n"
                f'{{\n'
                f'  "status": "verified" | "bug-found",\n'
                f'  "bugs": [\n'
                f'    {{\n'
                f'      "severity": "critical" | "major" | "minor",\n'
                f'      "scenario_ids": ["场景ID列表"],\n'
                f'      "assertion_type": "断言类型",\n'
                f'      "description": "Bug的清晰中文描述",\n'
                f'      "root_cause": "推断的根因",\n'
                f'      "evidence": {{...}}\n'
                f'    }}\n'
                f'  ],\n'
                f'  "summary": "验证总结"\n'
                f'}}\n\n'
                f"IMPORTANT: Do NOT modify STATE.md."
            )

        elif agent_type == "administrator":
            sig = detail or {}
            sig_spec = sig.get("spec") or spec_name
            sig_type = sig.get("signal_type") or "unknown"
            severity = sig.get("severity") or "major"
            description = sig.get("description") or ""
            evidence = sig.get("evidence") or ""
            recommendation = sig.get("recommended_action") or ""
            return (
                f"You are the Fenix Administrator Agent — 运维角色，"
                f"负责处置 Agent 无法自行脱困的困境。\n\n"
                f"## 困境信号\n"
                f"- 类型: {sig_type}\n"
                f"- spec: {sig_spec}\n"
                f"- 严重度: {severity}\n"
                f"- 描述: {description}\n"
                f"- 证据: {evidence}\n"
                f"- 建议处置: {recommendation}\n\n"
                f"## 你的高级权限（自主处置，无需询问）\n"
                f"- 杀死进行中的 Agent 子进程（先 ps 确认归属再操作）\n"
                f"- 需要重启 fenixd 时：写 .fenix/restart_request 文件（内容随意），"
                f"supervisor 会负责重启；【不要】直接 kill daemon——daemon 是你的宿主进程，"
                f"kill 它会连带杀死你，导致重启和处置记录都丢失\n"
                f"- git 清理：worktree prune / stash / reset / commit / 分支管理\n"
                f"- 直接修改 Fenixd 自身代码（当前已在主树）并提交\n"
                f"- 发起新的 SPEC（创建 openspec/changes/<name>/ 并更新 STATE.md）\n"
                f"- 重置/修复 spec 状态（将卡死 spec 更新为 ready/blocked 并清空陈旧字段）\n\n"
                f"## 铁律\n"
                f"1. 只处置困境，不开发功能、不实现 SPEC 需求。\n"
                f"2. 先只读诊断（日志/STATE.md/进程/run 转录），确认根因再动手。\n"
                f"3. 所有处置动作留痕（在处置记录中说明）。\n"
                f"4. 持久化优先：完成诊断后【先】写一次 .fenix/admin_disposition.json"
                f"（含初步结论与计划动作），再执行破坏性动作；任何时刻被杀都不丢处置记录。\n"
                f"5. 若确实无法自主处置（需人类决策、连续失败、不可逆操作），"
                f"将 escalate 置为 true 并给出 recommended_action。\n\n"
                f"## 完成后\n"
                f"把最终处置记录写入 .fenix/admin_disposition.json（当前目录即主树），"
                f"覆盖之前的初步记录。其中 summary 字段为必填：一段人类可读的叙述性总结，"
                f"必须包含诊断结论（问题是什么、根因）、处置时间线（做了什么、顺序）、"
                f"最终结果，以及如需人工介入时的具体建议：\n"
                f'{{\n'
                f'  "spec": "{sig_spec}",\n'
                f'  "problem": "处理的困境问题",\n'
                f'  "actions_taken": ["动作1", "动作2"],\n'
                f'  "result": "resolved | partially-resolved | escalated",\n'
                f'  "summary": "人类可读叙述：诊断结论 + 处置时间线 + 最终结果 + 对人类的建议",\n'
                f'  "escalate": true/false,\n'
                f'  "recommended_action": "若升级，给出人类应做的操作"\n'
                f'}}\n'
                f"然后结束，无需额外输出。不要直接编辑 .fenix/admin_alerts.json——"
                f"daemon 会基于你的处置记录写入。\n"
            )

    def _run_claude(self, prompt: str, cwd: Path, run_id: str,
                    model_override: str | None = None,
                    env_overrides: Dict[str, str] | None = None,
                    resume_session_id: str | None = None,
                    max_turns: int | None = None) -> tuple:
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
            model_override: Pass `--model <value>` explicitly. Needed for agent
                types that spawn subagents via the Agent SDK: the environment runs on
                ANTHROPIC_MODEL=deepseek-v4-flash (a non-Claude model name the SDK
                rejects with unrecognized_model, which is fatal on subagent spawn paths).
                An official Claude model name bypasses that check while requests still
                route through ANTHROPIC_BASE_URL. 调用方未配置 agents.subagent_model 时
                默认传入 claude-sonnet-5，保证始终通过 SDK 校验。
            env_overrides: 额外注入到子进程的环境变量（每线程独立 env 副本，不串扰）。
                用于按 agent_type 注入不同 Provider 的 baseurl/apikey/model。
            resume_session_id: 非 None 时以 `--resume <id>` 续跑该 session。
            max_turns: 单次运行轮次上限；达到即 kill（None 表示不限制）。

        Returns: (output, turns_used, session_id)
        """
        timeout = self._get_config("agents.run_timeout_seconds", 1800)

        # 每线程独立 env 副本，多 agent_type 并发时环境覆盖互不串扰
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)

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
        deadline = time.time() + timeout
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    proc.kill()
                    timeout_error = f"Timeout after {timeout}s"
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
            raise RuntimeError(f"claude CLI timed out after {timeout}s")

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

        return output, turns, session_id

    @staticmethod
    def _extract_session_id(run_file: Path) -> str | None:
        """从 run 产物提取 session_id（供 --resume 续跑）。

        session_id 出现在两类事件：开头的 system/init 事件（会话建立时），以及
        结尾的 result 事件。max_turns/超时强杀时 CLI 不会输出 result 事件，
        必须从 init 事件取，否则 resume 在 Max turns 场景失效（fix）。
        文件不存在/损坏返回 None。
        """
        try:
            size = run_file.stat().st_size
            with run_file.open("rb") as f:
                if size > 65536:
                    f.seek(size - 65536)
                tail = f.read().decode("utf-8", "replace")
                f.seek(0)
                head = f.read(65536).decode("utf-8", "replace")
        except OSError:
            return None
        for chunk in (head, tail):
            for line in chunk.splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                if e.get("type") == "result" and e.get("session_id"):
                    return e["session_id"]
                if (e.get("type") == "system" and e.get("subtype") == "init"
                        and e.get("session_id")):
                    return e["session_id"]
        return None

    def wait_for_running_agents(self, timeout: int = 300):
        """Wait for all running Agent subprocesses to complete (for graceful shutdown)."""
        deadline = time.time() + timeout
        for name, proc in list(self._running_agents.items()):
            remaining = deadline - time.time()
            if remaining <= 0:
                self.logger.warning("agent_runner", f"Killing agent: {name}")
                proc.kill()
                continue
            try:
                proc.wait(timeout=remaining)
                self.logger.info("agent_runner", f"Agent completed during shutdown: {name}")
            except subprocess.TimeoutExpired:
                self.logger.warning("agent_runner", f"Killing agent (timeout): {name}")
                proc.kill()

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
        from .config import ConfigLoader
        return ConfigLoader.get_agent_model_assignment(self.config, agent_type)

    def _get_config(self, key: str, default=None):
        """Get a nested config value."""
        from .config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)
