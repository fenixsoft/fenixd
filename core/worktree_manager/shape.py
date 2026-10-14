"""shape.py — worktree 载体分支形状判定（verifier 族 / 实现族消歧）。

零包内依赖的叶模块（design D1 叶模块惯例，防循环导入）：lifecycle /
legacy_registry / pm_engine.engine 三处形状判定单源。

背景（实证事故 2026-10-14 dsh-plugins admin-global-1791999865）：spec 名自身
以 ``verify-`` 开头（如 ``verify-dsh-plugins-live``）时，其实现分支按
``fenix/<spec>-<ts>`` 命名为 ``fenix/verify-dsh-plugins-live-<ts>``——与
verifier 分支形状前缀（``fenix/verify-``）撞车。cleanup finally 段以裸
``startswith("fenix/verify-")`` 判形状，把该实现分支误判为 verifier 形状，
收尾只摘 ``:verifier`` 族锁 → 同键 ``:implementer`` 锁泄漏 → 后续每轮重派
``create()`` 即撞锁 early give-up（Failed to create worktree）→ 同因重派
循环 → spec 冻结。同型叠加缺陷：``_spec_from_branch`` 对该分支按验证语义
剥 ``verify-`` 回推出错 spec（``dsh-plugins-live``），cleanup finally 的
``wt_spec`` 锁键过滤同样匹配不上——两重机制独立致锁释放失效。

分层锚定（可靠度递减，先命中先返回）：
  1. ``spec_hint``（调用方上下文的真 spec 名，如锁键/keep_for_reuse 入参）：
     分支末段去时间戳得 ``front``，``front == hint`` 判实现族、
     ``front == "verify-<hint>"`` 判 verifier 族——与
     ``_impl_branch_owned_by_spec``（3f168f91d3af）实现语义全等判定同源；
  2. worktree 目录名前缀：create() 按 agent_type 定前缀（verifier →
     ``verify-``、其余 → ``impl-``），与 spec 名无关，**从无歧义**——
     ``impl-`` 判实现族、``verify-`` 判 verifier 族、``repair-``/``judge-``
     为不登记锁的载体（返回 None）；
  3. 分支自结构：验证语义剥 ``verify-`` 得 spec 锚后全等判别（锚不可得
     或分支非本框架命名时回落 4）；
  4. 历史前缀启发式：裸 ``startswith("fenix/verify-")``——对 verify- 开头
     spec 名的实现分支**不可解歧**（维持历史判定，调用方应提供锚 1/2）。
"""

from __future__ import annotations

_WT_NAME_FAMILY_PREFIXES = ("repair-", "judge-")


def branch_shape_is_verifier(
    branch: str | None, wt_name: str = "", spec_hint: str | None = None,
) -> bool | None:
    """判定载体分支形状：verifier 族 / 实现族（tri-state）。

    Args:
        branch: 分支名（``fenix/<spec>-<ts>`` / ``fenix/verify-<spec>-<ts>``）；
            可为 None/空（分支表缺失等场景）。
        wt_name: worktree 目录名（``impl-<spec>-<ts>`` / ``verify-<spec>-<ts>``），
            目录名前缀锚。
        spec_hint: 调用方上下文的真 spec 名（锁键 spec 段 / keep_for_reuse
            入参 / pm_engine 方法入参），结构全等判别的最高优先锚。

    Returns:
        True  = verifier 族形状；False = 实现族形状（implementer/fast-track/
        planner/code-fix 载体）；None = 形状完全不可辨（repair-/judge- 等
        不登记锁的载体、或双锚皆缺失且分支非本框架命名）——调用方按各自
        历史口径消费 None（cleanup finally 视作非 verifier、legacy_registry
        视作全摘/全不计族）。
    """
    text = branch or ""
    # 锚 1：spec_hint 结构全等（最高优先——上下文真 spec 名无歧义）
    if spec_hint and text.startswith("fenix/"):
        parts = text[len("fenix/"):].rsplit("-", 1)
        if len(parts) == 2 and parts[0] and parts[1].isdigit():
            front = parts[0]
            if front == spec_hint:
                return False
            if front == f"verify-{spec_hint}":
                return True
            # hint 与分支全不匹配：不强行选边，继续降锚（防脏 hint 误导）
    # 锚 2：目录名前缀（create() 按 agent_type 定前缀，与 spec 名无关）
    name = wt_name or ""
    if name.startswith("impl-"):
        return False
    if name.startswith("verify-"):
        return True
    if name.startswith(_WT_NAME_FAMILY_PREFIXES):
        return None  # repair-/judge- 载体：从不登记锁，形状不可辨
    # 锚 3：分支自结构（验证语义剥 verify- 得锚，全等判别）
    if text.startswith("fenix/"):
        parts = text[len("fenix/"):].rsplit("-", 1)
        if len(parts) == 2 and parts[0] and parts[1].isdigit():
            front = parts[0]
            spec = front[len("verify-"):] if front.startswith("verify-") else front
            if spec:
                if front == spec:
                    return False
                if front == f"verify-{spec}":
                    return True
            # spec 锚为空（spec 名恰为 "verify" 的退化形态）：歧义不可解
            return text.startswith("fenix/verify-")
        # 末段非纯数字时间戳：非本框架命名形态，按历史前缀启发式
        return text.startswith("fenix/verify-")
    # 双锚皆缺失：形状不可辨（目录名也非本框架载体词表）
    return None
