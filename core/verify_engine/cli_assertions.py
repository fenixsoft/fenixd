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
from pathlib import Path

from .api_assertions import _MISSING, _compile_regex, evaluate_json_path
from .scenarios import CLI_ASSERTION_LAYERS

# 文件内容断言读取上限（MB 级）：场景断言 path 误指向构建产物/日志等大文件时，
# 只读前 N 字节参与匹配，防全量读入撑爆验证进程内存（与 stdout 侧 64KB 证据
# 截断纪律同旨，文件匹配留 MB 级余量）。
_FILE_CONTENT_LIMIT = 8 * 1024 * 1024


def _regex_brace_body(pattern: str, i: int) -> "str | None":
    """取 pattern[i] 起始的 ``{...}`` 量词体；无闭合 ``}`` 返回 None。"""
    j = pattern.find("}", i + 1)
    return pattern[i + 1 : j] if j > i else None


def _has_nested_quantifier(pattern: str) -> bool:
    """高危正则预检：检测「组内变长量词 × 组整体无上界量词」的嵌套形态
    （灾难性回溯的典型结构特征，如 ``(.+)*`` / ``(\\d+)+`` / ``(a{1,2})+``）。

    保守取舍（宁少拦不误拦）：
      - 仅当组闭合紧跟无上界量词（``*``/``+``/``{m,}``）且组内直接出现变长
        量词（``*``/``+``/``{m,n}``）才判高危——外层有界量词（``?``/``{m}``）
        重复次数有限、内层定长（``{m}``）切分唯一，均不构成指数级回溯，不拦；
      - 重叠分支等结构不典型的形态（如 ``(a|aa)+``）不识别，属刻意漏拦：
        漏拦的代价是慢，误拦的代价是拒绝合法场景断言。
      - 内层 ``{m,n}`` 范围量词亦按变长计：有界却仍拦（``(a{1,2})+`` 类
        有界形态同样指数回溯，与 ``(?:\\d{1,3}\\.)*`` 类以分隔符消歧的
        安全形态须语义分析才能区分）——后者是 IP/版本号惯用写法，会被
        确定性拒绝（fail-closed 可见化，拒绝文案附改写建议），误拦面比
        「宁少拦」宣称更宽，属已知取舍。
    跳过转义序列与字符类（``[*+]`` 内的量词字符是字面量）。
    """
    group_has_variable_quant: list[bool] = []
    in_class = False
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            i += 2  # 转义序列整体跳过（含被转义的量词字符）
            continue
        if in_class:
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
        elif ch == "(":
            group_has_variable_quant.append(False)
            if i + 1 < n and pattern[i + 1] == "?":
                i += 2  # 「(?:」「(?=」等的 ? 是组语法而非量词，不计
                continue
        elif ch == ")":
            if group_has_variable_quant:
                had = group_has_variable_quant.pop()
                nxt = pattern[i + 1] if i + 1 < n else ""
                unbounded = nxt in ("*", "+") or (
                    nxt == "{"
                    and (_regex_brace_body(pattern, i + 1) or "").endswith(",")
                )
                if had and unbounded:
                    return True
        elif ch in "*+":
            if group_has_variable_quant:
                group_has_variable_quant[-1] = True
        elif ch == "{":
            body = _regex_brace_body(pattern, i)
            if body and "," in body and group_has_variable_quant:
                group_has_variable_quant[-1] = True
        i += 1
    return False


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
            if not isinstance(assertion, dict):
                # fail-closed：非 dict 断言条目（planner/自愈链路产出的畸形
                # 条目，如字符串或 None）会让下方 assertion.get 抛
                # AttributeError，且在 run() 的 try 之外直接穿透（try 只包
                # handler 调用）；本文件对 path/glob/expected 等字段的防御
                # 注释多处宣称兜住运行期自愈路径，断言条目是同级别的不可信
                # 输入。按「未知断言类型」同款结构返回确定性失败（与 api 侧
                # run() 的同款守卫口径对齐）
                results.append(
                    {
                        "type": None,
                        "layer": 0,
                        "pass": False,
                        "error": (
                            f"断言条目非法: 须为 dict，"
                            f"实际 {type(assertion).__name__}"
                        ),
                    }
                )
                continue
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
                            "layer": CLI_ASSERTION_LAYERS.get(a_type, 0),
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
                            "layer": CLI_ASSERTION_LAYERS.get(a_type, 0),
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
            # 不可哈希 step（list/dict，YAML 合法表达）会让 dict.get 抛
            # TypeError，且本函数调用在 run() 的 per-assertion try 之外，
            # 异常整批穿透使全部断言结果被场景级 error 取代（同 122-141 行
            # 非 dict 守卫口径：断言字段是同级别的不可信输入）——按下方
            # 「引用的 run 结果不存在」同款定向失败归一为 None
            if not isinstance(ref, str):
                return None
            return named_results.get(ref)
        return named_results.get("_latest")

    # ── 匹配辅助 ──────────────────────────────────────────────

    def _match(self, actual, expected, mode: str, negate: bool, *, exact_strip: bool = True) -> bool:
        """exact/contains/regex 匹配单一实现（output_match / file_content /
        json_output 共用，防双实现漂移）。

        exact_strip=True（缺省，文本断言）：exact 对两侧 .strip() 后比较——
            terminal 输出/文件内容常带首尾空白（如尾换行），strip 更宽容。
        exact_strip=False（json_output）：exact 直接结构相等比较——actual 是
            JSON 子树，可为 int/bool/None/list/dict，字符串化会改变语义
            （如 5.0 == 5 成立而 "5.0" != "5"），故不做 str() 也不 strip。
        contains/regex：actual 为 str 时原样参与（既有调用方传入恒为 str，
            与原 `actual or ""` 兜底等价），非 str（仅 json_output）先 str()
            字符串化（与既有 json_output 行为一致）。
        """
        # 配置错误可见化：未知 mode 显式走断言异常通道（与 api 侧
        # sse_event_matches「未知 mode」及 run()「未知断言类型」口径对齐），
        # 不静默按 contains 匹配掩盖场景编写缺陷
        if mode not in ("exact", "contains", "regex"):
            raise ValueError(f"未知 mode: {mode}")
        if mode == "exact":
            if exact_strip:
                m = (actual or "").strip() == str(expected).strip()
            else:
                m = actual == expected
        else:
            text = actual if isinstance(actual, str) else str(actual)
            if mode == "regex":
                # 高危形态预检：灾难性回溯正则（嵌套量词类）可在 MB 级文本上
                # 长时间占住断言协程。显式拒绝走断言异常通道而非静默执行（与
                # 下方非法正则的口径对齐；预检保守宁少拦不误拦，见函数
                # docstring）
                if _has_nested_quantifier(str(expected)):
                    raise ValueError(
                        f"正则含嵌套量词高危形态（组内变长量词再被无上界量词"
                        f"化，灾难性回溯风险），已拒绝执行: {expected!r}；"
                        f"改写建议：把无上界量词上提为顶层有界重复，如 "
                        f"(?:\\d{{1,3}}\\.)* → (?:[0-9]{{1,3}}\\.){{0,20}}"
                    )
                # 复用 api 侧 _compile_regex/_TimeoutRegex 包装匹配：regex 库
                # 可用时 search 带 1s 时限，预检刻意漏拦的不典型回溯形态（如
                # 重叠分支）由超时收口而非无限占住断言协程（超时按 re.error
                # fail-closed，走下方非法正则同一异常通道）；库缺失时回退
                # stdlib re，行为同无防护版
                pattern, regex_error = _compile_regex(str(expected))
                if regex_error is not None:
                    # 非法正则是场景编写缺陷，显式走断言异常通道（与
                    # _assert_exit_code 对非法 expected 对齐），不令 m=False
                    # 掩盖——negate 场景会静默假绿
                    raise ValueError(f"非法正则表达式: {expected!r}（{regex_error}）")
                m = bool(pattern.search(text))
            else:  # contains（缺省）
                m = str(expected) in text
        return (not m) if negate else m

    def _normalize_bool_field(self, raw, field: str) -> bool:
        """布尔字段显式归一单实现（negate / exists 共用，防多内联口径漂移）。

        bool 原样收；数值 0/1 按布尔语义映射（与字符串 "1"/"0" 同为无歧义
        表示；int 分支须在 bool 之后——bool 是 int 子类）；字符串按
        "true"/"false"/"1"/"0" 解析；其余脏值显式失败——bool("false") 类
        非空字符串恒真会静默反转断言裁决方向（contains 命中判 fail、negate
        场景假绿），且结果字段无从察觉写的是 "false"。
        """
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int) and raw in (0, 1):
            return bool(raw)
        normalized = raw.strip().lower() if isinstance(raw, str) else raw
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
        raise ValueError(
            f"{field} 非法，须为布尔或数值 0/1 或 'true'/'false'/'1'/'0': {raw!r}"
        )

    def _normalize_negate(self, a: dict) -> bool:
        """negate 显式归一（output_match / file_content / json_output 共用）。

        与 _assert_file_exists 对 exists 的归一口径对齐：二者共用
        _normalize_bool_field 单实现（bool 原样收；数值 0/1 按布尔语义映射；
        字符串四值解析；其余脏值显式失败，详见其 docstring）。
        """
        return self._normalize_bool_field(a.get("negate", False), "negate")

    def _resolve_under_root(self, raw) -> "Path | None":
        """文件类断言 path/glob 的统一解析护栏：限定在验证树根内。

        与 docstring「path/glob 相对验证树根」的承诺对齐：拒绝绝对路径
        （pathlib 的 ``/`` 对绝对路径直接取绝对路径，静默落到树根之外）
        与含 ``..`` 的段；resolve 后再校验前缀仍在本根内（防符号链接
        逃逸）。worktree 轮若放行，断言会读到主树而非隔离树的文件，
        产生假结果。返回 None 表示路径非法，由调用方按断言失败语义
        记录错误，不抛异常破坏断言收集流程。
        """
        rel = Path(str(raw))
        if rel.is_absolute() or ".." in rel.parts:
            return None
        # NUL 字节等非法路径（YAML 双引号串 "\0" 可合法表达）会让 resolve()
        # 抛 ValueError（OSError 为文件系统层兜底），违背本函数「不抛异常
        # 破坏断言收集流程」的契约——归一为 None（路径非法），调用方走既有
        # 「path 非法」定向失败分支而非泛化「断言执行异常」
        try:
            resolved = (self.project_root / rel).resolve()
        except (ValueError, OSError):
            return None
        try:
            resolved.relative_to(self.project_root.resolve())
        except ValueError:
            return None
        return resolved

    # ═══════════════════════════════════════════════════════════════
    # 第1层：存在性/状态（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_exit_code(self, step, a: dict) -> dict:
        """断言命令退出码等于期望值（缺省期望 0）。"""
        expected = a.get("expected", 0)
        # bool 是 int 子类，须在 int() 前显式排除（同 _normalize_negate 的
        # 先-bool-后-int 纪律、verify_contract._positive_int_or_default 先例）：
        # expected: true 否则被静默折算成 1 改写断言目标而非显式报错
        if isinstance(expected, bool):
            raise ValueError(f"expected 非法，须为整数: {expected!r}")
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
        # exists 显式归一：与 negate 共用 _normalize_bool_field 单实现
        # （bool 原样收；数值 0/1 按布尔语义映射；字符串四值解析；其余脏值
        # 显式失败，防 bool("false") 类非空字符串恒真静默反转断言语义产出
        # 假失败，与 _assert_exit_code 对非法 expected 的口径对齐）
        want = self._normalize_bool_field(a.get("exists", True), "exists")
        raw_path = a.get("path", "")
        if raw_path is None or (isinstance(raw_path, str) and not raw_path.strip()):
            # 空/空白 path 经 Path("") 归一为 "." 落回验证树根本体——根本体
            # exists() 恒真产出假通过；显式 null 经 Path(str(None)) 伪装成
            # 字面量 "None" 路径，exists=false 断言恒通过，同按缺参失败。与
            # 缺 expected 的显式失败口径对齐（验收期必填表
            # ASSERTION_REQUIRED_FIELDS 是前置防线，此处兜住运行期自愈/绕过
            # 验收的调用路径）
            return {
                "type": "file_exists",
                "layer": 1,
                "path": raw_path,
                "pass": False,
                "error": "缺少 path 字段",
            }
        path = self._resolve_under_root(raw_path)
        if path is None:
            return {
                "type": "file_exists",
                "layer": 1,
                "path": str(a.get("path", "")),
                "pass": False,
                "error": "path 非法：须为相对验证树根的路径（不得为绝对路径或含 '..' 段）",
            }
        exists = path.exists()
        return {
            "type": "file_exists",
            "layer": 1,
            "path": str(path),
            "exists": exists,
            "pass": exists == want,
        }

    async def _assert_dir_contains(self, a: dict) -> dict:
        """断言目录通配匹配数量在 [min, max] 内（glob 相对验证树根）。"""
        raw_glob = a.get("glob")
        # 先拦 None 再字符串化：显式 null 经 str(None)="None" 会伪装成非空串
        # 绕过空值拦截（字面量 "None" 路径 glob 计 0，无 min/max 时恒通过），
        # 与空/缺失 glob 同按缺参失败
        glob = "" if raw_glob is None else str(raw_glob)
        if not glob.strip():
            # 空/缺失/显式 null glob 经 _resolve_under_root 落回树根本体并走
            # 下方 ``if glob else []`` 计 0——无 min/max 声明时恒通过。词表将
            # glob 列为必填（ASSERTION_REQUIRED_FIELDS mode "post"，缺失/
            # 空串均非法，本库无「glob 缺省=只验目录存在」语义），与缺
            # expected 的显式失败口径对齐
            return {
                "type": "dir_contains",
                "layer": 1,
                "glob": glob,
                "count": 0,
                "pass": False,
                "error": "缺少 glob 字段",
            }
        if self._resolve_under_root(glob) is None:
            return {
                "type": "dir_contains",
                "layer": 1,
                "glob": glob,
                "count": 0,
                "pass": False,
                "error": "glob 非法：须为相对验证树根的路径（不得为绝对路径或含 '..' 段）",
            }
        paths = sorted(self.project_root.glob(glob)) if glob else []
        count = len(paths)
        minimum = a.get("min")
        maximum = a.get("max")
        # bool 是 int 子类，须在 int() 前显式排除（同 _assert_exit_code 的
        # bool 前判口径）：min/max: true 否则被静默折算成 1 改写断言边界
        if isinstance(minimum, bool) or isinstance(maximum, bool):
            raise ValueError(
                f"min/max 非法，须为整数: min={minimum!r}, max={maximum!r}"
            )
        try:
            min_n = None if minimum is None else int(minimum)
            max_n = None if maximum is None else int(maximum)
        except (TypeError, ValueError):
            # min/max 非法（如 "two"）显式带参数名走断言异常通道，与
            # _assert_exit_code 对非法 expected 的文案口径对齐——裸 int() 的
            # 「invalid literal」报错定位不到是哪个边界写错
            raise ValueError(
                f"min/max 非法，须为整数: min={minimum!r}, max={maximum!r}"
            )
        ok_min = min_n is None or count >= min_n
        ok_max = max_n is None or count <= max_n
        passed = ok_min and ok_max
        result = {
            "type": "dir_contains",
            "layer": 1,
            "glob": glob,
            "count": count,
            "pass": passed,
        }
        if min_n is not None:
            result["min"] = min_n
        if max_n is not None:
            result["max"] = max_n
        if not passed:
            result["matches"] = [str(p.relative_to(self.project_root)) for p in paths[:10]]
        return result

    # ═══════════════════════════════════════════════════════════════
    # 第3层：内容正确性（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_output_match(self, step, a: dict) -> dict:
        """断言命令输出匹配（stream ∈ stdout/stderr/combined；mode/negate）。"""
        stream = str(a.get("stream", "combined"))
        if stream not in ("stdout", "stderr", "combined"):
            # stream 非法（如拼写错误 "stdoud"）显式失败而非静默按 combined
            # 匹配：拼接体可能因另一股流的巧合内容假通过/假失败且无任何提示，
            # 与未知 mode / 缺 expected 的显式失败口径对齐
            return {
                "type": "output_match",
                "layer": 3,
                "stream": stream,
                "pass": False,
                "error": f"stream 非法，须为 stdout/stderr/combined: {stream!r}",
            }
        stdout = str(step.get("stdout") or "")
        stderr = str(step.get("stderr") or "")
        if stream == "stdout":
            actual = stdout
        elif stream == "stderr":
            actual = stderr
        else:  # combined（缺省）
            actual = stdout + "\n" + stderr
        expected = a.get("expected")
        mode = a.get("mode", "contains")
        negate = self._normalize_negate(a)
        # 判空口径（expected is None 才算缺参）：None 恒拦——exact 缺参仍须按
        # 缺参失败，否则会滑进 _match 与 str(None)="None" 比对；空串仅拦
        # contains/regex（`"" in actual` 恒真、空正则恒匹配），exact 空串是
        # 「命令输出恰为空」的合法期望故放行（与 _assert_file_content 的
        # 「文件恰为空」口径对齐）；数值 expected（如 0）非空值，按 str()
        # 归一参与 _match 匹配，与 api 侧数值归一放行口径一致，不按缺参误拦
        if expected is None or (expected == "" and mode != "exact"):
            # 显式失败而非静默恒真：缺参/空串的 contains 对任意输出恒真、
            # regex 空串恒匹配，会产出假通过；与 web 侧
            # text_contains 缺参口径对齐
            return {
                "type": "output_match",
                "layer": 3,
                "stream": stream,
                "mode": mode,
                "expected": expected,
                "negate": negate,
                "pass": False,
                "error": "缺少 expected 字段",
            }
        passed = self._match(actual, expected, mode, negate)
        # 证据纪律：报告只保留命中片段（64KB 内、前后文截断），不膨胀
        snippet = ""
        # is not None 判空：数值 expected（如 0）匹配失败时也带命中片段证据
        if not passed and expected is not None:
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
        raw_path = a.get("path", "")
        if raw_path is None or (isinstance(raw_path, str) and not raw_path.strip()):
            # 空/缺失/显式 null path 经 Path("") 归一为 "." 落回验证树根本体，
            # 根本体 is_file() 为 False 误报「文件不存在」，把场景编写缺参
            # 误导为产品未产出文件；与 _assert_file_exists 的缺参显式失败
            # 口径对齐（验收期必填表 ASSERTION_REQUIRED_FIELDS 是前置防线，
            # 此处兜住运行期自愈/绕过验收的调用路径）
            return {
                "type": "file_content",
                "layer": 3,
                "path": raw_path,
                "pass": False,
                "error": "缺少 path 字段",
            }
        path = self._resolve_under_root(raw_path)
        if path is None:
            return {
                "type": "file_content",
                "layer": 3,
                "path": str(a.get("path", "")),
                "pass": False,
                "error": "path 非法：须为相对验证树根的路径（不得为绝对路径或含 '..' 段）",
            }
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
        # 哨兵区分缺参与显式空串/null（复用 api 侧 _MISSING）：缺参归一 ""
        # 会让 explicit null 在 exact 模式放行，滑进 _match 与
        # str(None)="None" 的比对——文件内容恰为 "None" 时断言假通过，正是
        # _assert_output_match 判空注释防住的失效形态
        expected = a.get("expected", _MISSING)
        mode = a.get("mode", "contains")
        negate = self._normalize_negate(a)
        missing = expected is _MISSING or expected is None
        if missing or (expected == "" and mode != "exact"):
            # 显式失败而非静默恒真：缺 expected 时 contains 的 `"" in 内容`
            # 恒真、regex 空串恒匹配，会产出假通过；空串仅拦 contains/regex，
            # exact 空串是空文件合法期望故放行（仅显式空串，缺参/null 均按
            # 缺参失败）；数值 expected（如 0）非空值，按 str() 归一参与
            # 匹配，不按缺参误拦（与 _assert_output_match 及 api 侧数值归一
            # 口径对齐）。验收期必填表 ASSERTION_REQUIRED_FIELDS 是前置
            # 防线，此处兜住运行期自愈/绕过验收的调用路径
            return {
                "type": "file_content",
                "layer": 3,
                "path": str(path),
                "mode": mode,
                "expected": None if expected is _MISSING else expected,
                "negate": negate,
                "pass": False,
                "error": "缺少 expected 字段",
            }
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
        if truncated and negate:
            # 大文件超限 + negate：只读前 N 字节的截断样本无法完整反证「不包含
            # expected」，截断点之后的真实出现会被漏检而静默假绿（truncated 标记
            # 不参与裁决）。按断言失败处理（与 exact 超限分支同原则：无法完整
            # 比对即判失败），并带 error/truncated 供定位。
            passed = False
            error = (
                f"文件过大（{size} 字节 > 上限 {_FILE_CONTENT_LIMIT}），"
                f"negate 断言无法在截断样本上完整反证，判失败"
            )
        else:
            passed = self._match(content, expected, mode, negate)
            error = ""
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
        if error:
            result["error"] = error
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
            if "json" not in step:
                # 读取键与哨兵键配对：json_parsed=True 但缺 json 键属直接构造
                # step 的调用方缺陷，显式失败而非 data=None 参与比对（path 为
                # 空时 None 与 expected 静默对照，可假通过或产生无从解释的
                # 失败）。按键存在性校验：合法的字面量 null 走 json=None 值，
                # 不在此误伤
                return {
                    "type": "json_output",
                    "layer": 3,
                    "step": a.get("step"),
                    "path": a.get("path"),
                    "pass": False,
                    "error": "step 含 json_parsed=True 但缺 json 字段（两者由 cli_runner 成对写入，直接构造 step 时须同时提供）",
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
        # fail-closed：非字符串 path（如 YAML 合法标量 path: 5 归一成 int）
        # 不静默放行——原样传给 evaluate_json_path 会在路径 token 拆分时抛
        # TypeError，被 run() 兜底归一成泛化「断言执行异常」，丢掉「path 字段
        # 类型非法」这一可直接修复的定位信息。口径对齐 api 侧 _assert_json_path
        # （验收期必填表 ASSERTION_REQUIRED_FIELDS 是前置防线，此处兜住运行期
        # 自愈/绕过验收的调用路径）
        path = a.get("path")
        if not isinstance(path, str) or not path:
            return {
                "type": "json_output",
                "layer": 3,
                "step": a.get("step"),
                "path": path,
                "pass": False,
                "error": "缺少 path 字段或类型非法（path 须为非空字符串）",
            }
        expected = a.get("expected", _MISSING)
        # 哨兵区分「路径不存在」与「显式 null」（与 api 侧 _assert_json_path
        # 口径对齐）：expected=null 且路径缺失时 None==None 会假通过
        actual = evaluate_json_path(data, path, missing=_MISSING) if path else data
        path_missing = bool(path) and actual is _MISSING
        if path_missing:
            # 哨兵仅内部判定，不外泄（actual 归一为 None）
            actual = None
        mode = a.get("mode", "exact")
        negate = self._normalize_negate(a)
        if path_missing:
            # fail-closed：路径缺失对任何比对 mode 都显式报错（negate 下也不
            # 放行——缺失属场景/产品缺陷，须可定位），不做内容比对
            return {
                "type": "json_output",
                "layer": 3,
                "step": a.get("step"),
                "path": path,
                "expected": None if expected is _MISSING else expected,
                "actual": None,
                "mode": mode,
                "pass": False,
                "error": (
                    f"路径 {path!r} 在 JSON 载荷中不存在（区别于显式 null），"
                    f"无法与 expected 对比"
                ),
            }
        # fail-closed：比照 _assert_file_content 缺 expected 预检（None 是
        # 「未设置」哨兵非显式 null）——缺参时 exact 的 None==None 会把目标
        # 值为显式 null 的假通过计入裁决，contains 则滑进 str(None)="None"
        # 子串比对（验收期必填表 ASSERTION_REQUIRED_FIELDS 已登记 expected，
        # 此处兜住运行期自愈/绕过验收的调用路径）；空串仅拦 contains/regex
        # （`"" in str(actual)` 对任意 JSON 子树恒真、空正则恒匹配），exact
        # 空串对字符串子树是合法期望故放行（与 _assert_output_match /
        # _assert_file_content 的判空口径对齐）
        if expected is _MISSING or expected is None or (expected == "" and mode != "exact"):
            return {
                "type": "json_output",
                "layer": 3,
                "step": a.get("step"),
                "path": path,
                "expected": None if expected is _MISSING else expected,
                "mode": mode,
                "negate": negate,
                "pass": False,
                "error": "缺少 expected 字段",
            }
        # 匹配逻辑与 _match 共用单一实现；exact 走结构相等（JSON 值可非字符串，
        # 不做 str()/strip），与文本断言的 strip 语义以 exact_strip 开关区分
        passed = self._match(actual, expected, mode, negate, exact_strip=False)
        result = {
            "type": "json_output",
            "layer": 3,
            "step": a.get("step"),
            "path": path,
            "expected": expected,
            "actual": actual,
            "mode": mode,
            "pass": passed,
        }
        # 证据纪律（对齐 output_match 的 160 字符 snippet / file_content 与
        # api 侧的 [:200] 先例）：path 为空时 actual 是整棵解析文档、有 path
        # 时是任意 JSON 子树，而 cli_runner 侧 json 由完整 stdout 解析、上限
        # _RUN_JSON_PARSE_LIMIT 为 1MB——原样入结果会把最高 1MB 的 JSON 文本
        # 带进 report.json 与 judge 归因上下文。判定已基于完整值完成，仅对
        # 写入结果的 actual 截断（repr 后 200 字符 + truncated 标注）
        actual_repr = repr(actual)
        if len(actual_repr) > 200:
            result["actual"] = actual_repr[:200]
            result["actual_truncated"] = True
        return result
