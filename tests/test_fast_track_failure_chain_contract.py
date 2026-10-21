"""双车道终态失败分类链结构自检契约（code-review item c0a33f55ce27）。

背景：fast_track.py `_handle_fast_track_failure` 的四段终态分类
（provider 熔断保持原状 / [provider-transient] 延迟重派 /
MODEL_CHAIN_UNAVAILABLE_MARKER 保持原状 / _retry_count 递增与 max_r
封顶冻结转人工）与 queue.py `_run_agent_worker` 内
agent_type == "implementer" 的失败处置链（死亡 run 豁免之后）逐段
同构、纯手工双维护（两侧 MUST 同步注释，code-review item
0caca76e37b1）。fast-track 侧历史上曾三次缺失、事后补齐对齐
（item 498a7c7432f1、867125061b61、6e6259821f64）。

本契约把「MUST 同步」人工纪律降为机器校验（只读比对，不改运行时行为）：

1. 指纹/标记常量单一权威源：两侧模块引用的
   PROVIDER_CIRCUIT_ERROR_MARKER / MODEL_CHAIN_UNAVAILABLE_MARKER
   必须与 core.agent_runner.provider_circuit 的定义是同一对象——
   防任一侧回退成裸字符串/复制文案，上游措辞调整时消费点静默失配。
2. 终态分类段数与分支序一致：AST 只读解析两侧函数，按源码序提取
   「<标记> in <错误归因>」型 If 守卫，断言两侧均为同三段、同序
   （熔断 → [provider-transient] → 模型链）。任一车道新增/漏配终态段
   即在此显式失败，逼迫同步另一侧。
3. 分段处置动作同构：transient 段的延迟重派排程
   （_schedule_transient_recovery）、else 段的重试记账
   （bump_counters 写 "_retry_count"）、封顶判定（retries >= max_r）、
   冻结转人工（freeze_for_human）、复位重派（_enqueue_front）与
   各段 error 落盘（update_spec）、封顶阈值读取（_max_retries）
   两侧必须同时在场。

有意不做的事：不断言两侧日志文案/返回形态等实现细节；fast-track 侧
无同因 streak 熔断属 design D3 作用域边界（见 fast_track 失败链内
注释），不是漂移，不纳入契约。对照定位一律用方法名/分支语义，
勿写裸行号（行号会漂移，两侧文件自定约定同源）。
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.pm_engine.dispatch.fast_track as fast_track_mod
import core.pm_engine.dispatch.queue as queue_mod
from core.agent_runner import provider_circuit

REPO_ROOT = Path(__file__).resolve().parent.parent
FAST_TRACK_FILE = REPO_ROOT / "core" / "pm_engine" / "dispatch" / "fast_track.py"
QUEUE_FILE = REPO_ROOT / "core" / "pm_engine" / "dispatch" / "queue.py"

# 两侧共享的指纹/标记常量名（单一权威源：core.agent_runner.provider_circuit）
SHARED_MARKER_NAMES = (
    "PROVIDER_CIRCUIT_ERROR_MARKER",
    "MODEL_CHAIN_UNAVAILABLE_MARKER",
)
# provider 瞬断标记：两侧目前同为裸字符串字面量（未收敛为共享常量），
# 本契约以字面值相等兜底防漂移。
TRANSIENT_MARKER_LITERAL = "[provider-transient]"
# 终态分类段期望序（与两侧 MUST 同步注释一致）：熔断 → transient → 模型链。
EXPECTED_TERMINAL_ORDER = (
    "PROVIDER_CIRCUIT_ERROR_MARKER",
    TRANSIENT_MARKER_LITERAL,
    "MODEL_CHAIN_UNAVAILABLE_MARKER",
)
# 终态分类链上的处置动作两侧必须同时在场（按方法/属性名匹配，不匹配文案）。
REQUIRED_SEGMENT_ACTIONS = (
    "update_spec",  # 各终态段 error 落盘（dashboard/admin 可见）
    "_schedule_transient_recovery",  # transient 段：延迟重派排程
    "_max_retries",  # else 段：封顶阈值统一读取器
    "bump_counters",  # else 段：_retry_count 锁内原子递增
    "freeze_for_human",  # else 段：retries 达 max_r 冻结转人工
    "_enqueue_front",  # else 段：复位 ready 后显式重入队
)


def _iter_preorder(node):
    """先序 DFS（ast.walk 是 BFS 不保源码序；此处自实现保序遍历）。"""
    for child in ast.iter_child_nodes(node):
        yield child
        yield from _iter_preorder(child)


def _find_function(tree, name):
    """在模块 AST 中按方法名定位函数/方法定义（对照定位用名字不用行号）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"AST 中找不到函数 {name}")


def _marker_guard_key(node):
    """识别「<标记> in <错误归因>」型比较，返回标记键；非此形态返回 None。

    标记键只认三类：两个共享常量名 + transient 裸字面量。其余比较一律
    忽略，避免把两侧无关的子串匹配卷进契约断言。
    """
    if not (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.In)
    ):
        return None
    left = node.left
    if isinstance(left, ast.Name) and left.id in SHARED_MARKER_NAMES:
        return left.id
    if (
        isinstance(left, ast.Constant)
        and isinstance(left.value, str)
        and left.value == TRANSIENT_MARKER_LITERAL
    ):
        return TRANSIENT_MARKER_LITERAL
    return None


def _terminal_guard_order(scope_node):
    """按源码序收集作用域内 If 守卫引用的终态标记键序列。"""
    keys = []
    for node in _iter_preorder(scope_node):
        if not isinstance(node, ast.If):
            continue
        for sub in _iter_preorder(node.test):
            key = _marker_guard_key(sub)
            if key:
                keys.append(key)
    return keys


def _implementer_chain_node(queue_worker_func):
    """定位 `_run_agent_worker` 内 agent_type == "implementer" 分支节点。

    implementer 失败处置链嵌在该分支体内（try/except 深处），按分支
    语义定位后在其子树内做结构提取——不依赖任何行号。
    """
    for node in _iter_preorder(queue_worker_func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.left, ast.Name)
            and test.left.id == "agent_type"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "implementer"
        ):
            return node
    raise AssertionError(
        "queue.py `_run_agent_worker` 内找不到 agent_type == \"implementer\" 分支"
    )


def _call_names(scope_node):
    """收集作用域内全部被调用名（Attribute 取 attr、Name 取 id）。"""
    names = set()
    for sub in _iter_preorder(scope_node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def _has_dict_key(scope_node, key):
    """作用域内是否存在以给定字符串常量为键的 dict 字面量（重试记账键）。"""
    for sub in _iter_preorder(scope_node):
        if isinstance(sub, ast.Dict):
            for k in sub.keys:
                if isinstance(k, ast.Constant) and k.value == key:
                    return True
    return False


def _has_retry_cap_test(scope_node):
    """识别「retries >= max_r」封顶判定 If 守卫（两侧同型）。"""
    for node in _iter_preorder(scope_node):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.GtE)
            and isinstance(test.left, ast.Name)
            and test.left.id == "retries"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Name)
            and test.comparators[0].id == "max_r"
        ):
            return True
    return False


def _load_sides():
    """解析两侧源码并定位各自比对作用域（fast-track 全函数 / queue 分支子树）。"""
    ft_func = _find_function(
        ast.parse(FAST_TRACK_FILE.read_text(encoding="utf-8")),
        "_handle_fast_track_failure",
    )
    q_worker = _find_function(
        ast.parse(QUEUE_FILE.read_text(encoding="utf-8")),
        "_run_agent_worker",
    )
    return ft_func, _implementer_chain_node(q_worker)


def test_marker_constants_share_single_source_of_truth():
    """两侧模块引用的指纹/标记常量必须是 provider_circuit 权威定义本身。"""
    for name in SHARED_MARKER_NAMES:
        authoritative = getattr(provider_circuit, name)
        assert getattr(fast_track_mod, name) is authoritative, (
            f"fast_track.py 顶层的 {name} 未引用 provider_circuit 权威常量"
            "（回退裸字符串会在上游文案调整时静默失配）"
        )
        assert getattr(queue_mod, name) is authoritative, (
            f"queue.py 顶层的 {name} 未引用 provider_circuit 权威常量"
            "（回退裸字符串会在上游文案调整时静默失配）"
        )


def test_terminal_classification_segment_count_and_order_aligned():
    """终态分类段数与分支序两侧一致：熔断 → [provider-transient] → 模型链。"""
    ft_func, q_chain = _load_sides()
    ft_keys = _terminal_guard_order(ft_func)
    q_keys = _terminal_guard_order(q_chain)
    expected = list(EXPECTED_TERMINAL_ORDER)
    assert ft_keys == expected, (
        f"fast-track 车道 `_handle_fast_track_failure` 终态分类段漂移："
        f"实测 {ft_keys}，期望 {expected}。"
        "与 queue.py implementer 失败处置链 MUST 同步"
        "（code-review item 0caca76e37b1），禁止只改 full 车道一侧。"
    )
    assert q_keys == expected, (
        f"full 车道 `_run_agent_worker` implementer 失败处置链终态分类段漂移："
        f"实测 {q_keys}，期望 {expected}。"
        "与 fast_track.py `_handle_fast_track_failure` MUST 同步，"
        "禁止只改 fast-track 车道一侧。"
    )


def test_terminal_segment_actions_structurally_aligned():
    """分段处置动作两侧同构：transient 排程 / 重试记账 / 封顶冻结 / 复位重派。"""
    ft_func, q_chain = _load_sides()
    ft_calls = _call_names(ft_func)
    q_calls = _call_names(q_chain)
    for action in REQUIRED_SEGMENT_ACTIONS:
        assert action in ft_calls, (
            f"fast-track 车道失败分类链缺少处置动作 {action}()——"
            "与 full 车道失配，MUST 同步后再改分支语义"
        )
        assert action in q_calls, (
            f"full 车道 implementer 失败处置链缺少处置动作 {action}()——"
            "与 fast-track 车道失配，MUST 同步后再改分支语义"
        )
    # else 段重试记账键与封顶判定两侧同型
    for side, scope in (("fast-track", ft_func), ("queue implementer", q_chain)):
        assert _has_dict_key(scope, "_retry_count"), (
            f"{side} 失败分类链缺少 _retry_count 记账（bump_counters 写入键）"
        )
        assert _has_retry_cap_test(scope), (
            f"{side} 失败分类链缺少 retries >= max_r 封顶判定"
        )
