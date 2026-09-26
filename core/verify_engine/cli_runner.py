"""
cli_runner.py — CliRunner：subprocess 驱动的 CLI 场景执行（spec verify-runner-engine PR3）

步骤（限 cli 词表）：``run``——command（字符串=经 shell 执行、列表=argv
直接执行，与 prepare 解析约定同源）、cwd（相对验证树根）、env（值支持
{env:VAR} 插值）、stdin、timeout、as（命名结果）。

CLI 特异执行语义（与 web「失败即中断」唯一的分歧点，design D3）：
  - **非零退出码不判步骤失败**：错误路径测试的正常预期，结果照常记录
    （exit_code/stdout/stderr），由 exit_code 断言仲裁
  - **超时强杀 = 步骤失败**：hang 本身是要抓的缺陷；杀整个进程组防孤儿子进程
  - **信号死亡 = error**：被信号终止（如段错误）判 error 而非 fail，
    不进 product-bug 管道；argv 二进制不存在（FileNotFoundError）、
    cwd 目录不存在同判 error
  - 环境注入：``FENIX_VERIFY_BASE_URL`` / ``FENIX_VERIFY_PORT`` 自动注入且
    框架值优先——场景 env 中同名变量被框架值覆盖（防 stale 地址事故同一
    防护逻辑，design D4）；无实例形态下注入为空操作
  - 证据纪律：stdout/stderr 捕获超过 64KB 截断并带截断标记；
    场景结果 screenshots/visual_results 恒为空列表
"""

import asyncio
import json
import os
import re
import signal
from pathlib import Path
from urllib.parse import urlparse

from .runner import VerifyRunner, register_runner, determine_scenario_status
from .cli_assertions import CliAssertionRunner
from .scenarios import validate_scenario

_EVIDENCE_LIMIT = 64 * 1024  # 证据 64KB 截断上限
DEFAULT_RUN_TIMEOUT = 60.0


def _truncate(text: str) -> tuple:
    """证据截断：超过 64KB（UTF-8 字节口径）截断并带截断标记。返回 (截断后文本, truncated)。"""
    if text is None:
        return "", False
    # 按编码后字节数截断（与「64KB」声明同口径；中文等多字节输出按字符数
    # 比较会漏截）；errors="ignore" 丢弃尾部被切半的多字节序列，不出非法 UTF-8
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > _EVIDENCE_LIMIT:
        return encoded[:_EVIDENCE_LIMIT].decode("utf-8", errors="ignore"), True
    return text, False


def _interpolate_env(value: str, env: dict) -> str:
    """{env:VAR} 插值：未命中的占位符原样保留（防静默改写）。"""
    if not isinstance(value, str) or "{env:" not in value:
        return value

    def _repl(m):
        return env.get(m.group(1), m.group(0))

    return re.sub(r"\{env:([^}]+)\}", _repl, value)


@register_runner
class CliRunner(VerifyRunner):
    """subprocess 驱动的 CLI Runner。"""

    kind = "cli"

    def __init__(
        self, spec_name, project_root=None, logger=None, config: dict = None, scenario_root=None
    ):
        super().__init__(spec_name, project_root, logger, config, scenario_root=scenario_root)
        # 契约统一供给的实例 base_url（引擎注入；FENIX_VERIFY_BASE_URL/PORT
        # 注入依据）。无实例形态（纯 cli 轮次）为空字符串（注入空操作）。
        self.base_url = ""
        self.asserter = CliAssertionRunner(
            project_root=self.project_root,
            scenario_root=self.scenario_root,
        )

    # ── 场景验收 ───────────────────────────────────────────────

    def validate(self, scenario) -> list[str]:
        """cli 词表校验（仅 run 步骤 + CLI 断言必填字段）。"""
        return validate_scenario(scenario)

    # ── 生命周期 ───────────────────────────────────────────────

    async def setup(self):
        pass  # subprocess 驱动无全局资源

    async def teardown(self):
        pass

    # ── 场景执行 ───────────────────────────────────────────────

    async def execute(self, scenario) -> dict:
        """执行单个 cli 场景：run 步骤序列 + CLI 断言。"""
        named_results: dict = {}
        step_results: list[dict] = []
        steps_failed = False

        for step in scenario.steps:
            step_dict = step.to_dict()
            result = await self._execute_run(step_dict, named_results)
            step_results.append(result)
            if result.get("error_level") == "error":
                # 信号死亡/argv 二进制不存在/cwd 目录不存在 → 场景 error
                # （不进 product-bug 管道）
                return {
                    "scenario_id": scenario.id,
                    "description": scenario.description,
                    "kind": "cli",
                    "status": "error",
                    "error": result.get("error", ""),
                    "step_results": step_results,
                    "assertion_results": [],
                    "visual_results": [],
                    "screenshots": [],
                }
            if not result.get("success"):
                steps_failed = True
                break

        assertion_results: list[dict] = []
        if not steps_failed:
            assertion_defs = [a.to_dict() for a in scenario.assertions]
            assertion_results = await self.asserter.run(named_results, assertion_defs)

        status = determine_scenario_status(step_results, assertion_results, [])

        return {
            "scenario_id": scenario.id,
            "description": scenario.description,
            "kind": "cli",
            "status": status,
            "step_results": step_results,
            "assertion_results": assertion_results,
            "visual_results": [],
            "screenshots": [],
        }

    async def _execute_run(self, step_dict: dict, named_results: dict) -> dict:
        """执行单个 run 步骤（subprocess，进程组会话隔离）。"""
        cmd = step_dict.get("command")
        if not cmd:
            return {
                "success": False,
                "action": "run",
                "error": "run 步骤缺少 command",
            }
        use_shell = not isinstance(cmd, list)
        cwd = self._resolve_cwd(step_dict.get("cwd", ""))
        if cwd is None:
            # cwd 缺失属场景/环境缺陷：判 error 与信号死亡/二进制不存在同规
            # （不进 product-bug 管道），与 FileNotFoundError 分支口径一致
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"cwd 目录不存在: {step_dict.get('cwd')}",
            }
        env = self._build_env(step_dict.get("env") or {})
        stdin = str(step_dict.get("stdin") or "")
        try:
            timeout = float(step_dict.get("timeout") or 0) or DEFAULT_RUN_TIMEOUT
        except (TypeError, ValueError) as e:
            # 非法 timeout（非数字字符串/结构化值）归一为本步骤结构化失败，
            # 而非 ValueError 穿出令整个场景 run 异常中断（与 api_runner 同规）。
            return {
                "success": False,
                "action": "run",
                "error": f"timeout 须为数字（秒）: {step_dict.get('timeout')!r} ({e})",
            }
        name = str(step_dict.get("as") or "")

        try:
            if use_shell:
                proc = await asyncio.create_subprocess_shell(
                    str(cmd),
                    cwd=str(cwd),
                    env=env,
                    stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,  # 独立进程组：超时强杀可带全组
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *[str(c) for c in cmd],
                    cwd=str(cwd),
                    env=env,
                    stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
        except FileNotFoundError as e:
            # 空 cwd 回退链根目录（scenario_root/project_root）不做存在性校验，
            # 其缺失同样抛 FileNotFoundError，先区分文案避免误导向「二进制不存在」
            if not cwd.is_dir():
                return {
                    "success": False,
                    "action": "run",
                    "error_level": "error",
                    "error": f"cwd 目录不存在: {cwd}",
                }
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"命令二进制不存在（argv 形态）: {e}",
            }

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin.encode() if stdin else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # 超时强杀整个进程组（防孤儿子进程）＝步骤失败（hang 是要抓的缺陷）
            self._kill_process_group(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                pass
            return {
                "success": False,
                "action": "run",
                "error_type": "timeout",
                "error": f"命令超时（>{timeout}s），已强杀进程组: {cmd}",
            }

        exit_code = proc.returncode
        if exit_code is not None and exit_code < 0:
            # 被信号终止（如 SIGSEGV）→ error，不进 product-bug 管道
            sig = -exit_code
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error_type": "signal",
                "signal": sig,
                "error": f"命令被信号 {sig} 终止（段错误等），判 error 不进 product-bug 管道",
            }

        stdout_full = stdout_b.decode(errors="replace") if stdout_b else ""
        stderr_full = stderr_b.decode(errors="replace") if stderr_b else ""
        # JSON 解析必须用完整 stdout，早于证据截断（与 api_runner 同规）：
        # 若先 _truncate 再 json.loads，>64KB 的合法 JSON 会被截成非法文本 →
        # json_output 断言必然假失败（harness 缺陷，非产品缺陷、非场景缺陷）。
        # json_parsed 与 json 分开存：区分「非法 JSON」与合法的字面量 null。
        if stdout_full.strip():
            try:
                stdout_json = json.loads(stdout_full)
                stdout_json_parsed = True
            except json.JSONDecodeError:
                stdout_json = None
                stdout_json_parsed = False
        else:
            stdout_json = None
            stdout_json_parsed = False
        stdout, stdout_truncated = _truncate(stdout_full)
        stderr, stderr_truncated = _truncate(stderr_full)

        result = {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "json": stdout_json,
            "json_parsed": stdout_json_parsed,
        }
        if name:
            named_results[name] = result
        named_results["_latest"] = result

        # 非零退出码不判步骤失败：照常记录，由 exit_code 断言仲裁
        return {
            "success": True,
            "action": "run",
            "command": cmd,
            "exit_code": exit_code,
            "as": name or None,
            "detail": f"退出码 {exit_code}"
            + ("（stdout 已截断 64KB）" if stdout_truncated else "")
            + ("（stderr 已截断 64KB）" if stderr_truncated else ""),
        }

    # ── 辅助 ───────────────────────────────────────────────────

    def _resolve_cwd(self, rel: str):
        """cwd 相对验证树根（scenario_root）；无显式 cwd 时以验证树根为
        缺省（worktree 轮落验证树，无 worktree 轮回退 project_root）。
        目录不存在返回 None（判 error，不进 product-bug 管道）。
        """
        if not rel:
            # 回退链：scenario_root（有 serving worktree 时）→ project_root
            root = self.scenario_root or self.project_root
            return Path(root)
        # 有显式 cwd 时：相对验证树根
        root = self.scenario_root or self.project_root
        p = Path(root) / rel
        return p if p.is_dir() else None

    def _build_env(self, declared_env: dict) -> dict:
        """执行环境组装：进程环境 + 场景 env（{env:VAR} 插值）+ 框架注入优先。"""
        env = dict(os.environ)
        for k, v in (declared_env or {}).items():
            env[str(k)] = _interpolate_env(str(v), env)
        base_url, port = self._base_url_parts()
        if base_url:
            # 框架值优先：覆盖场景声明中的同名变量（防 stale 地址事故）
            env["FENIX_VERIFY_BASE_URL"] = base_url
            env["FENIX_VERIFY_PORT"] = port
        return env

    def _base_url_parts(self) -> tuple:
        """从契约 base_url 解析 (FENIX_VERIFY_BASE_URL, FENIX_VERIFY_PORT)。"""
        if not self.base_url:
            return "", ""
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return self.base_url, ""
        try:
            port = parsed.port
        except ValueError:
            # 端口段非法（非数字/越界，如 http://host:abc）：按非 http(s)
            # 分支原样透出 base_url、不注入端口，异常不作结构化穿出
            return self.base_url, ""
        port = port or (443 if parsed.scheme == "https" else 80)
        return self.base_url.rstrip("/"), str(port)

    @staticmethod
    def _kill_process_group(proc):
        """强杀整个进程组（SIGKILL）。"""
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
            except Exception:
                pass

    # ── 环境探针（环境门委托）─────────────────────────────────

    async def probe_env(self, candidates: list[dict]) -> dict:
        """CLI 第 1 版不做降级探针（超时=fail 是真缺陷语义）。

        返回保守健康——CLI 场景永不降级 blocked-env（is_env_candidate 只认
        mock_api/连接失败类，cli 无此类候选，本方法实际不被引擎触达）。
        """
        return {"healthy": True, "detail": "cli 第 1 版不做降级探针（超时=fail）"}
