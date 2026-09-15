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


def parse_tree(path: Path):
    """解析单个 .py 文件为 AST；读取/语法错误返回 None（扫描静默跳过）。"""
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


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
