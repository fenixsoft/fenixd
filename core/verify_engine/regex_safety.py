"""regex_safety.py — 正则回溯安全共享层（无内部依赖）。

TimeoutRegex/compile_regex（api/cli 断言侧）与嵌套量词高危形态预检
（cli 侧）的原单点实现下沉至此（code-review item ee72d324ea15）：
scenarios.py 的 expect_network URL 匹配也要同一防护口径，而 scenarios
是被 api_assertions/cli_assertions/assertions 反向依赖的被依赖侧（它们
只从 scenarios 取词表常量）——实现若留在 api_assertions，scenarios 反向
import 即成环。本模块 MUST 保持零内部 import，三方（scenarios/api/cli）
共用同一防护实现，防口径漂移。

对外共用契约（code-review item 93fed01dcaa0）：``regex_lib`` /
``TimeoutRegex`` / ``compile_regex`` / ``has_nested_quantifier`` 是本模块
供 scenarios/api/cli 三方跨模块 import 的公共 API，命名不带下划线私有
前缀、受「对外契约」语义保护不得随意改名；旧下划线名（``_regex_lib``/
``_TimeoutRegex``/``_compile_regex``/``_has_nested_quantifier``）保留为
同义别名，仅供既有消费方 import 平滑兼容，新代码一律用公共名。
"""

import re

# regex 第三方库可选增强：其引擎对嵌套量词等灾难回溯形态自带线性化保护，
# 且支持 timeout（超时抛 TimeoutError）。场景正则由 planner 生成（有幻觉
# 正则原语前科），嵌套量词类病态模式对 64KB 级 body/事件文本 search 可指数
# 回溯长时间阻塞验证事件循环；库缺失时回退 stdlib re（行为同无防护版）。
try:
    import regex as regex_lib
except ImportError:  # pragma: no cover - 环境相关分支
    regex_lib = None

# 旧下划线名别名：保住既有消费方（scenarios/api_assertions）import 兼容
# （code-review item 93fed01dcaa0），新代码一律用公共名 regex_lib
_regex_lib = regex_lib

# 单次正则匹配的墙上时钟上限（秒）：合法断言正则对 64KB 文本远低于此值
_REGEX_MATCH_TIMEOUT_SECONDS = 1.0


class TimeoutRegexError(re.error):
    """regex 库匹配超时（疑似灾难性回溯）的定向异常。

    继承 re.error 以保住调用方既有 ``except re.error`` 捕获面（超时沿
    原异常面传播、run() 归一为带定向归因的断言失败），同时让「regex
    库引擎侧失败」在类型层可判别——调用点无须再依赖文案区分超时与
    真正的非法正则。除超时外，re/regex 合法性判定的罕见分歧（预检用
    stdlib re 放行、regex 库判定非法）也从 search 路径以此类型定向
    抛出，保住「非法正则」归因不漏成笼统「断言执行异常」；常规非法
    正则仍在 compile_regex 预检期返回、不以此类型抛出。
    """


class TimeoutRegex:
    """re.Pattern 的回溯安全包装：search 走 regex 库（带 timeout）防阻塞。

    对外只暴露与 re.Pattern 同形的 ``search(text) -> bool``，四处内容断言
    调用点无须感知背后是 regex 库还是 stdlib 回退。
    """

    def __init__(self, source: str, compiled: re.Pattern):
        self._source = source
        self._compiled = compiled
        # regex 库可用时按同 pattern 预编译一次，search 复用编译产物——否则
        # 每次匹配（sse_event_matches 逐事件各调一次）都经模块级 search 重新
        # 解析编译同一 pattern（code-review item bbe2c304be8e）。预编译意外
        # 失败（regex 与 re 语法判定的罕见分歧）时回退模块级 search，timeout
        # 防护语义不变
        self._regex_compiled = None
        if regex_lib is not None:
            try:
                self._regex_compiled = regex_lib.compile(source)
            except Exception:
                self._regex_compiled = None

    def search(self, text: str) -> bool:
        if regex_lib is not None:
            compiled = self._regex_compiled
            try:
                if compiled is not None:
                    return (
                        compiled.search(
                            text, timeout=_REGEX_MATCH_TIMEOUT_SECONDS
                        )
                        is not None
                    )
                return (
                    regex_lib.search(
                        self._source, text, timeout=_REGEX_MATCH_TIMEOUT_SECONDS
                    )
                    is not None
                )
            except TimeoutError:
                # 超时按确定性配置失败 fail-closed：沿 TimeoutRegexError（
                # re.error 子类）传播，调用点既有 except re.error 捕获面不变
                # （run() 归一为带定向归因的断言失败），防 judge 把场景正则
                # 缺陷误归因为产品缺陷
                raise TimeoutRegexError(
                    f"正则匹配超时（>{_REGEX_MATCH_TIMEOUT_SECONDS}s，"
                    f"疑似灾难性回溯）: {self._source!r}"
                ) from None
            except regex_lib.error as e:
                # re/regex 合法性判定的罕见分歧（compile_regex 用 stdlib re
                # 预检放行、regex 库判定同一模式非法）走回退 search 时抛出的
                # regex.error 不是 re.error 子类，无此层会漏进 run() 的
                # except Exception 被归因为笼统「断言执行异常」；转抛同族
                # 定向失败保住「非法正则」归因（code-review item
                # d41d3b5063e2），不吞 TimeoutRegexError 的超时语义
                raise TimeoutRegexError(
                    f"非法正则（regex 库判定该模式非法，"
                    f"与 stdlib re 预检判定分歧）: {self._source!r}: {e}"
                ) from None
        return self._compiled.search(text) is not None


# 旧下划线名别名：既有消费方（api_assertions re-export）import 兼容
# （code-review item 93fed01dcaa0），新代码一律用公共名 TimeoutRegex
_TimeoutRegex = TimeoutRegex


def compile_regex(pattern: str) -> tuple[TimeoutRegex | None, str | None]:
    """进匹配前编译预检：非法正则是确定性配置错误。

    此前各 regex 分支 ``except re.error: passed = False`` 静默吞错，结果与
    「内容确实不匹配」无法区分，judge 会把 planner 写错的正则误归因为产品
    缺陷；统一预检后非法时返回带「非法正则」error 的确定性失败（口径对齐
    web 侧 _assert_text_match）。返回 (compiled, None)；非法时 (None, 文案)。
    预检仍用 stdlib re.compile（保持非法判定口径），编译产物包一层
    TimeoutRegex：regex 库可用时匹配带 timeout，防病态正则长时间阻塞
    （见 TimeoutRegex）。
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return None, f"非法正则: {e}"
    return TimeoutRegex(pattern, compiled), None


# 旧下划线名别名：既有消费方（scenarios/api_assertions/cli_assertions）
# import 兼容（code-review item 93fed01dcaa0），新代码一律用公共名
# compile_regex
_compile_regex = compile_regex


def _regex_brace_body(pattern: str, i: int) -> "str | None":
    """取 pattern[i] 起始的 ``{...}`` 量词体；无闭合 ``}`` 返回 None。"""
    j = pattern.find("}", i + 1)
    return pattern[i + 1 : j] if j > i else None


def has_nested_quantifier(pattern: str) -> bool:
    """高危正则预检：检测「组内变长量词 × 组整体无上界量词」的嵌套形态
    （灾难性回溯的典型结构特征，如 ``(.+)*`` / ``(\\d+)+`` / ``(a{1,2})+``）。

    保守取舍（宁少拦不误拦）：
      - 仅当组闭合紧跟无上界量词（``*``/``+``/``{m,}``）且组内出现变长
        量词（``*``/``+``/``{m,n}``；嵌套子组的变长标志随 ``)`` 闭合向
        父组传播，``((a+))+`` 与 ``(a+)+`` 等价同拦）才判高危——外层有界
        量词（``?``/``{m}``）
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
                if group_has_variable_quant:
                    # 变长标志向父组传播：((a+))+ 与 (a+)+ 回溯语义等价，同属
                    # 灾难性回溯典型结构，子组标志不上提会让外层无上界量词
                    # 判定漏拦（弹栈后栈顶即父组）
                    group_has_variable_quant[-1] |= had
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


# 旧下划线名别名：既有消费方（scenarios/cli_assertions）import 兼容
# （code-review item 93fed01dcaa0），新代码一律用公共名
# has_nested_quantifier
_has_nested_quantifier = has_nested_quantifier
