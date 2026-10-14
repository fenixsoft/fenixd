"""
fenix_guards.py — 控制平面静默失效防线的静态守卫共用工具。

add-control-plane-silent-failure-guards 防线一（callsite-arity-guard）与
防线二（test-double-fidelity）共用同一套「core/ 方法签名索引 → 唯一签名
候选 seam」构造逻辑。本模块**不含任何类定义**，因此不会被防线二自身的
替身保真扫描误判为测试替身。

规则（design D1/D2，保守起步）：
- 候选 seam = 方法名在 core/ 中**唯一签名**（同名多签名 → 排除）、签名
  无 *args/**kwargs、非 dunder、不在宽泛名黑名单。
- 实例方法/类方法剥离首个 self/cls；staticmethod 不剥离。
- vendored 代码（core/dashboard/static/node_modules/ 下 katex parse_tfm.py
  等第三方构建脚本）不参与扫描——它们是依赖产物，不是本仓库的生产调用点。
"""

import ast
from pathlib import Path

# 第三方 vendored 目录标记：跳过（katex 的 parse_tfm.py 等构建脚本混在
# node_modules 里，AST 解析合法但其调用点不属于本仓库生产代码）。
VENDORED_DIR_MARKERS = ("node_modules",)


def is_vendored(path: Path) -> bool:
    return any(m in path.as_posix() for m in VENDORED_DIR_MARKERS)


def repo_relative(path: Path, root: Path) -> str:
    """仓库相对路径（白名单键与违规报告的基准）。

    文件在仓库内 → `core/admin_monitor.py` 形态；仓库外（单元测试注入的
    临时样例）→ 返回绝对路径形态，白名单键按绝对路径即可匹配。
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# AST 解析缓存：(绝对路径, mtime_ns, size) → tree | None。同一守卫进程内
# 多趟扫描（签名索引 → seam 参数名收集 → 调用点扫描）对同一批文件各
# ast.parse 一遍是全守卫套件的主要耗时（约 3/4），而各趟只读遍历 AST、
# 从不改动，共享同一棵树判定结果逐位一致。键带 mtime_ns/size：同进程内
# 文件被改写（如单元测试向临时样例写入）不会命中陈旧缓存；解析失败的
# None 也一并缓存，避免坏文件被反复读。进程级缓存随 pytest 进程退出释放。
_PARSE_CACHE: dict = {}


def parse_tree(path: Path):
    """解析单个 .py 文件为 AST；读取/语法错误返回 None（扫描静默跳过）。"""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _PARSE_CACHE:
        return _PARSE_CACHE[key]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        tree = None
    _PARSE_CACHE[key] = tree
    return tree


def method_signature(fn: ast.FunctionDef):
    """提取方法签名的判定四元组 (必填位参数, 是否含 *args, 是否含 **kwargs)。

    self/cls 剥离规则：staticmethod 首参不剥离（装饰器判定）；实例方法/
    类方法剥离首个参数。defaults 作用于 (posonlyargs + args) 的尾部，
    `max(0, pos - len(defaults))` 即必填位参数个数。
    """
    is_static = any(
        (isinstance(d, ast.Name) and d.id == "staticmethod")
        or (isinstance(d, ast.Attribute) and d.attr == "staticmethod")
        for d in fn.decorator_list
    )
    pos = len(fn.args.posonlyargs) + len(fn.args.args)
    req = max(0, pos - len(fn.args.defaults))
    if not is_static:
        req = max(0, req - 1)
    return (req, fn.args.vararg is not None, fn.args.kwarg is not None, is_static)


def iter_class_methods(tree):
    """遍历 AST 中所有类及其直接子级方法定义。

    产出 (class_node, method_node)。仅取类体直接子级（不深入嵌套类/函数内
    定义的类——方法的直接定义点在类体中）。
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            yield node, item


def index_method_signatures(files):
    """扫描文件集合，构建 {方法名: [(必填, vararg, kwarg), ...]} 索引。"""
    sigs: dict = {}
    for f in files:
        if is_vendored(f):
            continue
        tree = parse_tree(f)
        if tree is None:
            continue
        for _cls, item in iter_class_methods(tree):
            req, va, kw, _is_static = method_signature(item)
            sigs.setdefault(item.name, []).append((req, va, kw))
    return sigs


def unique_seams(sig_index: dict, blacklist=frozenset()) -> dict:
    """从方法签名索引构造候选 seam：唯一签名 + 无变长参数 + 非 dunder
    + 不在宽泛名黑名单。返回 {方法名: (必填, vararg, kwarg)}。

    同名多签名（不同类同名但签名不同）→ 排除，避免跨类同名误报。
    """
    seams: dict = {}
    for name, sigs in sig_index.items():
        distinct = set(sigs)
        if len(distinct) != 1:
            continue
        req, va, kw = next(iter(distinct))
        if va or kw:
            continue
        if name.startswith("__") and name.endswith("__"):
            continue
        if name in blacklist:
            continue
        seams[name] = (req, va, kw)
    return seams


def _enclosing_class_name(tree, call: ast.Call) -> str:
    """返回 call 节点所属的类名；模块级调用返回 "module"。

    取「包含该调用行号且跨度最小」的类（最内层）。位置跨度用
    lineno/end_lineno 判定，避免依赖 ast.walk 的遍历顺序。
    """
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= call.lineno <= end:
            if best is None or (end - node.lineno) < (best[1] - best[0]):
                best = (node.lineno, end, node.name)
    return best[2] if best else "module"


def seam_param_names(prod_files, seams: dict) -> dict:
    """收集各候选 seam 的具名位参集合（关键字补足判定用）。

    {方法名: {参数名, ...}}——实例/类方法剔除首个 self/cls，staticmethod
    保留全部。
    """
    param_names: dict = {}
    for f in prod_files:
        if is_vendored(f):
            continue
        tree = parse_tree(f)
        if tree is None:
            continue
        for _cls, item in iter_class_methods(tree):
            if item.name not in seams:
                continue
            _req, _va, _kw, is_static = method_signature(item)
            names = [a.arg for a in item.args.posonlyargs] + [a.arg for a in item.args.args]
            if not is_static and names:
                names = names[1:]
            param_names.setdefault(item.name, set()).update(names)
    return param_names


# ── 时间原语守卫（add-timelib-consolidation-layer 2.1）────────────────────
# 时间产出/解析必须走 core/timelib.py 唯一原语（分层约定：存储/计算=aware
# UTC，渲染边界=本地；naive 唯一策略=按本地解读）。本扫描器按 ast.Attribute
# 链判定禁用模式，供 tests/test_timelib_guard.py 棘轮消费。

# timelib 自身全豁免（spec Scenario「timelib 自身豁免」）：它就是唯一原语，
# 内部实现必然使用 fromisoformat 等底层 API。
TIME_GUARD_EXEMPT_FILES = frozenset({"core/timelib.py"})

# datetime 模块的缺省接收者别名：调用链根名命中即判定
# （`datetime.datetime.now()` 链式接收者根名仍为 datetime，同样命中）。
# 其余别名（`from datetime import datetime as _dt` 的 `_dt` 等）按文件
# import 绑定动态收集（_datetime_aliases），不依赖静态罗列。
DATETIME_ROOT_ALIASES = frozenset({"datetime", "dt"})

# 模式名 → 人读描述（违规报告用）。
TIME_PATTERN_LABELS = {
    "now-zero-arg": "零参 datetime.now()（naive 本地产出）",
    "utcnow": "datetime.utcnow()（已废弃且产出 naive）",
    "fromtimestamp-no-tz": "零/单参 fromtimestamp()（未显式指定 tz）",
    "utcfromtimestamp": "datetime.utcfromtimestamp()（已废弃）",
    "fromisoformat": "timelib 之外的 fromisoformat()（解析未收拢）",
}


def _datetime_aliases(tree) -> frozenset:
    """收集文件内 `import datetime` / `from datetime import X [as Y]` 的
    绑定名（ast.walk 全作用域，含函数内局部 import），并上缺省别名集。
    """
    names = set(DATETIME_ROOT_ALIASES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "datetime":
                    names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            for a in node.names:
                names.add(a.asname or a.name)
    return frozenset(names)


def _datetime_root_name(call: ast.Call, aliases) -> str:
    """调用接收者链的根名；根名不在 datetime 别名集时返回空串。

    参考 arity-guard 的接收者表达式处理：`datetime.now` / `dt.now` /
    `datetime.datetime.now` 命中；`self.now` / `page.now` 等无关同名不误报。
    """
    node = call.func.value
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name) and node.id in aliases:
        return node.id
    return ""


def _time_pattern(call: ast.Call):
    """判定单个调用的时间禁用模式名；不在禁用集合返回 None。"""
    attr = call.func.attr
    if attr == "now":
        # 只禁零参（naive 产出）；now(timezone.utc) 是合法 aware 写法
        if not call.args and not call.keywords:
            return "now-zero-arg"
        return None
    if attr == "utcnow":
        return "utcnow"
    if attr == "utcfromtimestamp":
        return "utcfromtimestamp"
    if attr == "fromtimestamp":
        # 显式指定 tz（关键字或第二个位参）不算裸调用
        if any(k.arg == "tz" for k in call.keywords) or len(call.args) >= 2:
            return None
        return "fromtimestamp-no-tz"
    if attr == "fromisoformat":
        return "fromisoformat"
    return None


def scan_time_primitives(files, root, whitelist=()):
    """扫描时间禁用模式，返回 (violations, violation_keys)。

    violations: `文件:行 接收者.方法 描述` 列表（含行号，报告/修复定位用）。
    violation_keys: 命中的 `(仓库相对路径, 模式名)` 集合——白名单键与之
    对账：白名单键无任何命中即为僵尸条目（design D3，报失败不报警告）。
    whitelist: `(相对路径, 模式名)` 列表，语义键不含行号（arity-guard
    2026-09-15 行漂移回归的教训）；豁免粒度=文件×模式，同文件同模式全部
    现存违例一并豁免，迁移消除后整组收缩该键。
    """
    violations = []
    violation_keys = set()
    for f in files:
        if is_vendored(f):
            continue
        rel = repo_relative(f, root)
        if rel in TIME_GUARD_EXEMPT_FILES:
            continue
        tree = parse_tree(f)
        if tree is None:
            continue
        aliases = _datetime_aliases(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                continue
            if not _datetime_root_name(node, aliases):
                continue
            pattern = _time_pattern(node)
            if pattern is None:
                continue
            violation_keys.add((rel, pattern))
            if (rel, pattern) in whitelist:
                continue
            violations.append(
                f"{rel}:{node.lineno} {ast.unparse(node.func)} "
                f"{TIME_PATTERN_LABELS[pattern]}")
    violations.sort()
    return violations, violation_keys
