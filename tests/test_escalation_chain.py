"""add-escalation-chain-admin-arbiter：处置链核心测试。

1.1 防自环清单：_send_human_escalation_alert 与 freeze_for_human 全调用点
机械枚举并标注来源（框架信号 / 链成员产出）——框架信号经 family 咽喉入链
头，链成员产出走链终点直写（chain_context 携带，跳过链头重入）。新增调用
点绕过咽喉或链终点缺 chain_context 时本类红。

6.1 全 Scenario 覆盖见后续类（escalation-chain 与 chain-observability）。
"""

import glob
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.pm_engine.escalation_chain import (
    ChainQuotaStore,
    EscalationChain,
    load_chain_state,
    reset_chain,
)


def _scan_call_sites(pattern: str, directory: str = "core") -> list:
    """机械枚举 core/ 内 ``pattern`` 的属性调用点（跳过 def 定义行）。

    ``directory`` 可为目录（递归 glob）或单文件路径。返回
    ``[(file, 调用段文本)]``；调用段取调用点后 500 字符供子断言。
    """
    targets = (
        [directory] if directory.endswith(".py")
        else sorted(glob.glob(f"{directory}/**/*.py", recursive=True))
    )
    hits = []
    for fp in targets:
        src = open(fp, encoding="utf-8").read()
        for m in re.finditer(re.escape(pattern) + r"\(", src):
            if src[max(0, m.start() - 4):m.start()].rstrip().endswith("def"):
                continue  # 定义行
            hits.append((fp.replace("\\", "/"), src[m.end():m.end() + 500]))
    return hits


# 咽喉与链终点之外的真实调用点白名单（全部为框架信号——经 PMEngine 委托
# `_family` 咽喉进链头；新框架调用点出现于此清单外时本测试红，须人工确认
# 来源标注后收录）。
FRAMEWORK_ALERT_CALLERS = {
    "core/pm_engine/budget.py",             # impl_budget_exhausted 族
    "core/pm_engine/engine.py",             # legacy 降级熔断 verify_env_blocked
    "core/pm_engine/spec_integrity.py",     # spec_content_missing 族
    "core/pm_engine/verification/context.py",  # escalation_notifier 委托
}


class TestAntiSelfLoopInventory(unittest.TestCase):
    """1.1 升级咽喉调用点清单与防自环判定。"""

    def test_throat_is_single_entry(self):
        """告警咽喉单入口：除 family 本体与链终点外，无旁路落人工调用点。"""
        callers = {fp for fp, _seg in _scan_call_sites("_send_human_escalation_alert")}
        callers.discard("core/pm_engine/family.py")            # 咽喉本体
        callers.discard("core/pm_engine/escalation_chain.py")  # 链终点直写
        stray = callers - FRAMEWORK_ALERT_CALLERS
        assert not stray, (
            f"发现未收录的落人工告警调用点 {sorted(stray)}——"
            f"框架信号必须经 family 咽喉（链优先派发），"
            f"链成员产出必须走链终点（chain_context 直写）"
        )

    def test_chain_endpoint_alerts_carry_chain_context(self):
        """链成员产出的上升件 MUST 携带 chain_context（链终点直写不重入链头）。"""
        hits = _scan_call_sites("_send_human_escalation_alert",
                                "core/pm_engine/escalation_chain.py")
        assert hits, "链终点上升调用点零命中——扫描器坏了或链终点路径被移除"
        for fp, seg in hits:
            assert re.search(r"chain_context\s*=", seg), (
                f"{fp}: 链成员上升件缺 chain_context——咽喉会把它当框架信号"
                f"重新入链（同签名 dedup 兜底不死循环，但链痕迹丢失）"
            )

    def test_family_throat_chain_first(self):
        """family 咽喉链优先：chain_context 为空时 MUST 先调链派发再落盘。"""
        src = open("core/pm_engine/family.py", encoding="utf-8").read()
        m = re.search(r"def _send_human_escalation_alert", src)
        assert m, "family 咽喉定义缺失"
        body = src[m.end():m.end() + 4000]
        assert "chain_context is None" in body, "咽喉缺链头判定分叉"
        assert "submit_entry" in body, "咽喉缺链优先派发（框架信号绕链直落人工）"

    def test_freeze_hook_chain_first_with_fallback(self):
        """freeze 咽喉链优先 + 降级回落：先试链，链缺席回落 lane.submit_trigger。"""
        src = open("core/pm_engine/arbiter.py", encoding="utf-8").read()
        m = re.search(r"def install_freeze_hook", src)
        assert m, "install_freeze_hook 定义缺失"
        body = src[m.end():src.find("\ndef ", m.end())]
        assert "submit_entry" in body, "freeze 咽喉缺链优先派发"
        assert "submit_trigger" in body, (
            "freeze 咽喉缺降级回落——链缺席时冻结信号必须仍可进 Arbiter 既有路径"
        )

    def test_freeze_throat_signals_outside_default_blacklist(self):
        """freeze_for_human 全调用点 signal_type 不落在缺省黑名单内。"""
        found = set()
        for fp, seg in _scan_call_sites("freeze_for_human"):
            sm = re.search(r"signal_type\s*=\s*['\"]?([A-Za-z][\w-]*)", seg)
            if sm:
                found.add(sm.group(1))
        assert found, "freeze_for_human 机械枚举零命中——扫描器本身坏了"
        tmp = Path(tempfile.mkdtemp())
        try:
            chain = EscalationChain(tmp, MagicMock())  # 缺省配置（黑名单空）
            for sig in sorted(found):
                assert not chain.blacklisted(sig), (
                    f"冻结族 '{sig}' 落在缺省黑名单内——链头会拒收生产冻结信号"
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            reset_chain()


class TestChainQuotaStoreBasics(unittest.TestCase):
    """配额状态层基本读写（6.1 场景的底层前置）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def test_empty_state_shape(self):
        state = load_chain_state(self.tmp)
        assert state["version"] == 1
        assert state["signatures"] == {}
        assert state["in_flight"] == []
        assert "meta" in state

    def test_admin_attempt_counting(self):
        sig = "spec-a::verify_env_blocked"
        store = ChainQuotaStore(self.tmp)
        store.count_admin_attempt(sig)
        store.count_admin_attempt(sig)
        state = load_chain_state(self.tmp)
        assert state["signatures"][sig]["admin_attempts"] == 2
