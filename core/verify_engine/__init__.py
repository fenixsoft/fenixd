"""
verify_engine — Fenix 验证引擎

将验证拆为两层三阶段：
  阶段1（Planner Agent / LLM）：读取SPEC → 生成结构化测试场景
  阶段2（本引擎 / Python）：并行Playwright → DOM断言 → 截图对比
  阶段3（Planner Agent / LLM）：分析JSON报告 → 通过/发现Bug

阶段2是纯确定性代码，零LLM参与。
"""

from .engine import VerifyEngine
from .scenarios import TestScenario, TestStep, Assertion

__all__ = ["VerifyEngine", "TestScenario", "TestStep", "Assertion"]
