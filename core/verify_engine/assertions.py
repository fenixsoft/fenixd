"""
assertions.py — 四层 DOM 断言库

分层设计：
  第1层 元素存在性（确定性，0误判）：可见/数量/焦点/可交互状态
  第2层 交互可用性（确定性，0误判）：点击拦截/重叠/视口内/层级
  第3层 内容正确性（确定性，0误判）：文字/属性/DOM结构/控制台错误
  第4层 布局完整性（启发式，需阈值）：溢出/对齐

第1-3层断言失败 = 一定是Bug。
第4层断言失败 = 需Planner结合上下文判定。
"""

import math
import re
import time
from typing import Any

# 词表 layer 表单一权威源在 scenarios.py（WEB_ASSERTION_LAYERS，同 api/cli
# 侧从 scenarios 导入层词表的模式）：各 handler 内硬编码的 layer 是第二
# 副本，run() 出口统一按词表覆盖（code-review item d2b223e5f4dc），任一侧
# 调整层归属或新增断言类型时不再静默漂移。
from .scenarios import WEB_ASSERTION_LAYERS

# 第三方 regex 库（环境可用时）为 regex 模式提供 timeout 参数，防灾难性
# 回溯正则挂起整个验证执行；库缺失时退回 stdlib re（无超时保护）。
try:
    import regex as _regex_mod
except ImportError:  # pragma: no cover
    _regex_mod = None

# 轮询类断言（text_match/attribute_match）timeout/interval 的钳制边界
# （code-review item e396300682b6）：timeout 上界对齐 element_count/
# element_not_exist 的 3s 收敛预算量级、放宽至 Playwright 默认单操作超时，
# 拦截 timeout: 999999999 之类超大声明把 deadline 推到数天后、场景协程被
# 单条断言长期占住；timeout 下界（code-review item e81daf39cc30）防 0/负值
# 把 deadline 推到过去、首轮读取后零等待即判失败；interval 下界防 0/负值在
# deadline 前热轮询。越界一律归一为边界值并在结果 note 中注明，不按配置
# 错误炸场景。
_MAX_POLL_TIMEOUT_MS = 30000
_MIN_POLL_TIMEOUT_MS = 1000
_MIN_POLL_INTERVAL_MS = 50


class AssertionRunner:
    """执行结构化DOM断言。

    每个断言方法签名为: async def _assert_<type>(self, page, assertion: dict) -> dict
    返回统一格式的 dict: {type, layer, pass, selector?, label?, ...}
    """

    # ── 辅助方法 ───────────────────────────────────────────────

    def _locator(self, page, selector: str):
        """安全获取 locator，多元素匹配时自动取 .first。"""
        return page.locator(selector).first

    async def _element_exists(self, page, selector: str) -> bool:
        """检查至少一个匹配元素存在。"""
        try:
            count = await page.locator(selector).count()
            return count > 0
        except Exception:
            return False

    async def _safe_evaluate(self, page, selector: str, js: str, *args):
        """安全执行 evaluate，元素不存在时返回 None 而不超时。"""
        if not await self._element_exists(page, selector):
            return None
        return await self._locator(page, selector).evaluate(js, *args)

    @staticmethod
    def _int_or_none(value: Any):
        """数值参数预校验：可安全 int() 的返回 int，否则返回 None。

        供 count/expected/timeout/interval 等数字参数进轮询前预检使用，
        非数值形态（如 "two"/null/"3s"）在此被拦下按确定性失败上报，
        而不是在方法体内抛 ValueError/TypeError 被 run() 包成缺 selector
        的「断言执行异常」。bool 须在 int() 前显式排除（bool 是 int 子类，
        先例 verify_contract._positive_int_or_default）：否则 count: true
        之类 YAML 笔误会被静默折算成 1 按正常断言裁决。非整数值浮点
        （如 2.5）会被 int() 静默截断，同样按 None 拒绝，不予截断放行。
        """
        if isinstance(value, bool):
            return None
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError):
            # OverflowError：int(float('inf'))（如 JSON 合法值 1e999），
            # 同 engine.py max_parallel 口径；nan 走 ValueError。
            return None
        # 非整数值浮点（如 2.5）被 int() 截断后按截断值裁决，而字符串 "2.5"
        # 走 int() 抛 ValueError 被确定性拒绝——同一非法语义两种处置
        # （code-review item badad82d7719）。比照字符串口径返回 None，由各
        # 调用方既有的非法参数失败路径透出；整数值浮点（300.0）不受影响。
        if isinstance(value, float) and result != value:
            return None
        return result

    @staticmethod
    def _clamp_poll_params(timeout_ms: int, interval_ms: int):
        """钳制轮询参数越界（同 element_count/element_not_exist 预算防线）。

        超大 timeout 声明（如 999999999）会把 deadline 推到数天后，轮询循环
        （每轮 interval 读取 + wait_for_timeout）持续占住场景协程；timeout
        为 0/负值则 deadline 落在过去，首轮读取后零等待即判失败（异步渲染
        场景确定性误判）；interval 为 0/负值则在 deadline 前热轮询；interval
        无上界时（code-review item 1c993346c4da），轮询循环在每轮读取后执行
        wait_for_timeout(interval_ms) 且该等待发生在 deadline 判断之后，超大
        interval（如 999999999）会在首轮读取失败后一次性 sleep 远超 timeout
        预算，与超大 timeout 同类地长期占住场景协程，故钳到 clamped_timeout
        （单条断言预算量级）封顶。越界归一为边界值而非按配置错误炸场景，
        第三元素返回注明文案供结果 note 携带（未越界为空串）。
        """
        clamped_timeout = min(
            max(timeout_ms, _MIN_POLL_TIMEOUT_MS), _MAX_POLL_TIMEOUT_MS
        )
        clamped_interval = min(
            max(interval_ms, _MIN_POLL_INTERVAL_MS), clamped_timeout
        )
        if clamped_timeout == timeout_ms and clamped_interval == interval_ms:
            return timeout_ms, interval_ms, ""
        parts = []
        if clamped_timeout != timeout_ms:
            parts.append(f"timeout {timeout_ms}→{clamped_timeout}ms")
        if clamped_interval != interval_ms:
            parts.append(f"interval {interval_ms}→{clamped_interval}ms")
        return (
            clamped_timeout,
            clamped_interval,
            f"参数越界已归一为边界值（{', '.join(parts)}）",
        )

    @staticmethod
    async def _poll_interval_sleep(page, deadline: float, interval_ms: int):
        """轮询循环按剩余预算截断睡眠（text_match/attribute_match 共用）。

        全额睡 interval_ms 时最坏时序为「读取挂满 interval + 睡 interval +
        再读挂满 interval」，单条断言墙钟可达声明 timeout 的约 3 倍，与
        _clamp_poll_params 注释宣称的单条断言预算量级偏离；截断后睡眠不会
        把下一轮读取起点推过 deadline，墙钟上界收敛回 timeout + 单轮读取
        量级（deadline 为 monotonic 秒，换算毫秒）。

        只收编 deadline 判断之后的这段截断睡眠（code-review item
        e9e91e2c23be）：两处轮询循环的读取与比较语义差异大（表单元素
        分派、正则超时定向归因、异常复位哨兵各不相同），整环抽 _poll_until
        需把 match 异常分流/复位值参数化，漂移风险大于收益，故公共助手
        止于本段——第三处轮询断言复用此处即不再复制这段注释锚点。
        """
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        await page.wait_for_timeout(min(interval_ms, max(0, remaining_ms)))

    # ── 断言执行入口 ──────────────────────────────────────────

    async def run(self, page, assertions: list[dict]) -> list[dict]:
        """执行断言列表，返回每个断言的结果。"""
        results: list[dict] = []
        for assertion in assertions:
            if not isinstance(assertion, dict):
                # fail-closed（code-review item dce263839d91，同 api 侧
                # ApiAssertionRunner.run 的非 dict 条目守卫口径）：非 dict
                # 断言条目（planner/运行期自愈链路产出的畸形条目，如字符串
                # 或 None）会让下方 assertion.get 抛 AttributeError，且位于
                # run() 的 try 之外直接穿透（try 只包 handler 调用），单场景
                # 全部断言以异常收场而非归一为本条的结构化失败。按「未知
                # 断言类型」同款结构返回确定性失败。
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
            handler_name = f"_assert_{a_type}"
            handler = getattr(self, handler_name, None)
            if handler:
                try:
                    result = await handler(page, assertion)
                    result.setdefault("type", a_type)
                    result.setdefault("layer", 0)
                    # 层归属以 scenarios.WEB_ASSERTION_LAYERS 为单一权威源
                    # 覆盖（code-review item d2b223e5f4dc）：消除 handler
                    # 硬编码 layer 这第二副本的漂移面；词表未登记的类型保留
                    # handler 原值（缺省 0，与未知类型回退口径一致）。
                    result["layer"] = WEB_ASSERTION_LAYERS.get(
                        a_type, result.get("layer", 0)
                    )
                    # 统一补 label（code-review item 17bc55668597）：仅部分
                    # handler（element_visible/element_count/element_enabled/
                    # no_click_interception 等）在结果里自带 label，其余
                    # （text_match/z_index_order/alignment 等）不带，正常
                    # 通过/失败路径的 label 缺失使下游证据展示口径不一致；
                    # setdefault 不覆盖 handler 已携带的值，各 handler 既有
                    # label 逻辑保持原样。
                    result.setdefault("label", assertion.get("label", ""))
                    results.append(result)
                except Exception as e:
                    # 兜底补齐定位上下文：handler 内未预检路径（选择器语法
                    # 非法使 locator 抛错、_safe_evaluate 存在性检查与求值
                    # 之间元素消失的竞态等）抛出的异常落到这里，缺 selector
                    # 的裸形态无法定位是哪条断言执行失败。
                    results.append(
                        {
                            "type": a_type,
                            # 与正常路径出口的词表覆盖单点同源（code-review
                            # item d2b223e5f4dc）：已知断言类型异常时层归属
                            # 不得回落 0 与正常失败路径分叉
                            "layer": WEB_ASSERTION_LAYERS.get(a_type, 0),
                            "selector": assertion.get("selector", ""),
                            "label": assertion.get("label", ""),
                            "pass": False,
                            "error": f"断言执行异常: {e}",
                        }
                    )
            else:
                results.append(
                    {
                        "type": a_type,
                        "layer": 0,
                        "pass": False,
                        "error": f"未知断言类型: {a_type}",
                    }
                )
        return results

    # ═══════════════════════════════════════════════════════════════
    # 第1层：元素存在性（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_element_visible(self, page, a: dict) -> dict:
        """断言元素存在且可见。"""
        selector = a["selector"]
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=3000)
            return {
                "type": "element_visible",
                "layer": 1,
                "selector": selector,
                "label": a.get("label", ""),
                "pass": True,
            }
        except Exception as e:
            return {
                "type": "element_visible",
                "layer": 1,
                "selector": selector,
                "label": a.get("label", ""),
                "pass": False,
                "error": str(e),
            }

    async def _assert_element_count(self, page, a: dict) -> dict:
        """断言元素数量等于期望值。

        字段口径（admin 修 2026-08-29：failover-model-mapping-ui 族谱爆炸根因）：
        planner 生成的场景事实约定用 ``count`` 字段（全库 test_scenarios.json
        133 处 vs ``expected`` 28 处），而引擎此前只读 ``expected``——所有
        ``count: 2`` 的场景被静默按缺省值 1 断言，产品正确渲染 2 行时反而
        伪失败（expected=1/actual=2），被 judge 记为产品 bug 或伪失败，
        反复派生 fix 子 SPEC（fix-fix-improve-failover-model-mapping-ui 两轮
        验证同因翻车）。``count`` 优先，``expected`` 兼容，缺省 1。

        带最长 3s 的收敛等待：异步渲染场景下首次读取可能早于列表数据落地，
        比照 element_not_exist 轮询重读到数量一致，超时仍不等才按最后读取
        值判 fail。
        """
        selector = a["selector"]
        count_field = "count" if "count" in a else "expected"
        expected_raw = a.get(count_field, 1)
        expected = self._int_or_none(expected_raw)
        if expected is None:
            # 非数值期望是确定性配置错误：int() 在方法体内抛 ValueError/
            # TypeError 会被 run() 包装成无 selector 的「断言执行异常」，
            # 无法定位是哪个断言的参数非法；比照 _assert_z_index_order 的
            # 非法 operator 口径，进轮询前返回带 selector 与参数名的失败。
            return {
                "type": "element_count",
                "layer": 1,
                "selector": selector,
                "label": a.get("label", ""),
                **{count_field: expected_raw},
                "pass": False,
                "error": f"非法 {count_field}: {expected_raw!r}，须为数值",
            }
        locator = page.locator(selector)
        # [fenix-ignore:87212a1756aa] 条目基于旧时点代码：此处已非瞬时一次性读数，不等时按 element_not_exist 同款 10 次×300ms 轮询收敛
        actual = await locator.count()
        if actual != expected:
            for _ in range(10):
                await page.wait_for_timeout(300)
                actual = await locator.count()
                if actual == expected:
                    break
        # 声明字段名透出（code-review item e3c2ca53264a）：与上方确定性失败
        # 路径的 **{count_field: expected_raw} 对齐——正常路径结果恒写
        # expected 键，用 count 声明的场景经 judge/报告证据回看时无法还原
        # 原字段口径；按加法键 expected_field 附带声明字段名，不改动既有
        # expected 键，存量读取该键的断言不受影响。
        return {
            "type": "element_count",
            "layer": 1,
            "selector": selector,
            "label": a.get("label", ""),
            "expected": expected,
            "expected_field": count_field,
            "actual": actual,
            "pass": actual == expected,
        }

    async def _assert_element_not_exist(self, page, a: dict) -> dict:
        """断言元素不存在（用于验证删除操作）。

        带最长 3s 的收敛等待（admin 修 2026-08-29：族谱爆炸根因之一）：
        乐观 DOM 移除（如删除 spec 行）发生在 POST 响应回调里，高并行度下
        断言执行瞬间可能早于回调落地——瞬时 count 会把「稍后即消失」的元素
        误判为失败。轮询等待元素消失，超时仍存在才判 fail（真残留依然失败）。
        """
        selector = a["selector"]
        locator = page.locator(selector)
        count = await locator.count()
        if count > 0:
            for _ in range(10):
                await page.wait_for_timeout(300)
                count = await locator.count()
                if count == 0:
                    break
        return {
            "type": "element_not_exist",
            "layer": 1,
            "selector": selector,
            "label": a.get("label", ""),
            "actual_count": count,
            "pass": count == 0,
        }

    async def _assert_element_focused(self, page, a: dict) -> dict:
        """断言元素获得焦点。"""
        selector = a["selector"]
        focused = await self._safe_evaluate(page, selector, "el => el === document.activeElement")
        result = {
            "type": "element_focused",
            "layer": 1,
            "selector": selector,
            "pass": focused is True,
        }
        if focused is None:
            # 与 element_enabled/no_overlap「元素不存在」口径对齐：None =
            # 元素缺失/求值失败，排障时无须猜测是缺失还是焦点不在
            result["error"] = f"元素 '{selector}' 不存在"
        return result

    async def _assert_element_enabled(self, page, a: dict) -> dict:
        """断言元素可交互（非disabled状态）。"""
        selector = a["selector"]
        if not await self._element_exists(page, selector):
            return {
                "type": "element_enabled",
                "layer": 1,
                "selector": selector,
                "label": a.get("label", ""),
                "pass": False,
                "error": "元素不存在",
            }
        enabled = await self._locator(page, selector).is_enabled()
        return {
            "type": "element_enabled",
            "layer": 1,
            "selector": selector,
            "label": a.get("label", ""),
            "pass": enabled,
        }

    # ═══════════════════════════════════════════════════════════════
    # 第2层：交互可用性（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_no_click_interception(self, page, a: dict) -> dict:
        """断言元素点击不被遮挡。

        Playwright 原生支持：当元素被其他元素遮挡时，
        locator.click(trial=True) 会抛出 'intercepts pointer events' 错误。
        """
        selector = a["selector"]
        locator = self._locator(page, selector)
        try:
            await locator.click(trial=True, timeout=3000)
            return {
                "type": "no_click_interception",
                "layer": 2,
                "selector": selector,
                "label": a.get("label", ""),
                "pass": True,
            }
        except Exception as e:
            error_msg = str(e)
            # 尝试提取拦截元素信息
            intercept_detail: dict[str, Any] | None = None
            detail_note = ""
            if "intercepts pointer events" in error_msg:
                try:
                    # 在目标元素自身上执行 elementFromPoint 逻辑，而非
                    # document.querySelector(selector)：selector 是 Playwright
                    # 选择器语法（支持 :has-text() / text= 等），querySelector
                    # 对这类语法抛 SyntaxError 被静默吞掉，含 tag/z-index 的
                    # 拦截详情在最有价值的拦截场景反而拿不到。
                    intercept_detail = await self._locator(page, selector).evaluate(
                        """el => {
                            const rect = el.getBoundingClientRect();
                            const cx = rect.left + rect.width / 2;
                            const cy = rect.top + rect.height / 2;
                            const topEl = document.elementFromPoint(cx, cy);
                            if (topEl && topEl !== el) {
                                return {
                                    intercepting_tag: topEl.tagName,
                                    intercepting_class: topEl.className?.toString() || '',
                                    intercepting_z_index: getComputedStyle(topEl).zIndex,
                                    target_z_index: getComputedStyle(el).zIndex,
                                };
                            }
                            return null;
                        }"""
                    )
                except Exception as e:
                    # 拦截详情提取失败不阻塞主流程，但随结果 note 注明原因，
                    # judge 归因时可知 intercept_detail=None 并非「无遮挡详情」。
                    # evaluate 抛错不一定是选择器语法：存在性/拦截判定通过后
                    # 元素被移除、页面导航中、上下文关闭等竞态同样会抛错（比照
                    # z_index_order/alignment 竞态窗口「元素不存在」口径），
                    # note 携带实际异常类型，避免固定归因选择器误导排障。
                    detail_note = f"拦截详情未提取（{type(e).__name__}，拦截元素 tag/z-index 未知）"

            return {
                "type": "no_click_interception",
                "layer": 2,
                "selector": selector,
                "label": a.get("label", ""),
                "pass": False,
                "error": error_msg,
                "intercept_detail": intercept_detail,
                **({"note": detail_note} if detail_note else {}),
            }

    async def _assert_no_overlap(self, page, a: dict) -> dict:
        """断言目标元素不与同级元素发生超过阈值的重叠。

        通过 getBoundingClientRect 计算交集面积比例。
        """
        selector = a["selector"]
        threshold_raw = a.get("threshold", 0.2)
        try:
            threshold = float(threshold_raw)
        except (TypeError, ValueError):
            threshold = None
        if threshold is None or not 0 < threshold < 1:
            # 非法 threshold 确定性失败而非静默透传（与 _assert_z_index_order
            # 非法 operator 口径一致）：planner 误写 "20%" 等非数值进 JS 数值
            # 比较得 NaN 恒为 false，任何重叠都检不出、断言恒 pass（假通过）；
            # 0/负数又会把全部同级元素报成重叠。进 evaluate 前显式失败。
            return {
                "type": "no_overlap",
                "layer": 2,
                "selector": selector,
                "threshold": threshold_raw,
                "pass": False,
                "error": f"非法 threshold: {threshold_raw!r}，须为 (0,1) 开区间内数值",
            }

        overlaps = await self._safe_evaluate(
            page,
            selector,
            """(el, threshold) => {
                const rect = el.getBoundingClientRect();
                const parent = el.parentElement;
                if (!parent) return { zero_size: false, results: [] };
                const siblings = [...parent.children].filter(c => c !== el);
                const targetArea = rect.width * rect.height;
                // display:none 等隐藏元素 getBoundingClientRect 返回全零 rect，
                // targetArea===0 时重叠比例无法计算、恒判「无重叠」假通过，标记
                // zero_size 交 Python 侧显式失败（与 in_viewport 零尺寸口径一致）
                if (targetArea === 0) return { zero_size: true, results: [] };

                const results = [];
                for (const sib of siblings) {
                    const sr = sib.getBoundingClientRect();
                    const xOverlap = Math.max(0,
                        Math.min(rect.right, sr.right) - Math.max(rect.left, sr.left));
                    const yOverlap = Math.max(0,
                        Math.min(rect.bottom, sr.bottom) - Math.max(rect.top, sr.top));
                    const overlapArea = xOverlap * yOverlap;
                    const ratio = overlapArea / targetArea;
                    if (ratio > threshold) {
                        results.push({
                            sibling_tag: sib.tagName,
                            // SVG 的 className 是 SVGAnimatedString（无 split），
                            // 可选链挡不住类型不符，须先 toString 再 split
                            sibling_class: sib.className?.toString?.().split(' ')[0] || '',
                            overlap_ratio: Math.round(ratio * 100) / 100,
                            sibling_z_index: getComputedStyle(sib).zIndex,
                        });
                    }
                }
                return { zero_size: false, results };
            }""",
            threshold,
        )

        if overlaps is None:
            return {
                "type": "no_overlap",
                "layer": 2,
                "selector": selector,
                "threshold": threshold,
                "pass": False,
                "error": "元素不存在，无法检测重叠",
            }
        if isinstance(overlaps, dict) and overlaps.get("zero_size", False):
            # 零尺寸/隐藏目标的重叠比例无法计算，恒判「无重叠」是无信息量的
            # 假通过，显式失败供 judge 区分「确无重叠」与「目标根本不可见」。
            return {
                "type": "no_overlap",
                "layer": 2,
                "selector": selector,
                "threshold": threshold,
                "pass": False,
                "error": "元素存在但零尺寸（如 display:none / 隐藏），重叠检查无意义，不视为通过",
            }
        results = overlaps.get("results", []) if isinstance(overlaps, dict) else []
        return {
            "type": "no_overlap",
            "layer": 2,
            "selector": selector,
            "threshold": threshold,
            "pass": len(results) == 0,
            "overlaps": results,
        }

    async def _assert_in_viewport(self, page, a: dict) -> dict:
        """断言元素在可视区域内。"""
        selector = a["selector"]
        in_view = await self._safe_evaluate(
            page,
            selector,
            """el => {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) {
                // display:none 等隐藏元素 getBoundingClientRect 返回全零 rect，
                // 四条边界不等式恒真会被误判为「在可视区域内」，零尺寸显式判失败
                return { zero_size: true };
            }
            return {
                zero_size: false,
                in_view:
                    rect.top >= 0 &&
                    rect.left >= 0 &&
                    rect.bottom <= window.innerHeight &&
                    rect.right <= window.innerWidth,
            };
        }""",
        )  # in_viewport evaluate ends
        if in_view is None:
            return {
                "type": "in_viewport",
                "layer": 2,
                "selector": selector,
                "pass": False,
                "error": "元素不存在",
            }
        if in_view.get("zero_size", False):
            return {
                "type": "in_viewport",
                "layer": 2,
                "selector": selector,
                "pass": False,
                "error": "元素存在但零尺寸（如 display:none / 隐藏），不视为在可视区域内",
            }
        return {
            "type": "in_viewport",
            "layer": 2,
            "selector": selector,
            "pass": in_view["in_view"],
        }

    async def _assert_z_index_order(self, page, a: dict) -> dict:
        """断言元素的z-index层级关系。

        extra参数:
            compare_selector: 对比元素选择器（必填，缺失/为空时断言直接失败）
            operator: 比较操作符（> / < / ==），默认 ">"
        """
        selector = a["selector"]
        compare_selector = a.get("compare_selector", "")
        op = a.get("operator", ">")
        if op not in (">", "<", "=="):
            # 确定性失败而非静默按相等比较：planner 误写 ">="/"≥" 等会落入
            # == 分支产出与场景意图相悖的裁决，与 _assert_alignment 的非法
            # axis 口径保持一致，给出可定位提示。
            return {
                "type": "z_index_order",
                "layer": 2,
                "selector": selector,
                "compare_selector": compare_selector,
                "operator": op,
                "pass": False,
                "error": f"非法 operator: {op!r}，仅支持 >/</==",
            }

        if not compare_selector:
            # 显式失败而非静默兜底：缺对比对象时 _safe_evaluate 会返回
            # None 并按 z-index 0 处理，变成「自身 vs 0」却无任何提示。
            return {
                "type": "z_index_order",
                "layer": 2,
                "selector": selector,
                "compare_selector": compare_selector,
                "operator": op,
                "pass": False,
                "error": "缺少 compare_selector",
            }

        if not await self._element_exists(page, selector):
            return {
                "type": "z_index_order",
                "layer": 2,
                "selector": selector,
                "compare_selector": compare_selector,
                "operator": op,
                "pass": False,
                "error": f"元素 '{selector}' 不存在",
            }

        # compare_selector 已在上方缺参检查中确保非空，此处直接判存在性
        if not await self._element_exists(page, compare_selector):
            return {
                "type": "z_index_order",
                "layer": 2,
                "selector": selector,
                "compare_selector": compare_selector,
                "operator": op,
                "pass": False,
                "error": f"对比元素 '{compare_selector}' 不存在",
            }

        z1_result = await self._safe_evaluate(
            page, selector, "el => parseInt(getComputedStyle(el).zIndex) || 0"
        )
        z2_result = await self._safe_evaluate(
            page, compare_selector, "el => parseInt(getComputedStyle(el).zIndex) || 0"
        )
        # 存在性预检通过后、读取前的竞态窗口内元素被移除时 _safe_evaluate
        # 返回 None：比照 _assert_alignment 对 evaluate_all 空列表的口径显式
        # 按元素不存在失败（code-review item e4f0eb541bb2），而非折叠为 0
        # 继续裁决——后者对 ==（或 < 且对比侧 z-index>0）会把已消失的元素
        # 判 pass，与模块头「第 1-3 层缺失一律显式失败」的承诺相悖。
        if z1_result is None:
            return {
                "type": "z_index_order",
                "layer": 2,
                "selector": selector,
                "compare_selector": compare_selector,
                "operator": op,
                "pass": False,
                "error": f"元素 '{selector}' 不存在",
            }
        if z2_result is None:
            return {
                "type": "z_index_order",
                "layer": 2,
                "selector": selector,
                "compare_selector": compare_selector,
                "operator": op,
                "pass": False,
                "error": f"对比元素 '{compare_selector}' 不存在",
            }
        z1 = z1_result
        z2 = z2_result

        if op == ">":
            passed = z1 > z2
        elif op == "<":
            passed = z1 < z2
        else:
            passed = z1 == z2

        return {
            "type": "z_index_order",
            "layer": 2,
            "selector": selector,
            "compare_selector": compare_selector,
            "z_index_self": z1,
            "z_index_compare": z2,
            "operator": op,
            "pass": passed,
        }

    # ═══════════════════════════════════════════════════════════════
    # 第3层：内容正确性（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    def _text_matches(
        self, actual: str, expected: str, mode: str, regex_compiled: re.Pattern | None = None
    ) -> bool:
        """按 mode 判断文本是否匹配。"""
        if mode == "exact":
            return actual.strip() == expected.strip()
        if mode == "contains":
            return expected in actual
        if mode == "regex":
            return self._regex_search(expected, actual, regex_compiled)
        return False

    # regex 模式单次匹配的回溯预算（秒）：compile 通过但呈灾难性回溯的
    # 正则（嵌套量词形态）在匹配时无超时保护，长文本下会同步阻塞
    # AssertionRunner 直至回溯结束，整轮验证被单个断言拖死；planner 产出
    # 属半可信输入，单次匹配超时按「不匹配」收场，交由轮询按普通失败上报
    # （匹配超时轮以带「正则匹配超时」归因的 re.error 抛给调用方定向
    # 标注，见 _regex_search）。
    _REGEX_MATCH_TIMEOUT_S = 1.0

    @classmethod
    def _regex_search(
        cls, pattern: str, text: str, compiled: re.Pattern | None = None
    ) -> bool:
        """regex 模式匹配，带单次匹配超时保护。

        优先用第三方 regex 库的 timeout 参数（覆盖嵌套量词等全部灾难性
        回溯形态，超时抛 TimeoutError）；库不可用时退回 stdlib re（行为
        同旧版，无超时保护）。其余异常一律按不匹配收场——抛错会被
        _assert_text_match 的 except 当「元素尚未渲染」空转至超时；仅
        匹配超时重抛为带归因的 re.error（code-review item b34af3a4195b，
        与 api 侧 _TimeoutRegex 的定向归因口径对齐），由
        _assert_text_match 单独捕获记入结果 error，归因不被吞。

        compiled 是调用方预编译好的同一 pattern（编译引擎与 regex 库可用
        性一致，见 _assert_text_match 的正则预检），传入时复用编译产物，
        轮询循环不必每轮重复解析编译（同 api 侧 _TimeoutRegex 的预编译
        口径，code-review item ad66fbae76be）；未传入时保持模块级 search
        的旧行为。
        """
        if _regex_mod is not None:
            try:
                if compiled is not None:
                    return bool(
                        compiled.search(text, timeout=cls._REGEX_MATCH_TIMEOUT_S)
                    )
                return bool(
                    _regex_mod.search(pattern, text, timeout=cls._REGEX_MATCH_TIMEOUT_S)
                )
            except TimeoutError:
                raise re.error(
                    f"正则匹配超时（>{cls._REGEX_MATCH_TIMEOUT_S}s，"
                    f"疑似灾难性回溯）: {pattern!r}"
                ) from None
            except Exception:
                return False
        if compiled is not None:
            return bool(compiled.search(text))
        return bool(re.search(pattern, text))

    async def _assert_text_match(self, page, a: dict) -> dict:
        """断言元素文字内容匹配。

        mode: exact（精确）/ contains（包含）/ regex（正则）
        对 input/textarea/select 元素自动使用 value 属性（而非 textContent）。

        与 element_visible 一致，带等待/重试：异步渲染（如 WebCrypto 密码
        哈希 + 密钥加密的用户创建流程）完成后 DOM 才更新，一次性读取会
        读到旧值，因此轮询到超时为止。
        """
        selector = a["selector"]
        # 「未设置」哨兵是 None 而非空串：空串是 text_match 的合法期望值
        # （如「detail 为空串」），与 scenarios.py Assertion 哨兵及 api 侧
        # json_path/sse_event_matches 的空串 exact 比较口径一致。
        expected = a.get("expected", None)
        mode = a.get("mode", "exact")
        # 数值参数预校验（同 element_count 的 count/expected 口径）：非数值
        # timeout/interval 会让 int() 在方法体内抛 ValueError/TypeError，被
        # run() 包装成无 selector 的「断言执行异常」，进轮询前显式失败。
        timeout_ms = self._int_or_none(a.get("timeout", 3000))
        interval_ms = self._int_or_none(a.get("interval", 200))
        if timeout_ms is None or interval_ms is None:
            bad_param = "timeout" if timeout_ms is None else "interval"
            return {
                "type": "text_match",
                "layer": 3,
                "selector": selector,
                "expected": expected,
                "actual": "",
                "mode": mode,
                "pass": False,
                "error": f"非法 {bad_param}: {a.get(bad_param)!r}，须为数值（毫秒）",
            }
        # 越界钳制（同 attribute_match 口径）：超大 timeout/零 interval 归一为
        # 边界值，进轮询前生效，注明文案随结果 note 带出。
        timeout_ms, interval_ms, clamp_note = self._clamp_poll_params(
            timeout_ms, interval_ms
        )

        if expected is None:
            # 显式失败而非静默恒真：expected 未设置时与 dom_structure 的缺参
            # 口径（确定性失败）保持一致，给出可定位提示。
            return {
                "type": "text_match",
                "layer": 3,
                "selector": selector,
                "expected": expected,
                "actual": "",
                "mode": mode,
                "pass": False,
                "error": "缺少 expected 字段",
            }
        if not isinstance(expected, str):
            # 非字符串 expected（planner 误写 JSON 数字/布尔等）是确定性配置
            # 错误：_text_matches 里 expected.strip()/子串比较会抛
            # AttributeError/TypeError，被轮询循环当「元素尚未渲染」空转至
            # 超时，与下方非法正则/非法 mode 的预检口径一致，进轮询前显式失败。
            return {
                "type": "text_match",
                "layer": 3,
                "selector": selector,
                "expected": expected,
                "actual": "",
                "mode": mode,
                "pass": False,
                "error": f"非法 expected: {expected!r}，须为字符串",
            }
        if expected == "" and mode in ("contains", "regex"):
            # 显式空串对 contains/regex 恒真（"" 是任意文本的子串、空串正则
            # 恒匹配），维持确定性失败避免假通过；exact 模式放行空串比较，
            # actual.strip() == "" 断言「元素文本为空」。
            return {
                "type": "text_match",
                "layer": 3,
                "selector": selector,
                "expected": expected,
                "actual": "",
                "mode": mode,
                "pass": False,
                "error": f"mode={mode} 时 expected 为显式空串恒真，拒绝",
            }

        # 非法正则是确定性错误：_text_matches 经 _regex_search 匹配时在 regex
        # 库可用时走 _regex_mod.search，预检须用同一引擎——regex 是 re 的超集，
        # 仅 regex 支持的语法（如递归）会被 stdlib re.compile 误判为非法正则、
        # 把可执行的合法期望值按确定性错误拒绝；regex.error 与 re.error 无继承
        # 关系，须按引擎捕获对应异常。库缺失时回退 re.compile/re.error。
        # （code-review item 11293370e8f2）非法正则本身仍是确定性错误：
        # _text_matches 内每轮重抛匹配异常，会被下方 except 当作「元素尚未
        # 渲染」的临时态空转至超时，故进轮询前预检。
        # [fenix-ignore:7f1d7284e123] 正则预检以 mode == "regex" 为门，mode 非法
        # 时进不了本分支，下方「非法 mode」校验必然先于任何正则报错触发，
        # 「双配置错误归因偏离」场景在当前代码中不存在。
        # 预编译产物（regex 库可用时 regex.compile、缺失时 re.compile）随
        # 轮询循环复用，避免每轮匹配重复解析编译同一 pattern（同 api 侧
        # _TimeoutRegex 的预编译口径，code-review item ad66fbae76be）。
        regex_compiled = None
        if mode == "regex":
            if _regex_mod is not None:
                regex_compile, regex_errors = _regex_mod.compile, _regex_mod.error
            else:
                regex_compile, regex_errors = re.compile, re.error
            try:
                regex_compiled = regex_compile(expected)
            except regex_errors as e:
                return {
                    "type": "text_match",
                    "layer": 3,
                    "selector": selector,
                    "expected": expected,
                    "actual": "",
                    "mode": mode,
                    "pass": False,
                    "error": f"非法正则: {e}",
                }

        # 非法 mode 是确定性配置错误：_text_matches 对未知 mode 返回 False，
        # text_match 会空转至超时后按普通失败收场且无任何提示，judge 会把
        # planner 的拼写错误（如 mode: has_text）误归因为产品缺陷；与
        # _assert_z_index_order 的非法 operator 口径一致，进轮询前显式失败。
        if mode not in ("exact", "contains", "regex"):
            return {
                "type": "text_match",
                "layer": 3,
                "selector": selector,
                "expected": expected,
                "actual": "",
                "mode": mode,
                "pass": False,
                "error": f"非法 mode: {mode!r}，仅支持 exact/contains/regex",
            }

        deadline = time.monotonic() + timeout_ms / 1000
        actual = ""
        passed = False
        last_error = ""
        regex_error = ""

        while True:
            try:
                # 单次读取限时 interval_ms：元素永不渲染时这些 API 会按
                # Playwright 默认 30 秒超时阻塞，先于下方 deadline 检查
                # 突破预算，故显式压到单轮间隔内，交由轮询兜底。
                # 注意不能像 attribute_match 那样进轮询前先查存在性快速
                # 失败——本方法的等待重试正是为异步渲染设计的。
                # input/textarea/select 元素使用 value 属性
                tag = await self._locator(page, selector).evaluate(
                    "el => el.tagName?.toLowerCase()", timeout=interval_ms
                )
                if tag in ("input", "textarea", "select"):
                    actual = (
                        await self._locator(page, selector).input_value(timeout=interval_ms)
                    ) or ""
                else:
                    actual = (
                        await self._locator(page, selector).text_content(timeout=interval_ms)
                    ) or ""

                try:
                    passed = self._text_matches(actual, expected, mode, regex_compiled)
                except re.error as e:
                    # 正则匹配超时（灾难性回溯）的定向归因（code-review item
                    # b34af3a4195b，与 api 侧 _TimeoutRegex 口径对齐）：按普通
                    # 失败继续轮询（文本可能随渲染变化），但归因不经「元素尚未
                    # 渲染」兜底、随结果 error 带出，actual 保留已读文本。
                    regex_error = str(e)
                if passed:
                    break
            except Exception as e:
                # 元素尚未渲染/不可读时继续重试
                last_error = str(e)
                actual = ""

            if time.monotonic() >= deadline:
                break
            # 按剩余预算截断睡眠（code-review item 9ada803767ca，公共助手
            # 收编自本处与 attribute_match 的同构段，见
            # _poll_interval_sleep 注释）。
            await self._poll_interval_sleep(page, deadline, interval_ms)

        return {
            "type": "text_match",
            "layer": 3,
            "selector": selector,
            "expected": expected,
            "actual": actual.strip(),
            "mode": mode,
            "pass": passed,
            **({"error": last_error} if not passed and last_error else {}),
            # 正则超时归因后置（同 key 时覆盖读数异常）：后者只说明「元素尚未
            # 渲染」，定向的正则归因对 judge 判别场景缺陷更有价值。
            **({"error": regex_error} if not passed and regex_error else {}),
            **({"note": clamp_note} if clamp_note else {}),
        }

    async def _assert_text_contains(self, page, a: dict) -> dict:
        """断言页面某处包含指定文本。

        支持两种字段名: text 或 expected。
        如果提供了 selector，则在指定的任意一个匹配元素内查找文本。
        结果 match_semantics 透出实际匹配分支与大小写口径（三条路径不同）。
        """
        text = a.get("text") or a.get("expected", "")
        selector = a.get("selector", "")

        if not text:
            # 显式失败而非静默恒真：缺参时 text 为空串，selector 分支的
            # `"" in t` 与页面级降级的 `"" in content` 对任意内容恒真，
            # 会产出假通过；与 dom_structure 的缺参口径（确定性失败）
            # 保持一致，给出可定位提示。
            return {
                "type": "text_contains",
                "layer": 3,
                "text": text,
                "pass": False,
                "error": "缺少 text/expected 字段",
            }

        if not isinstance(text, str):
            # 非字符串 text/expected（planner 误写 JSON 数字/布尔等）是确定性
            # 配置错误：selector 分支的 `text in (t or "")` 抛 TypeError 会被
            # 下方 except 吞成无 error 归因的普通失败，页面级分支 get_by_text
            # 抛错落入保底后 `text in content` 二次抛 TypeError 逃逸到 run()
            # 被包成「断言执行异常」；与 text_match 非字符串 expected 的预检
            # 口径一致，进匹配前显式失败。
            return {
                "type": "text_contains",
                "layer": 3,
                "text": text,
                "pass": False,
                "error": f"非法 text/expected: {text!r}，须为字符串",
            }

        # 逐元素取数触顶标注（页面级降级分支不产生），随结果 note 带出
        budget_note = ""
        # 实际匹配口径透出（code-review item a60cce14f7b1）：有无 selector 的
        # 两条路径（含页面级异常保底）大小写敏感性与空白归一不同，随结果
        # match_semantics 透出实际分支与大小写口径供 judge 归因；判档本身
        # 维持各分支既有语义不变——存量冻结场景依赖页面级 get_by_text 的
        # 大小写不敏感匹配，统一改口径会翻转既有判定。
        match_semantics = ""
        # 实际检查的元素计数（仅 selector 分支填充，code-review item
        # 4d31aefb1f81）：取数中断时保持 None，随结果透出供 judge 归因。
        checked_elements = None
        # 逐元素取数外层异常文本（仅 selector 分支填充，code-review item
        # 02b9b2b1d6e5）：locator.all() 本身抛错等异常随结果 error 带出。
        outer_error = ""
        if selector:
            match_semantics = "selector 元素文本子串比较（大小写敏感）"
            # 等待至少一个匹配元素出现（容忍尚未渲染的情况），再检查全部匹配
            # wait_for 是否命中随结果透出（code-review item 4d31aefb1f81）。
            selector_attached = False
            try:
                await page.locator(selector).first.wait_for(state="attached", timeout=3000)
                selector_attached = True
            except Exception:
                pass
            try:
                # 逐元素取数（与 text_match 的表单元素口径一致，code-review
                # item fdf0d3af6c79）：input/textarea/select 的页面值落在
                # value 属性上、textContent 恒为空串，只读 textContent 会把
                # 已渲染值确定性误判为失败；input_value 取值异常时回退
                # textContent（单次读取限时 3s 同方法既有等待口径）。
                # 总预算防线（code-review item 6405221a79ad）：循环本身无
                # deadline，宽泛选择器意外命中大量元素时 元素数×3s 可把单条
                # 断言拖到分钟级占住场景协程（对比 text_match/
                # attribute_match 的 timeout 钳制预算防线），触顶截断剩余
                # 元素、已取文本仍参与匹配，并在结果 note 注明。
                deadline = time.monotonic() + _MAX_POLL_TIMEOUT_MS / 1000
                texts = []
                for loc in await page.locator(selector).all():
                    if time.monotonic() >= deadline:
                        budget_note = (
                            f"匹配元素过多，逐元素取数超出总预算"
                            f"（{_MAX_POLL_TIMEOUT_MS}ms）已截断，"
                            f"仅检查前 {len(texts)} 个匹配元素"
                        )
                        break
                    try:
                        tag = await loc.evaluate(
                            "el => el.tagName?.toLowerCase()", timeout=3000
                        )
                        if tag in ("input", "textarea", "select"):
                            try:
                                texts.append(
                                    (await loc.input_value(timeout=3000)) or ""
                                )
                                continue
                            except Exception:
                                pass
                        texts.append((await loc.text_content(timeout=3000)) or "")
                    except Exception:
                        # 单元素瞬态取数异常（遍历中被移除等）只跳过该元素：
                        # 异常冒到外层 except 会跳过 any() 判定、丢弃已收集
                        # 元素的命中结果按普通失败收场，且无 error 归因区分
                        # 「确无匹配」与「取数中断」；已取文本仍参与匹配的
                        # 口径同上方预算截断路径（code-review item
                        # e82503f5caf5）。
                        continue
                passed = any(text in (t or "") for t in texts)
                # 元素计数透出（code-review item 4d31aefb1f81）：零命中与
                # 「渲染了但文本不含期望值」此前同为无 error 的 pass=False，
                # judge 无法区分配置性失败与内容缺陷。
                checked_elements = len(texts)
            except Exception as e:
                # 外层取数异常归因（code-review item 02b9b2b1d6e5）：异常若
                # 只置 passed=False，结果将无 error/note、checked_elements
                # 保持 None，judge 无法区分「确无匹配」「零命中」与「取数
                # 中断」；异常文本随结果 error 带出（口径同 text_match 的
                # last_error 透出）。单元素级瞬态异常已有上方 continue 的
                # 跳过归因（e82503f5caf5），此处只兜外层这一档。
                passed = False
                outer_error = str(e)
        else:
            # 在整个页面中查找文本。
            # 优先按可见文本匹配（get_by_text 不计入 <script>/<style> 内容，
            # HTML 注释与属性值也天然不参与），避免 React/umi 等把数据内嵌
            # 在 <script> 里的产物页命中脚本字符串造成假通过；
            # 无 get_by_text 的环境（stub 页面等）降级回 page.content()
            # 原始 HTML 子串匹配——该保底路径存在 script/注释误判可能。
            # 与 selector 分支同形态：先等文本出现（容忍异步渲染，超时吞掉）
            # 再取数，避免断言先于渲染落地执行时立即 count 产出假失败。
            try:
                try:
                    await page.get_by_text(text).first.wait_for(
                        state="attached", timeout=3000
                    )
                except Exception:
                    pass
                match_semantics = "页面级 get_by_text（大小写不敏感、空白归一）"
                passed = await page.get_by_text(text).count() > 0
            except Exception:
                match_semantics = (
                    "页面级 page.content() 原始 HTML 子串保底（大小写敏感）"
                )
                content = await page.content()
                passed = text in content

        result = {
            "type": "text_contains",
            "layer": 3,
            "text": text,
            "pass": passed,
            "match_semantics": match_semantics,
            **({"note": budget_note} if budget_note else {}),
        }
        if selector:
            # 零命中归因（code-review item 4d31aefb1f81）：texts 长度随结果
            # 透出，零命中附 error 提示与 note（含 wait_for attached 是否
            # 命中），供 judge 区分「元素从未渲染」的场景前置/配置性失败与
            # 「渲染但文本不含期望值」的内容失败——同文件 text_match/
            # attribute_match 对元素缺失均有 error 归因或存在性预检。
            result["checked_elements"] = checked_elements
            if outer_error:
                # 外层取数中断归因（code-review item 02b9b2b1d6e5）优先于
                # 零命中：异常路径下 checked_elements 保持 None，与下方
                # checked_elements == 0 分支互斥，不争写 error 键。
                result["error"] = f"逐元素取数中断: {outer_error}"
            if checked_elements == 0:
                result["error"] = "选择器未匹配到任何元素"
                zero_note = (
                    "元素零命中（wait_for attached 未命中，元素从未渲染）"
                    if not selector_attached
                    else "元素零命中（wait_for attached 已命中，读取时元素数为 0）"
                )
                result["note"] = (
                    f"{budget_note}；{zero_note}" if budget_note else zero_note
                )
        return result

    async def _assert_attribute_match(self, page, a: dict) -> dict:
        """断言元素属性值等于期望值。"""
        selector = a["selector"]
        attr = a.get("attribute", "")
        # 「未设置」哨兵是 None 而非空串（code-review item ef4b26f85ce3，同
        # text_match 口径）：空串是断言「属性值为空」的合法期望值；若缺省
        # 空串，场景漏写 expected 键会进轮询与真实属性值比较直到超时、按
        # 普通失败收场且无配置错误归因，judge 易把 planner 漏参误判为产品
        # 缺陷。漏写与显式 null 统一命中下方缺参检查，确需断言空属性值的
        # 场景显式写 expected: ""。
        expected = a.get("expected", None)
        if not attr or expected is None:
            # 显式失败而非空转（与 text_match/z_index_order 缺参口径一致）：
            # attribute 缺参时 get_attribute("") 每轮抛错被轮询吞掉重试、
            # expected=None 与任何读取值永不相等，均空转满超时且报错是
            # Playwright 原始文本，judge 易把 planner 缺参误判为产品缺陷
            return {
                "type": "attribute_match",
                "layer": 3,
                "selector": selector,
                "attribute": attr,
                "expected": expected,
                "pass": False,
                "error": "缺少 attribute 字段" if not attr else "缺少 expected 字段",
            }
        if not isinstance(expected, str):
            # 非字符串 expected（planner 误写 JSON 数字/布尔）是确定性配置
            # 错误：get_attribute 返回 str/None，与数值期望永不相等，会空转
            # 满超时后按普通失败收场且无配置错误归因；属性值恒为字符串语义，
            # 比照 text_match 的非字符串 expected 预检口径（code-review item
            # ff8a84f7be8f），进轮询前显式失败。
            return {
                "type": "attribute_match",
                "layer": 3,
                "selector": selector,
                "attribute": attr,
                "expected": expected,
                "pass": False,
                "error": f"非法 expected: {expected!r}，须为字符串",
            }
        if not isinstance(attr, str):
            # 非字符串 attribute（planner 误写 YAML dict/list 等结构化值）是
            # 确定性配置错误：上方缺参检查只拦 falsy，真值 dict/list 会穿过
            # 全部预检，get_attribute(attr) 每轮抛 TypeError 被轮询 except
            # 吞掉、按「元素尚未渲染」空转满超时后报错是 Playwright 原始
            # 文本，正是 expected 预检着力消除的形态；比照同款口径
            # （code-review item 5b37c05f7b47），进轮询前显式失败。
            return {
                "type": "attribute_match",
                "layer": 3,
                "selector": selector,
                "attribute": attr,
                "expected": expected,
                "pass": False,
                "error": f"非法 attribute: {attr!r}，须为字符串",
            }
        if not await self._element_exists(page, selector):
            # 快速失败：比照 _assert_element_enabled 先查存在性，
            # 避免元素缺失时 get_attribute 拖满 Playwright 默认 30 秒超时
            return {
                "type": "attribute_match",
                "layer": 3,
                "selector": selector,
                "attribute": attr,
                "expected": expected,
                "pass": False,
                "error": "元素不存在",
            }
        # 属性可能由前端异步写入（fetch 回调设 href/data-*、状态码回填），
        # 一次性读取会读到旧值产出确定性判档的假失败；比照 text_match 做
        # deadline 轮询，超时仍不等再判 fail。
        # 数值参数预校验（同 text_match 口径）：非数值 timeout/interval 会让
        # int() 在方法体内抛 ValueError/TypeError，被 run() 包装成无 selector
        # 的「断言执行异常」，进轮询前显式失败。
        timeout_ms = self._int_or_none(a.get("timeout", 3000))
        interval_ms = self._int_or_none(a.get("interval", 200))
        if timeout_ms is None or interval_ms is None:
            bad_param = "timeout" if timeout_ms is None else "interval"
            return {
                "type": "attribute_match",
                "layer": 3,
                "selector": selector,
                "attribute": attr,
                "expected": expected,
                "pass": False,
                "error": f"非法 {bad_param}: {a.get(bad_param)!r}，须为数值（毫秒）",
            }
        # 越界钳制（同 text_match 口径）
        timeout_ms, interval_ms, clamp_note = self._clamp_poll_params(
            timeout_ms, interval_ms
        )
        deadline = time.monotonic() + timeout_ms / 1000
        actual = None
        last_error = ""
        while True:
            try:
                # 单轮读取限时 interval_ms，避免定位/读取异常时按 Playwright
                # 默认 30 秒超时突破轮询预算（同 text_match 口径）。
                actual = await self._locator(page, selector).get_attribute(
                    attr, timeout=interval_ms
                )
            except Exception as e:
                last_error = str(e)
                # 读数异常复位为「未读到」哨兵 None（code-review item
                # 468eb3b7de90，同 text_match except 复位空串口径）：不复位则
                # actual 保留失败时刻之前最后一轮成功读取的旧值，元素已被
                # 移除等场景下结果展示的 actual 与元素当前状态无关；复位后
                # 失败时刻的 actual 语义明确。None 与 get_attribute 属性缺失
                # 的正常返回同形（结果结构不变），且 expected 预检保证为
                # str，复位值不会参与相等判定产生假 pass。
                actual = None
            if actual == expected:
                break
            if time.monotonic() >= deadline:
                break
            # 按剩余预算截断睡眠（code-review item 9ada803767ca，同 text_match
            # 口径，公共助手 _poll_interval_sleep）。
            await self._poll_interval_sleep(page, deadline, interval_ms)

        return {
            "type": "attribute_match",
            "layer": 3,
            "selector": selector,
            "attribute": attr,
            "expected": expected,
            "actual": actual,
            "pass": actual == expected,
            # 读数异常导致的失败附错误说明（同 text_match 口径）
            **({"error": last_error} if actual != expected and last_error else {}),
            **({"note": clamp_note} if clamp_note else {}),
        }

    async def _assert_no_console_error(self, page, a: dict) -> dict:
        """断言页面没有控制台错误。

        注意：console_errors 由 BrowserManager 在 context 生命周期中收集，
        通过 assertion 的 _console_errors 字段传入。

        外部 API 网络错误过滤：当场景声明 external_net_errors_ok 为 True（涉及
        外部 API 真实请求，如 timeapi.io / open-meteo），net::ERR_ 等网络层
        错误视为测试环境网络不可达（外部服务端/环境因素，非产品缺陷），
        从失败集合中过滤；其余控制台错误（含签名/认证类）仍严格失败。

        残余风险（code-review item a838fb53292c）：豁免按泛化子串 marker
        匹配，无法区分「外部第三方服务不可达」与「被测应用自身请求失败」
        ——应用自身接口宕机/5xx 时前端抛出的 "Failed to fetch"、应用自产
        错误文案含 "NetworkError" 字样（如 console.error('NetworkError when
        saving user')）同样被过滤出失败集合（假通过面，方向与第 1-3 层
        「0 误判」承诺相反——该承诺约束假失败）。场景 schema 只携带布尔
        external_net_errors_ok、无外部域名白名单字段，且存量场景依赖该豁免
        过滤自身有意 mock 的非 2xx 资源加载日志，故无法在本函数内收窄为
        「仅外部域」。被豁免条目的原始全文保留在结果 filtered_network 中，
        judge 归因时须复核其中是否混有应用自身缺陷。
        """
        errors = a.get("_console_errors", [])
        allow_network = a.get("_external_net_errors_ok", False)
        # 数据未注入标注（code-review item 796f7244820d）：注入键缺失（未来
        # 新 runner 直用 AssertionRunner、或 web_runner 注入段回归）时按空集
        # 处理会让断言恒 pass 且无任何「数据未注入」痕迹——静默假通过方向
        # 与模块头第 1-3 层「0 误判/确定性」承诺相反。以 injected 标志 + note
        # 透出供 judge 区分「确无错误」与「未检查」；不翻转 pass：无收集
        # 能力的 runner 变体下翻失败会把环境缺位误判为产品缺陷（假失败）。
        injected = "_console_errors" in a

        # 注入数据形态防御（code-review item 90b055a2072a）：键缺失已有上方
        # injected 标志防御，形态防御此前缺位——注入值非 list（新 runner 变体
        # 直用 AssertionRunner、web_runner 注入段回归）时下方 truncated 的
        # startswith 遍历与网络错误分拣遍历抛 TypeError/AttributeError，被
        # run() 统一包装成「断言执行异常」，error 归因是裸异常文本而非「注入
        # 数据形态非法」，judge 难以归因；进分拣前按确定性失败上报并注明。
        if not isinstance(errors, list):
            return {
                "type": "no_console_error",
                "layer": 3,
                "pass": False,
                "errors": [],
                "truncated": False,
                "filtered_network": [],
                "injected": injected,
                "error": (
                    f"注入数据形态非法: _console_errors 须为 list，"
                    f"实际 {type(errors).__name__}"
                ),
            }

        # 元素级类型归一（code-review item c70f6bf51b8f）：list 形态防御不
        # 覆盖元素类型——含非 str 元素（新 runner 变体或收集器回归写入
        # dict/int）时下方 startswith 遍历抛 AttributeError，被 run() 包装
        # 成裸异常文本的「断言执行异常」（正是上方防御注释要避免的归因
        # 形态）；归一为 str 后正常收集路径（恒产 str）逐元素原样保留，
        # 不翻转 pass 裁决，畸形条目保真转字符串参与过滤与透出。
        errors = [e if isinstance(e, str) else str(e) for e in errors]
        # 收集侧触顶截断标记（browser._capped_append）不计入 pass：
        # external_net_errors_ok 豁免路径上，纯网络层错误风暴被截断后
        # 标记若留在 errors 里会被误计为控制台错误（误报）
        truncated = any(e.startswith("[truncated]") for e in errors)
        if truncated:
            errors = [e for e in errors if not e.startswith("[truncated]")]

        filtered: list[str] = []
        if allow_network:
            # 网络层错误特征：浏览器网络栈失败 / 资源加载失败 / fetch 失败 / CORS 拦截
            network_markers = (
                "net::ERR_",
                "Failed to load resource",
                "Failed to fetch",
                "has been blocked by CORS policy",
                "NetworkError",
                "network error",
            )
            # 注意：不得重绑定 errors 后再遍历（会遍历空列表）；
            # 用推导式在原列表上分拣
            filtered = [e for e in errors if any(m in e for m in network_markers)]
            errors = [e for e in errors if not any(m in e for m in network_markers)]

        return {
            "type": "no_console_error",
            "layer": 3,
            "pass": len(errors) == 0,
            "errors": errors,
            "truncated": truncated,
            "filtered_network": filtered,
            "injected": injected,
            **(
                {
                    "note": "控制台错误收集器数据未注入"
                    "（_console_errors 键缺失），本检查未真正执行"
                }
                if not injected
                else {}
            ),
        }

    async def _assert_no_network_error(self, page, a: dict) -> dict:
        """断言没有4xx/5xx网络请求。

        注意：network_errors 由 BrowserManager 在 context 生命周期中收集，
        通过 assertion 的 _network_errors 字段传入。
        """
        errors = a.get("_network_errors", [])
        # 数据未注入标注（code-review item 796f7244820d，同 no_console_error
        # 口径）：注入键缺失时按空集静默判 pass 是 fail-open 方向，以
        # injected 标志 + note 透出供 judge 区分「确无错误」与「未检查」。
        injected = "_network_errors" in a
        # 注入数据形态防御（code-review item 90b055a2072a，同 no_console_error
        # 口径）：注入值非 list 时下方 truncated 的 startswith 遍历抛
        # TypeError，被 run() 包装成裸异常文本的「断言执行异常」，进分拣前
        # 按确定性失败上报并注明注入形态非法。
        if not isinstance(errors, list):
            return {
                "type": "no_network_error",
                "layer": 3,
                "pass": False,
                "errors": [],
                "truncated": False,
                "injected": injected,
                "error": (
                    f"注入数据形态非法: _network_errors 须为 list，"
                    f"实际 {type(errors).__name__}"
                ),
            }
        # 元素级类型归一（code-review item c70f6bf51b8f，同 no_console_error
        # 口径）：list 形态防御不覆盖元素类型——含非 str 元素时下方
        # startswith 遍历抛 AttributeError，被 run() 包装成裸异常文本的
        # 「断言执行异常」；归一为 str 后正常收集路径逐元素原样保留，
        # 不翻转 pass 裁决，畸形条目保真转字符串参与过滤与透出。
        errors = [e if isinstance(e, str) else str(e) for e in errors]
        # 收集侧触顶截断标记（browser._capped_append）不计入 errors：标记是
        # 「后续还有错误被截断」的信号而非真实 4xx/5xx 记录，与 console 侧
        # （_assert_no_console_error）同口径剔除并以 truncated 标志透出
        # （code-review item 58ce31605491），judge 读错误清单不再混入标记条目
        truncated = any(e.startswith("[truncated]") for e in errors)
        if truncated:
            errors = [e for e in errors if not e.startswith("[truncated]")]
        return {
            "type": "no_network_error",
            "layer": 3,
            "pass": len(errors) == 0,
            "errors": errors,
            "truncated": truncated,
            "injected": injected,
            **(
                {
                    "note": "网络错误收集器数据未注入"
                    "（_network_errors 键缺失），本检查未真正执行"
                }
                if not injected
                else {}
            ),
        }

    async def _assert_no_auth_error(self, page, a: dict) -> dict:
        """断言页面未出现密钥/签名/认证类错误。

        检查页面正文文本是否包含「签名验证失败」「认证失败」
        「InvalidAccessKeyId」「SignatureDoesNotMatch」等关键词，
        用于捕获真实云端下载/上传时的密钥错误——这类「数据加解密/签名
        正确性」问题无法通过纯 UI 断言覆盖，需要真实触发网络请求后检查
        错误提示。

        口径说明（code-review item 4a34b869d479）：关键词子串命中本质是
        启发式，曾含「Access Key」「Secret Key」「AccessKey」「SecretKey」
        等泛化词，云凭证表单字段标签、密钥管理页、帮助文档等合法展示这些
        文案的页面会被误判为认证错误，与模块头第1-3层「0误判」承诺冲突。
        现收窄为高置信错误形态（完整错误码/错误句式）。层归属按词表映射
        仍为第3层（scenarios.py WEB_ASSERTION_LAYERS），收窄后的残余
        启发式风险按第4层口径由 judge 结合上下文复核。
        """
        keywords = [
            "签名验证失败",
            "认证失败",
            "SignatureDoesNotMatch",
            "InvalidAccessKeyId",
            # 不收录前缀形态 "InvalidAccessKey"：它是 InvalidAccessKeyId 的
            # 子串，同页命中时 matched 会出现两条同源记录（双计）。
        ]
        try:
            body_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception as e:
            # 正文不可读（页面崩溃/跳转中/上下文关闭）时不得兜底为空串判
            # pass：matched 恒为空会让认证类错误检查被静默跳过且无任何
            # error 标注，judge 无从得知检查未真正执行；比照模块其余断言
            # 「元素/数据缺失一律显式失败」的 fail-closed 口径显式失败
            # （code-review item 48e41871df44）。
            return {
                "type": "no_auth_error",
                "layer": 3,
                "pass": False,
                "matched": [],
                "error": f"页面正文读取失败，无法检查认证错误文案: {e}",
            }
        matched = [k for k in keywords if k in body_text]
        return {
            "type": "no_auth_error",
            "layer": 3,
            "pass": len(matched) == 0,
            "matched": matched,
        }

    async def _assert_dom_structure(self, page, a: dict) -> dict:
        """断言DOM结构关系（父子/包含）。"""
        parent_sel = a.get("parent", "")
        child_sel = a.get("child", "")
        relation = a.get("relation", "contains")  # contains | direct-child

        if not parent_sel or not child_sel:
            # 显式失败而非静默兜底：空选择器拼进 locator 会让 count() 抛错，
            # 被 run() 包成「断言执行异常」无法定位场景缺参，与 z_index_order
            # 的缺参口径（确定性失败）保持一致。
            return {
                "type": "dom_structure",
                "layer": 3,
                "parent": parent_sel,
                "child": child_sel,
                "relation": relation,
                "count": 0,
                "pass": False,
                "error": "缺少 parent 字段" if not parent_sel else "缺少 child 字段",
            }

        if relation == "contains":
            locator_str = f"{parent_sel} {child_sel}"
        elif relation == "direct-child":
            locator_str = f"{parent_sel} > {child_sel}"
        else:
            # 非法 relation 显式可见化（与 z_index_order 非法 operator、
            # text_match 非法 mode 口径对齐）：裸失败会让 judge 把 planner
            # 配置错误误归因为产品缺陷
            return {
                "type": "dom_structure",
                "layer": 3,
                "parent": parent_sel,
                "child": child_sel,
                "relation": relation,
                "count": 0,
                "pass": False,
                "error": f"非法 relation: {relation!r}，仅支持 contains/direct-child",
            }

        # 拼接片段可能无法被选择器引擎解析（code-review item 811c5b6c700e）：
        # planner 误写 text=/xpath= 等引擎语法或空格敏感片段时 count() 抛错
        # 会穿透到 run() 的通用 except，结果只带 assertion.get("selector","")
        # ——dom_structure 用的是 parent/child 键，定位上下文全丢；比照上方
        # 非法 relation 分支的 dict 形态返回带 parent/child/relation 的确定
        # 性失败，与同文件「缺参/非法参数进匹配前显式失败」口径一致。
        try:
            count = await page.locator(locator_str).count()
        except Exception as e:
            return {
                "type": "dom_structure",
                "layer": 3,
                "parent": parent_sel,
                "child": child_sel,
                "relation": relation,
                "count": 0,
                "pass": False,
                "error": f"选择器拼接无法解析: {e}",
            }
        passed = count > 0

        return {
            "type": "dom_structure",
            "layer": 3,
            "parent": parent_sel,
            "child": child_sel,
            "relation": relation,
            "count": count,
            "pass": passed,
        }

    # ═══════════════════════════════════════════════════════════════
    # 第4层：布局完整性（启发式，需阈值）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_no_overflow(self, page, a: dict) -> dict:
        """断言元素内容不溢出容器边界。"""
        selector = a["selector"]
        overflow_info = await self._safe_evaluate(
            page,
            selector,
            """el => {
            // display:none 等隐藏元素 getBoundingClientRect 与
            // scrollWidth/clientWidth 全为零，溢出不等式恒为 false，恒判
            // 「无溢出」是无信息量的假通过；zero_size 标记交 Python 侧
            // 显式失败（与 no_overlap / in_viewport 零尺寸口径一致）
            if (el.clientWidth === 0 && el.clientHeight === 0) {
                return { zero_size: true };
            }
            return {
                zero_size: false,
                has_horizontal_overflow: el.scrollWidth > el.clientWidth + 1,
                has_vertical_overflow: el.scrollHeight > el.clientHeight + 1,
                scroll_width: el.scrollWidth,
                client_width: el.clientWidth,
                scroll_height: el.scrollHeight,
                client_height: el.clientHeight,
            };
        }""",
        )
        if overflow_info is None:
            return {
                "type": "no_overflow",
                "layer": 4,
                "selector": selector,
                "pass": False,
                "error": "元素不存在",
            }
        if isinstance(overflow_info, dict) and overflow_info.get("zero_size", False):
            # 零尺寸/隐藏目标的溢出比较恒判「无溢出」是无信息量的假通过，
            # 显式失败供 judge 区分「确无溢出」与「目标根本不可见」。
            return {
                "type": "no_overflow",
                "layer": 4,
                "selector": selector,
                "pass": False,
                "error": "元素存在但零尺寸（如 display:none / 隐藏），溢出检查无意义，不视为通过",
            }
        passed = (
            not overflow_info["has_horizontal_overflow"]
            and not overflow_info["has_vertical_overflow"]
        )
        return {
            "type": "no_overflow",
            "layer": 4,
            "selector": selector,
            "pass": passed,
            "overflow_info": overflow_info,
        }

    async def _assert_alignment(self, page, a: dict) -> dict:
        """断言同组元素对齐一致性（同一轴上坐标差异在容差内）。

        extra参数:
            axis: left | top，默认 left
            tolerance: 像素容差，默认 2px
        """
        selector = a["selector"]
        axis = a.get("axis", "left")
        if axis not in ("left", "top"):
            # 确定性失败而非 KeyError：非法轴名直接给出可定位的提示，
            # 避免被 run() 包装成无上下文的「断言执行异常」。
            return {
                "type": "alignment",
                "layer": 4,
                "selector": selector,
                "axis": axis,
                "pass": False,
                "error": f"非法 axis: {axis!r}，仅支持 left/top",
            }
        try:
            tolerance = float(a.get("tolerance", 2))
        except (TypeError, ValueError):
            # 非数值容差按确定性失败上报而非静默回退默认 2.0：配置错误被
            # 吞掉后断言按非本意阈值裁决，与上方非法 axis、z_index_order
            # 非法 operator 的确定性失败口径一致，给出可定位提示。
            return {
                "type": "alignment",
                "layer": 4,
                "selector": selector,
                "axis": axis,
                "tolerance": a.get("tolerance"),
                "pass": False,
                "error": f"非法 tolerance: {a.get('tolerance')!r}，须为数值（像素）",
            }
        if not math.isfinite(tolerance) or tolerance < 0:
            # NaN/负数/无穷大同款拦截（与 no_overlap threshold 的区间校验
            # 对称，有限性口径对齐 scenarios 步骤 timeout 的 isfinite 拦截，
            # code-review item c9cab59b862c）：NaN 使 max_diff <= tolerance
            # 恒 False（任何对齐都判失败）、负值恒失败、inf 恒通过，均产出
            # 方向不明且无提示的裁决，进取数前显式失败。
            return {
                "type": "alignment",
                "layer": 4,
                "selector": selector,
                "axis": axis,
                "tolerance": a.get("tolerance"),
                "pass": False,
                "error": f"非法 tolerance: {a.get('tolerance')!r}，"
                f"须为非负有限数值（像素）",
            }

        if not await self._element_exists(page, selector):
            return {
                "type": "alignment",
                "layer": 4,
                "selector": selector,
                "pass": False,
                "error": "元素不存在",
            }

        positions = await page.locator(selector).evaluate_all("""els => {
            return els.map(el => {
                const r = el.getBoundingClientRect();
                return { left: r.left, top: r.top };
            });
        }""")

        if not positions:
            # 空列表按「元素不存在」确定性失败（code-review item 970974a19cd9）：
            # 存在性预检通过后、evaluate_all 执行前的竞态窗口内元素被全部移除
            # （或存在性检查读到瞬态节点后未落地）时，此前会落入下方跳过分支
            # 按 pass 收场，漏检「列表未渲染/行全消失」类回归；与同文件其余
            # DOM 断言对元素缺失一律显式失败的口径一致。
            return {
                "type": "alignment",
                "layer": 4,
                "selector": selector,
                "pass": False,
                "error": "元素不存在",
            }

        if len(positions) < 2:
            return {
                "type": "alignment",
                "layer": 4,
                "selector": selector,
                "pass": True,
                "note": "仅1个元素，跳过对齐检查",
            }

        values = [p[axis] for p in positions]
        max_diff = max(values) - min(values)
        passed = max_diff <= tolerance

        return {
            "type": "alignment",
            "layer": 4,
            "selector": selector,
            "axis": axis,
            "values": values,
            "max_diff": max_diff,
            "tolerance": tolerance,
            "pass": passed,
        }
