"""
runner.py — 验证引擎 Runner 接口与按 kind 注册表

调度器不得含 per-kind 执行分支（design D1，见 spec/changes/
add-verify-multi-kind-runner）：引擎只按 ``scenario.kind`` 查注册表分派
``validate`` / ``setup`` / ``execute`` / ``teardown`` / ``probe_env``，
拓扑排序/并行/进度/报告路径不得出现 ``if kind == ...`` 之类的执行分支。

新增第四种 kind 仅需新建 Runner 模块（继承 VerifyRunner 并注册），引擎调度
路径零改动。

各 Runner 契约：
  - ``kind``：场景 kind 标识（web/cli/api），同时是注册表键。
  - ``validate(scenario)``：本 kind 的场景验收（action/断言类型/必填字段），
    返回错误列表（空列表=合法）。验收失败不启动任何 Runner、不执行场景。
  - ``setup()``：本轮一次性准备（lazy——引擎仅对场景集中实际出现的 kind
    调用）。如 WebRunner 启动浏览器；纯 CLI/API 轮次不产生 Playwright 依赖。
  - ``execute(scenario)``：执行单个场景，返回统一场景结果 dict
    （status/step_results/assertion_results/screenshots/visual_results…）。
  - ``teardown()``：本轮收尾释放资源。
  - ``probe_env(candidates)``：环境探针（整轮一次，首个候选触达即 memoize）。
    返回 ``{"healthy": bool, "detail": str}``；失联时引擎将候选场景批量降级
    blocked-env。CLI 第 1 版不做降级探针。
"""

from typing import Optional


class _NullLogger:
    """空日志器，当未提供logger时的默认实现。"""

    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class VerifyRunner:
    """Runner 抽象基类：接口即约定，子类必须实现全部方法。

    引擎持有 Runner 时只依赖本类声明的契约；各 Runner 内部可持有
    web/api/cli 专属资源（浏览器实例 / httpx client / subprocess 语义）。
    """

    kind: str = ""

    def __init__(
        self,
        spec_name: str,
        project_root=None,
        logger=None,
        config: Optional[dict] = None,
        scenario_root=None,
    ):
        self.spec_name = spec_name
        self.project_root = project_root
        self.logger = logger or _NullLogger()
        self.config = config or {}
        # 场景执行根：worktree 轮传入 serving worktree 根，CLI 步骤
        # 缺省 cwd 以此为准；None 时回退 project_root（无 worktree 轮）。
        self.scenario_root = scenario_root

    # ── 场景验收 ───────────────────────────────────────────────

    def validate(self, scenario) -> list[str]:
        """校验本 kind 场景定义的合法性，返回错误列表（空列表=合法）。

        错误消息必须带「支持: …」词表速查（spec multi-kind-planning-guidance：
        验收错误可指导 planner 修复，plan 侧无需查询源码即可修正）。
        """
        return []

    # ── 生命周期 ───────────────────────────────────────────────

    async def setup(self):
        """本轮一次性准备（lazy：仅对实际出现的 kind 调用）。"""

    async def teardown(self):
        """本轮收尾释放资源。"""

    # ── 场景执行 ───────────────────────────────────────────────

    async def execute(self, scenario) -> dict:
        """执行单个场景，返回统一场景结果 dict。

        返回结构必须含 ``scenario_id`` / ``status`` / ``step_results`` /
        ``assertion_results``（裁决链只依赖这两者的 pass/layer 字段），
        ``screenshots`` / ``visual_results`` 恒为列表（CLI/API 恒为空）。
        ``step_results`` 每个条目必含布尔 ``success`` 键：新增返回点须显式
        写布尔 success，缺键会被 determine_scenario_status 按上游畸形判
        fail 兜底。
        """
        raise NotImplementedError

    # ── 环境探针（环境门委托）──────────────────────────────────

    async def probe_env(self, candidates: list[dict]) -> dict:
        """环境健全性探针（整轮一次），供引擎后置分类降级 blocked-env。

        Args:
            candidates: 该 Runner 名下被判为降级候选的场景结果列表。

        Returns:
            {"healthy": bool, "detail": str}；无法完成探测时保守判健康
            （避免误降级真缺陷）。
        """
        return {"healthy": True, "detail": ""}


# ── 场景状态判定（跨 kind 共用，design D3）──────────────────────────
# 三套词表共用分层语义：任何步骤失败=fail；第 1-3 层断言失败=fail（一定是
# Bug）；仅第 4 层断言失败=warning；视觉差异（web）超阈值=warning。


def determine_scenario_status(
    step_results: list,
    assertion_results: list,
    visual_results: list = None,
) -> str:
    """判定场景整体状态（对三种 kind 一致的规则）。

    - 任何步骤失败 → "fail"
    - 任何第1-3层断言失败 → "fail"
    - 仅第4层断言失败 → "warning"
    - 视觉差异超阈值 → "warning"
    - 全部通过 → "pass"

    失败断言的 layer 缺失或越 1-4 界（上游畸形结果，如未知断言类型
    回退 layer=0）时按 fail 兜底，保守判失败，避免静默放行为 pass。
    步骤结果缺 ``success`` 键（上游畸形结果）同理按 fail 兜底，取向一致。
    步骤/断言混入非 dict 条目（上游畸形）亦按 fail 兜底，防御口径与
    env_gate._failed_wait_errors 的 isinstance 逐条防御对齐。视觉条目混入
    非 dict（上游畸形）则按 warning 兜底（视觉层最高档），同样避免畸形
    条目被静默放行为 pass。
    """
    # 正常路径不受影响：各 Runner 步骤执行器（browser/api/cli）的所有
    # 返回点均显式写布尔 ``success``；缺键只剩上游畸形一种来源。
    if any(not isinstance(s, dict) or not s.get("success", False) for s in step_results):
        return "fail"

    has_layer_1_3_fail = False
    has_layer_4_fail = False
    for a in assertion_results:
        if not isinstance(a, dict):
            # 非 dict 条目（上游畸形）与 layer 缺失同向，保守按 fail 兜底。
            has_layer_1_3_fail = True
            continue
        if a.get("pass", False):
            continue
        layer = a.get("layer", 0)
        if 1 <= layer <= 3:
            has_layer_1_3_fail = True
        elif layer == 4:
            has_layer_4_fail = True
        else:
            # 层缺失/越界（含未知类型回退的 layer=0）→ 保守按 fail 兜底。
            has_layer_1_3_fail = True

    if has_layer_1_3_fail:
        return "fail"

    visual_results = visual_results or []
    # 非 dict 视觉条目（上游畸形）→ 保守按 warning 兜底（视觉层最高档，
    # 差异≠失败），与步骤/断言的非 dict 防御取向一致，避免被静默放行为
    # pass；此判置于三处 status 读取之前，使后续 v.get 只接触 dict 条目。
    if any(not isinstance(v, dict) for v in visual_results):
        return "warning"
    # 视觉基线防污染（add-verdict-credibility-gate / D5）：基线被拒固化
    # （白屏/低对比度）→ 本轮按环境存疑处理（warning），不产生像素比对结论。
    # 后续轮次截图干净时正常建立基线后，视觉断言才恢复常态判定。
    if any(v.get("status") == "baseline_rejected" for v in visual_results):
        return "warning"
    # baseline_deferred（fix-visual-baseline-settle D4）：基线固化前置条件
    # 未满足（步骤/断言存在失败）时本轮不固化、不产生比对结论——与
    # baseline_created 同属「非判定性视觉状态」，不计为视觉失败（不落
    # warning/failed），场景按 DOM 断言正常判档；judge 侧随即按非打回依据
    # 处理（同 flaky/env 待遇）。此处无需特判：非三档（rejected/diff/warning）
    # 即自然放行至层 4 断言与 pass 判定。
    if any(v.get("status") == "diff_detected" for v in visual_results):
        return "warning"
    if any(v.get("status") == "warning" for v in visual_results):
        return "warning"

    if has_layer_4_fail:
        return "warning"

    return "pass"


# ── 注册表 ─────────────────────────────────────────────────────────

RUNNER_REGISTRY: dict[str, type] = {}


def register_runner(cls: type) -> type:
    """注册 Runner 到按 kind 注册表（装饰器）。

    注册表键 = ``cls.kind``；不同模块重复注册同名 kind 属实现错误，直接报错
    暴露。**同模块重注册放行并替换**（admin 修 2026-09-07）：importlib.reload
    会重新执行类定义与装饰器，若一律 raise，reload 即失败且被验证流水线的
    静默吞异常掩盖——sys.modules 留存旧 Runner 类，admin 对引擎的修复永不
    生效（fix-mobile-touch-disclosure 验证阻塞实证：viewport 修复提交后引擎
    仍跑 1280×800 旧代码）。
    """
    if not getattr(cls, "kind", ""):
        raise ValueError(f"Runner {cls.__name__} 必须声明 kind 属性")
    existing = RUNNER_REGISTRY.get(cls.kind)
    if existing is not None and existing.__module__ != cls.__module__:
        raise ValueError(f"Runner kind 重复注册: {cls.kind}")
    RUNNER_REGISTRY[cls.kind] = cls
    return cls


def get_runner_class(kind: str) -> Optional[type]:
    """按 kind 查 Runner 类；未注册返回 None（引擎据此报未知 kind）。"""
    return RUNNER_REGISTRY.get(kind)
