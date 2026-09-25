"""
cli_assertions.py — CLI 结构化断言库（spec multi-kind-scenario-model「CLI 词表与执行语义」）

分层语义跨 kind 统一：
  第1层 存在性/状态（确定性，0误判）：exit_code / file_exists / dir_contains
  第3层 内容正确性（确定性，0误判）：output_match / file_content / json_output

第1-3层断言失败 = 一定是Bug。CLI 无第 2 层（交互可用性是 DOM 概念）。

断言引用命名结果 MUST 通过 ``step`` 字段（对应 run 步骤的 ``as`` 命名；
缺省=最近一次 run）。``file_exists`` / ``file_content`` / ``dir_contains``
的 path/glob 相对验证树根。

非零退出码不判步骤失败（错误路径测试的正常预期），由 ``exit_code`` 断言
仲裁——本库只读 step_results 中的 exit_code/stdout/stderr 字段。
"""

import json
import re
from pathlib import Path

from .api_assertions import evaluate_json_path
from .scenarios import CLI_ASSERTION_LAYERS

# 文件内容断言读取上限（MB 级）：场景断言 path 误指向构建产物/日志等大文件时，
# 只读前 N 字节参与匹配，防全量读入撑爆验证进程内存（与 stdout 侧 64KB 证据
# 截断纪律同旨，文件匹配留 MB 级余量）。
_FILE_CONTENT_LIMIT = 8 * 1024 * 1024


class CliAssertionRunner:
    """执行结构化 CLI 断言。

    每个断言方法签名为: async def _assert_<type>(self, result, assertion) -> dict
    返回统一格式 dict: {type, layer, pass, ...}。
    """

    # 依赖命名 run 结果的断言类型单源：这些类型在派发前先经 _resolve_step
    # 取 step 再调 handler（签名 (step, assertion)），其余类型直接以
    # (assertion,) 调用。新增依赖命名结果的 _assert_<type> 时 MUST 同步登记。
    STEP_ASSERTIONS = frozenset({"exit_code", "output_match", "json_output"})

    def __init__(self, project_root=None, scenario_root=None):
        # 文件类断言解析根：worktree 轮用 scenario_root（步骤写入隔离树），
        # 无 worktree 轮用 project_root（既有行为）。
        self.project_root = Path(scenario_root or project_root or ".")

    # ── 断言执行入口 ──────────────────────────────────────────

    async def run(self, named_results: dict, assertions: list[dict]) -> list[dict]:
        """执行断言列表。

        Args:
            named_results: 命名 run 结果表（含 ``_latest`` 最近一次；
                每条含 exit_code/stdout/stderr）。
            assertions: 断言定义列表。
        """
        results: list[dict] = []
        for assertion in assertions:
            a_type = assertion.get("type", "")
            handler = getattr(self, f"_assert_{a_type}", None)
            if handler is None:
                results.append(
                    {
                        "type": a_type,
                        "layer": 0,
                        "pass": False,
                        "error": f"未知断言类型: {a_type}",
                    }
                )
                continue
            if a_type in self.STEP_ASSERTIONS:
                step = self._resolve_step(named_results, assertion)
                if step is None:
                    ref = assertion.get("step") or "_latest"
                    results.append(
                        {
                            "type": a_type,
                            "layer": 1 if a_type == "exit_code" else 3,
                            "pass": False,
                            "error": f"断言引用的 run 结果 '{ref}' 不存在"
                            f"（step 字段对应 run 步骤 as 命名，缺省=最近一次）",
                        }
                    )
                    continue
                try:
                    result = await handler(step, assertion)
                    results.append(result)
                    continue
                except Exception as e:
                    results.append(
                        {
                            "type": a_type,
                            "layer": 1 if a_type == "exit_code" else 3,
                            "pass": False,
                            "error": f"断言执行异常: {e}",
                        }
                    )
                    continue
            # 文件系统断言（不依赖命名结果）
            try:
                result = await handler(assertion)
                results.append(result)
            except Exception as e:
                results.append(
                    {
                        "type": a_type,
                        # 按词表映射归层（file_content 属第 3 层），未登记类型回退 0
                        "layer": CLI_ASSERTION_LAYERS.get(a_type, 0),
                        "pass": False,
                        "error": f"断言执行异常: {e}",
                    }
                )
        return results

    def _resolve_step(self, named_results: dict, assertion: dict):
        """断言引用的 run 结果：step 字段指定命名，缺省=最近一次。"""
        ref = assertion.get("step")
        if ref:
            return named_results.get(ref)
        return named_results.get("_latest")

    # ── 匹配辅助 ──────────────────────────────────────────────

    def _match(self, actual: str, expected: str, mode: str, negate: bool) -> bool:
        text = actual or ""
        if mode == "exact":
            m = text.strip() == str(expected).strip()
        elif mode == "regex":
            try:
                m = bool(re.search(str(expected), text))
            except re.error:
                m = False
        else:  # contains（缺省）
            m = str(expected) in text
        return (not m) if negate else m

    # ═══════════════════════════════════════════════════════════════
    # 第1层：存在性/状态（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_exit_code(self, step, a: dict) -> dict:
        """断言命令退出码等于期望值（缺省期望 0）。"""
        expected = a.get("expected", 0)
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            # expected 非法（如 "zero"/null）显式走断言异常通道，不回退 0 掩盖场景编写错误
            raise ValueError(f"expected 非法，须为整数: {expected!r}")
        actual = step.get("exit_code")
        return {
            "type": "exit_code",
            "layer": 1,
            "expected": expected,
            "actual": actual,
            "pass": actual == expected,
        }

    async def _assert_file_exists(self, a: dict) -> dict:
        """断言文件/目录存在（exists 缺省 true；path 相对验证树根）。"""
        path = (self.project_root / str(a.get("path", ""))).resolve()
        exists = path.exists()
        want = bool(a.get("exists", True))
        return {
            "type": "file_exists",
            "layer": 1,
            "path": str(path),
            "exists": exists,
            "pass": exists == want,
        }

    async def _assert_dir_contains(self, a: dict) -> dict:
        """断言目录通配匹配数量在 [min, max] 内（glob 相对验证树根）。"""
        glob = str(a.get("glob", "")).lstrip("/")
        paths = sorted(self.project_root.glob(glob)) if glob else []
        count = len(paths)
        minimum = a.get("min")
        maximum = a.get("max")
        ok_min = minimum is None or count >= int(minimum)
        ok_max = maximum is None or count <= int(maximum)
        passed = ok_min and ok_max
        result = {
            "type": "dir_contains",
            "layer": 1,
            "glob": glob,
            "count": count,
            "pass": passed,
        }
        if minimum is not None:
            result["min"] = int(minimum)
        if maximum is not None:
            result["max"] = int(maximum)
        if not passed:
            result["matches"] = [str(p.relative_to(self.project_root)) for p in paths[:10]]
        return result

    # ═══════════════════════════════════════════════════════════════
    # 第3层：内容正确性（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_output_match(self, step, a: dict) -> dict:
        """断言命令输出匹配（stream ∈ stdout/stderr/combined；mode/negate）。"""
        stream = str(a.get("stream", "combined"))
        stdout = str(step.get("stdout") or "")
        stderr = str(step.get("stderr") or "")
        if stream == "stdout":
            actual = stdout
        elif stream == "stderr":
            actual = stderr
        else:  # combined（缺省）
            actual = stdout + "\n" + stderr
        expected = a.get("expected", "")
        mode = a.get("mode", "contains")
        negate = bool(a.get("negate", False))
        passed = self._match(actual, expected, mode, negate)
        # 证据纪律：报告只保留命中片段（64KB 内、前后文截断），不膨胀
        snippet = ""
        if not passed and expected:
            idx = actual.find(str(expected))
            if idx >= 0:
                snippet = actual[max(0, idx - 80) : idx + len(str(expected)) + 80]
            else:
                snippet = actual[:160]
        return {
            "type": "output_match",
            "layer": 3,
            "stream": stream,
            "mode": mode,
            "expected": expected,
            "negate": negate,
            "pass": passed,
            "actual_snippet": snippet,
        }

    async def _assert_file_content(self, a: dict) -> dict:
        """断言文件内容匹配（path 相对验证树根；mode/negate）。"""
        path = (self.project_root / str(a.get("path", ""))).resolve()
        if not path.is_file():
            return {
                "type": "file_content",
                "layer": 3,
                "path": str(path),
                "pass": False,
                "error": f"文件不存在: {path}",
            }
        # 大文件防护：读取前先取 size。超限时 contains/regex 只读前 N 字节匹配
        # （结果带 truncated 标记），exact 模式无法截断比对，直接判失败。
        expected = a.get("expected", "")
        mode = a.get("mode", "contains")
        negate = bool(a.get("negate", False))
        size = path.stat().st_size
        if mode == "exact" and size > _FILE_CONTENT_LIMIT:
            return {
                "type": "file_content",
                "layer": 3,
                "path": str(path),
                "mode": mode,
                "expected": expected,
                "negate": negate,
                "pass": False,
                "error": f"文件过大（{size} 字节 > 上限 {_FILE_CONTENT_LIMIT}），exact 模式不做截断比对，判失败",
            }
        truncated = size > _FILE_CONTENT_LIMIT
        with path.open("rb") as fh:
            content = fh.read(_FILE_CONTENT_LIMIT).decode("utf-8", errors="replace")
        passed = self._match(content, expected, mode, negate)
        result = {
            "type": "file_content",
            "layer": 3,
            "path": str(path),
            "mode": mode,
            "expected": expected,
            "negate": negate,
            "pass": passed,
            "actual_snippet": content[:200] if not passed else "",
        }
        if truncated:
            result["truncated"] = True
        return result

    async def _assert_json_output(self, step, a: dict) -> dict:
        """断言命名结果 stdout 的 JSON 子树（step 指定解析哪个命名结果）。

        优先取 runner 预解析的 ``json`` 字段——它在证据截断**之前**由完整
        stdout 解析（>64KB 输出不因截断而解析失败）；无该字段时回退为解析
        ``stdout``（兼容直接构造 step 的调用方）。
        """
        stdout = str(step.get("stdout") or "")
        if "json_parsed" in step:
            if not step.get("json_parsed"):
                return {
                    "type": "json_output",
                    "layer": 3,
                    "step": a.get("step"),
                    "path": a.get("path"),
                    "pass": False,
                    "error": f"stdout 非合法 JSON: {stdout[:120]}",
                }
            data = step.get("json")
        else:
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                return {
                    "type": "json_output",
                    "layer": 3,
                    "step": a.get("step"),
                    "path": a.get("path"),
                    "pass": False,
                    "error": f"stdout 非合法 JSON: {stdout[:120]}",
                }
        path = a.get("path") or ""
        expected = a.get("expected")
        actual = evaluate_json_path(data, path) if path else data
        mode = a.get("mode", "exact")
        negate = bool(a.get("negate", False))
        passed = False
        if mode == "exact":
            passed = actual == expected
        elif mode == "contains":
            passed = str(expected) in str(actual)
        elif mode == "regex":
            try:
                passed = bool(re.search(str(expected), str(actual)))
            except re.error:
                passed = False
        if negate:
            passed = not passed
        return {
            "type": "json_output",
            "layer": 3,
            "step": a.get("step"),
            "path": path,
            "expected": expected,
            "actual": actual,
            "mode": mode,
            "pass": passed,
        }
