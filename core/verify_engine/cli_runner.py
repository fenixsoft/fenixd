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
    不进 product-bug 管道——仅 argv 形态成立；shell 形态被监控的是 shell，
    内部命令信号死亡只体现为 shell 退出码 128+n，走非零退出码不判失败
    路径、由 exit_code 断言仲裁；argv 二进制不存在（FileNotFoundError）、
    cwd 目录不存在同判 error
  - 环境注入：``FENIX_VERIFY_BASE_URL`` / ``FENIX_VERIFY_PORT`` 自动注入且
    框架值优先——场景 env 中同名变量被框架值覆盖（防 stale 地址事故同一
    防护逻辑，design D4）；无实例形态下注入为空操作
  - 证据纪律：stdout/stderr 捕获超过 64KB 截断并带截断标记；
    场景结果 screenshots/visual_results 恒为空列表
"""

import asyncio
import json
import math
import os
import signal
from pathlib import Path
from urllib.parse import urlparse

from ._evidence import _EVIDENCE_LIMIT, _truncate, _interpolate_env  # 共享证据工具（符号出口保持）
from .runner import VerifyRunner, register_runner, determine_scenario_status
from .cli_assertions import CliAssertionRunner
from .scenarios import validate_scenario

DEFAULT_RUN_TIMEOUT = 60.0


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
        declared_env = step_dict.get("env") or {}
        if not isinstance(declared_env, dict):
            # 场景 env 非 dict 形态（如列表/字符串）：from_dict 对非空非 dict
            # 原样保留而词表校验不拦，直接进 _build_env 会 .items() 抛
            # AttributeError 穿出整个场景——归一为本步骤结构化失败（code-review
            # item 345415c58ac8，与 timeout 非法同规），判 error 与 cwd 缺失
            # 同口径：场景定义缺陷不进 product-bug 管道（item 74368415e965）
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"env 须为 object（键值表），收到 {type(declared_env).__name__}",
            }
        # 场景 env 键为空串或含 "="、控制字符（\x00、\n、\r 等）时，环境块
        # 无法表达，create_subprocess_shell/exec 会在 spawn 阶段抛 ValueError
        # 穿出 execute（except 只捕 FileNotFoundError）——归一为本步骤结构化
        # 失败（code-review item e9f97be76cd7，与 env 非 dict/timeout 非法
        # 同规），判 error 与 cwd 缺失同口径：场景定义缺陷不进 product-bug
        # 管道（item 74368415e965）。校验 _build_env 实际落键的 str(k) 形态
        for _k in declared_env:
            _key = str(_k)
            if not _key or "=" in _key or any(
                ord(c) < 32 or ord(c) == 127 for c in _key
            ):
                return {
                    "success": False,
                    "action": "run",
                    "error_level": "error",
                    "error": f"env 键须为非空且不含 '=' 或控制字符: {_k!r}",
                }
        env = self._build_env(declared_env)
        for _k in declared_env:
            # 场景 env 值含 NUL 空字节（场景 JSON \u0000 转义可构造）：
            # create_subprocess_shell/exec 在 spawn 阶段 os.fsencode 值时抛
            # ValueError: embedded null byte 穿出 execute（下方 except 只捕
            # FileNotFoundError）——校验 _build_env 落键的 _interpolate_env
            # 插值终值，归一为本步骤结构化失败（code-review item
            # 1878eb42b3d7，与 env 非 dict/env 键非法同规），判 error 与
            # cwd 缺失同口径：场景定义缺陷不进 product-bug 管道
            # （item 74368415e965）
            if "\x00" in env[str(_k)]:
                return {
                    "success": False,
                    "action": "run",
                    "error_level": "error",
                    "error": f"env 值不得含 NUL 空字节: {_k!r}",
                }
        stdin = step_dict.get("stdin") or ""
        if stdin and not isinstance(stdin, str):
            # 场景 stdin 非字符串形态（dict/list 等）：str() 强转会把 Python
            # repr（如 "{'a': 1}"）当文本静默注入子进程标准输入——归一为本
            # 步骤结构化失败（code-review item 166d6bced5d5，与 env 非 dict/
            # timeout 非法同规），判 error 与 cwd 缺失同口径：场景定义缺陷
            # 不进 product-bug 管道（item 74368415e965）
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"stdin 须为字符串，收到 {type(stdin).__name__}",
            }
        try:
            # 区分「键缺失」与「显式 0」：or 兜底会把显式 0（立即超时）静默
            # 改写成缺省 60s，与 api 侧 _execute_http_request 的 timeout 口径
            # 对齐——缺省仅在键缺失时生效
            _raw_timeout = step_dict.get("timeout")
            timeout = float(
                DEFAULT_RUN_TIMEOUT if _raw_timeout is None else _raw_timeout
            )
        except (TypeError, ValueError) as e:
            # 非法 timeout（非数字字符串/结构化值）归一为本步骤结构化失败，
            # 而非 ValueError 穿出令整个场景 run 异常中断（与 api_runner 同规）。
            # 判 error 与 cwd 缺失同口径：场景定义缺陷不进 product-bug 管道
            # （item 74368415e965）
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"timeout 须为数字（秒）: {step_dict.get('timeout')!r} ({e})",
            }
        if timeout < 0:
            # 负数 timeout 直通 wait_for 会立即抛 TimeoutError 走超时强杀，
            # 把场景定义错误误判成 hang 缺陷：归一为本步骤结构化失败
            # （code-review item bf2ffeded38c，词表校验层已同拦负值），
            # 判 error 同上口径（item 74368415e965）
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"timeout 须为正数（秒）: {step_dict.get('timeout')!r}",
            }
        if not math.isfinite(timeout):
            # float() 接受 "inf"/"1e999"（→inf）与 "nan"，负值检查对两者均
            # 放行：inf 传 wait_for 等效无限等待，「超时强杀」hang 兜底失效，
            # 一条场景声明即可挂起整轮验证——非有限值与负值同口径结构化失败
            # （code-review item 670544033774）
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"timeout 须为有限数字（秒）: {step_dict.get('timeout')!r}",
            }
        name = str(step_dict.get("as") or "")
        if name == "_latest":
            # `_latest` 是框架保留键（断言缺省引用最近一次 run 结果）：场景
            # as 命名撞上会与 named_results["_latest"] 同槽自我覆盖，执行期
            # 拒绝为结构化失败（code-review item 30a8c34f0535），判 error 与
            # cwd 缺失同口径：场景定义缺陷不进 product-bug 管道
            # （item 74368415e965）
            return {
                "success": False,
                "action": "run",
                "error_level": "error",
                "error": f"as 命名 '{name}' 是框架保留键，请改用其他名称",
            }

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
            if use_shell:
                # shell 形态 FileNotFoundError 只可能来自 shell 解释器本体
                # 缺失（部署环境极罕见），按形态区分文案避免误导排障方向
                # （code-review item 6b63412f7366）
                return {
                    "success": False,
                    "action": "run",
                    "error_level": "error",
                    "error": f"shell 解释器路径错误: {e}",
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
            # 强杀后回收超时前子进程已产出的输出证据：communicate 被 wait_for
            # 取消时传输层缓冲仍在 StreamReader 里，SIGKILL 后管道随即 EOF、
            # read 会很快返回——丢弃会让排障看不到子进程超时前打印了什么
            # （code-review item 728aacc5729c）。回收是尽力而为：读不到就
            # 放弃（不因回收证据引入新故障），附进结果沿用 64KB 证据纪律
            stdout_b = await self._drain_after_kill(proc.stdout)
            stderr_b = await self._drain_after_kill(proc.stderr)
            stdout, stdout_truncated = _truncate(stdout_b.decode(errors="replace"))
            stderr, stderr_truncated = _truncate(stderr_b.decode(errors="replace"))
            return {
                "success": False,
                "action": "run",
                "error_type": "timeout",
                "stdout": stdout,
                "stderr": stderr,
                "error": f"命令超时（>{timeout}s），已强杀进程组: {cmd}"
                + ("（stdout 已截断 64KB）" if stdout_truncated else "")
                + ("（stderr 已截断 64KB）" if stderr_truncated else ""),
            }

        exit_code = proc.returncode
        if exit_code is not None and exit_code < 0:
            # 被信号终止（如 SIGSEGV）→ error，不进 product-bug 管道。
            # 仅 argv 形态成立：shell 形态被监控的是 shell，内部命令信号死亡
            # 只体现为 shell 退出码 128+n，由 exit_code 断言仲裁
            # （code-review item bf0cbf18b226）
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
        root = self.scenario_root or self.project_root
        if not rel:
            # 回退链：scenario_root（有 serving worktree 时）→ project_root
            return Path(root)
        # 有显式 cwd 时：相对验证树根。护栏与 cli_assertions._resolve_under_root
        # 同款（code-review item 6b9b164b3ed9）：pathlib 的 ``/`` 对绝对路径
        # 直接取绝对路径、``..`` 段就地折叠，放行会让子进程落在验证树之外
        # （worktree 轮即绕过隔离语义，产物/副作用落到主树）；resolve 后
        # 再校验前缀仍在本根内（防符号链接逃逸）。非法按 cwd 缺失同口径
        # 判 error，不进 product-bug 管道。
        root_path = Path(root)
        rel_path = Path(str(rel))
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return None
        p = root_path / rel_path
        try:
            p.resolve().relative_to(root_path.resolve())
        except ValueError:
            return None
        # [fenix-ignore:5f27f4a2d378] cwd 含 NUL 时上方 p.resolve() 先抛 ValueError 已被 except 捕获返回 None（即便落至 is_dir()，pathlib 自身也吞 ValueError 返 False），结构化 cwd 缺失口径已在位，所述穿出路径不存在
        return p if p.is_dir() else None

    def _build_env(self, declared_env: dict) -> dict:
        """执行环境组装：进程环境 + 场景 env（{env:VAR} 插值）+ 框架注入优先。"""
        env = dict(os.environ)
        base_url, port = self._base_url_parts()
        if base_url:
            # 先播种框架值：让场景 env 的 {env:FENIX_VERIFY_*} 插值可见，
            # 否则 daemon 进程环境无同名变量时占位符按「未命中」残留字面文本
            env["FENIX_VERIFY_BASE_URL"] = base_url
            env["FENIX_VERIFY_PORT"] = port
        for k, v in (declared_env or {}).items():
            env[str(k)] = _interpolate_env(str(v), env)
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

    @staticmethod
    async def _drain_after_kill(stream) -> bytes:
        """强杀后回收超时前已缓冲的输出证据（小超时+异常安全的尽力而为）。

        communicate 被 wait_for 取消后，传输层已送达的数据仍留在 StreamReader
        缓冲；SIGKILL 后管道随即 EOF，read(_EVIDENCE_LIMIT + 1) 在缓冲枯竭
        或 EOF 时立即返回（多读 1 字节用于区分「恰满 64KB」与「超限截断」，
        超限部分本就按证据纪律截断丢弃）。读不到（读侧异常/1s 内未 EOF）就
        返回空——证据回收不得引入新故障（code-review item 728aacc5729c）。
        """
        if stream is None:
            return b""
        try:
            return await asyncio.wait_for(
                stream.read(_EVIDENCE_LIMIT + 1), timeout=1.0
            )
        except Exception:
            return b""

    # ── 环境探针（环境门委托）─────────────────────────────────

    async def probe_env(self, candidates: list[dict]) -> dict:
        """CLI 第 1 版不做降级探针（超时=fail 是真缺陷语义）。

        返回保守健康——CLI 场景永不降级 blocked-env（is_env_candidate 只认
        mock_api/连接失败类，cli 无此类候选，本方法实际不被引擎触达）。
        """
        return {"healthy": True, "detail": "cli 第 1 版不做降级探针（超时=fail）"}
