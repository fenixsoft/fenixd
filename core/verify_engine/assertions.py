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

import re
import time
from typing import Any


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

    # ── 断言执行入口 ──────────────────────────────────────────

    async def run(self, page, assertions: list[dict]) -> list[dict]:
        """执行断言列表，返回每个断言的结果。"""
        results: list[dict] = []
        for assertion in assertions:
            a_type = assertion.get("type", "")
            handler_name = f"_assert_{a_type}"
            handler = getattr(self, handler_name, None)
            if handler:
                try:
                    result = await handler(page, assertion)
                    result.setdefault("type", a_type)
                    result.setdefault("layer", 0)
                    results.append(result)
                except Exception as e:
                    results.append(
                        {
                            "type": a_type,
                            "layer": 0,
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
        expected = int(a.get("count", a.get("expected", 1)))
        locator = page.locator(selector)
        # [fenix-ignore:87212a1756aa] 条目基于旧时点代码：此处已非瞬时一次性读数，不等时按 element_not_exist 同款 10 次×300ms 轮询收敛
        actual = await locator.count()
        if actual != expected:
            for _ in range(10):
                await page.wait_for_timeout(300)
                actual = await locator.count()
                if actual == expected:
                    break
        return {
            "type": "element_count",
            "layer": 1,
            "selector": selector,
            "expected": expected,
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
            "actual_count": count,
            "pass": count == 0,
        }

    async def _assert_element_focused(self, page, a: dict) -> dict:
        """断言元素获得焦点。"""
        selector = a["selector"]
        focused = await self._safe_evaluate(page, selector, "el => el === document.activeElement")
        return {
            "type": "element_focused",
            "layer": 1,
            "selector": selector,
            "pass": focused is True,
        }

    async def _assert_element_enabled(self, page, a: dict) -> dict:
        """断言元素可交互（非disabled状态）。"""
        selector = a["selector"]
        if not await self._element_exists(page, selector):
            return {
                "type": "element_enabled",
                "layer": 1,
                "selector": selector,
                "pass": False,
                "error": "元素不存在",
            }
        enabled = await self._locator(page, selector).is_enabled()
        return {
            "type": "element_enabled",
            "layer": 1,
            "selector": selector,
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
            if "intercepts pointer events" in error_msg:
                try:
                    intercept_detail = await page.evaluate(
                        """(sel) => {
                            const el = document.querySelector(sel);
                            if (!el) return null;
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
                        }""",
                        selector,
                    )
                except Exception:
                    pass  # 拦截详情提取失败不阻塞主流程

            return {
                "type": "no_click_interception",
                "layer": 2,
                "selector": selector,
                "label": a.get("label", ""),
                "pass": False,
                "error": error_msg,
                "intercept_detail": intercept_detail,
            }

    async def _assert_no_overlap(self, page, a: dict) -> dict:
        """断言目标元素不与同级元素发生超过阈值的重叠。

        通过 getBoundingClientRect 计算交集面积比例。
        """
        selector = a["selector"]
        threshold = a.get("threshold", 0.2)

        overlaps = await self._safe_evaluate(
            page,
            selector,
            """(el, threshold) => {
                const rect = el.getBoundingClientRect();
                const parent = el.parentElement;
                if (!parent) return [];
                const siblings = [...parent.children].filter(c => c !== el);
                const targetArea = rect.width * rect.height;
                if (targetArea === 0) return [];

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
                            sibling_class: sib.className?.split(' ')[0] || '',
                            overlap_ratio: Math.round(ratio * 100) / 100,
                            sibling_z_index: getComputedStyle(sib).zIndex,
                        });
                    }
                }
                return results;
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
        return {
            "type": "no_overlap",
            "layer": 2,
            "selector": selector,
            "threshold": threshold,
            "pass": len(overlaps) == 0,
            "overlaps": overlaps,
        }

    async def _assert_in_viewport(self, page, a: dict) -> dict:
        """断言元素在可视区域内。"""
        selector = a["selector"]
        in_view = await self._safe_evaluate(
            page,
            selector,
            """el => {
            const rect = el.getBoundingClientRect();
            return (
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= window.innerHeight &&
                rect.right <= window.innerWidth
            );
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
        return {
            "type": "in_viewport",
            "layer": 2,
            "selector": selector,
            "pass": in_view,
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

        if compare_selector and not await self._element_exists(page, compare_selector):
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
        z1 = z1_result if z1_result is not None else 0
        z2 = z2_result if z2_result is not None else 0

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

    def _text_matches(self, actual: str, expected: str, mode: str) -> bool:
        """按 mode 判断文本是否匹配。"""
        if mode == "exact":
            return actual.strip() == expected.strip()
        if mode == "contains":
            return expected in actual
        if mode == "regex":
            return bool(re.search(expected, actual))
        return False

    async def _assert_text_match(self, page, a: dict) -> dict:
        """断言元素文字内容匹配。

        mode: exact（精确）/ contains（包含）/ regex（正则）
        对 input/textarea 元素自动使用 value 属性（而非 textContent）。

        与 element_visible 一致，带等待/重试：异步渲染（如 WebCrypto 密码
        哈希 + 密钥加密的用户创建流程）完成后 DOM 才更新，一次性读取会
        读到旧值，因此轮询到超时为止。
        """
        selector = a["selector"]
        expected = a.get("expected", "")
        mode = a.get("mode", "exact")
        timeout_ms = int(a.get("timeout", 3000))
        interval_ms = int(a.get("interval", 200))

        # 非法正则是确定性错误：_text_matches 内 re.search 每轮重抛 re.error，
        # 会被下方 except 当作「元素尚未渲染」的临时态空转至超时，故进轮询前预检。
        if mode == "regex":
            try:
                re.compile(expected)
            except re.error as e:
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

        deadline = time.monotonic() + timeout_ms / 1000
        actual = ""
        passed = False
        last_error = ""

        while True:
            try:
                # input/textarea 元素使用 value 属性
                tag = await self._locator(page, selector).evaluate(
                    "el => el.tagName?.toLowerCase()"
                )
                if tag in ("input", "textarea", "select"):
                    actual = (await self._locator(page, selector).input_value()) or ""
                else:
                    actual = (await self._locator(page, selector).text_content()) or ""

                passed = self._text_matches(actual, expected, mode)
                if passed:
                    break
            except Exception as e:
                # 元素尚未渲染/不可读时继续重试
                last_error = str(e)
                actual = ""

            if time.monotonic() >= deadline:
                break
            await page.wait_for_timeout(interval_ms)

        return {
            "type": "text_match",
            "layer": 3,
            "selector": selector,
            "expected": expected,
            "actual": actual.strip(),
            "mode": mode,
            "pass": passed,
            **({"error": last_error} if not passed and last_error else {}),
        }

    async def _assert_text_contains(self, page, a: dict) -> dict:
        """断言页面某处包含指定文本。

        支持两种字段名: text 或 expected。
        如果提供了 selector，则在指定的任意一个匹配元素内查找文本。
        """
        text = a.get("text") or a.get("expected", "")
        selector = a.get("selector", "")

        if selector:
            # 等待至少一个匹配元素出现（容忍尚未渲染的情况），再检查全部匹配
            try:
                await page.locator(selector).first.wait_for(state="attached", timeout=3000)
            except Exception:
                pass
            try:
                texts = await page.locator(selector).all_text_contents()
                passed = any(text in (t or "") for t in texts)
            except Exception:
                passed = False
        else:
            # 在整个页面中查找文本。
            # 优先按可见文本匹配（get_by_text 不计入 <script>/<style> 内容，
            # HTML 注释与属性值也天然不参与），避免 React/umi 等把数据内嵌
            # 在 <script> 里的产物页命中脚本字符串造成假通过；
            # 无 get_by_text 的环境（stub 页面等）降级回 page.content()
            # 原始 HTML 子串匹配——该保底路径存在 script/注释误判可能。
            try:
                passed = await page.get_by_text(text).count() > 0
            except Exception:
                content = await page.content()
                passed = text in content

        return {
            "type": "text_contains",
            "layer": 3,
            "text": text,
            "pass": passed,
        }

    async def _assert_attribute_match(self, page, a: dict) -> dict:
        """断言元素属性值等于期望值。"""
        selector = a["selector"]
        attr = a.get("attribute", "")
        expected = a.get("expected", "")
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
        actual = await self._locator(page, selector).get_attribute(attr)
        return {
            "type": "attribute_match",
            "layer": 3,
            "selector": selector,
            "attribute": attr,
            "expected": expected,
            "actual": actual,
            "pass": actual == expected,
        }

    async def _assert_no_console_error(self, page, a: dict) -> dict:
        """断言页面没有控制台错误。

        注意：console_errors 由 BrowserManager 在 context 生命周期中收集，
        通过 assertion 的 _console_errors 字段传入。

        外部 API 网络错误过滤：当场景声明 external_net_errors_ok 为 True（涉及
        外部 API 真实请求，如 timeapi.io / open-meteo），net::ERR_ 等网络层
        错误视为测试环境网络不可达（外部服务端/环境因素，非产品缺陷），
        从失败集合中过滤；其余控制台错误（含签名/认证类）仍严格失败。
        """
        errors = a.get("_console_errors", [])
        allow_network = a.get("_external_net_errors_ok", False)

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
            "filtered_network": filtered,
        }

    async def _assert_no_network_error(self, page, a: dict) -> dict:
        """断言没有4xx/5xx网络请求。

        注意：network_errors 由 BrowserManager 在 context 生命周期中收集，
        通过 assertion 的 _network_errors 字段传入。
        """
        errors = a.get("_network_errors", [])
        return {
            "type": "no_network_error",
            "layer": 3,
            "pass": len(errors) == 0,
            "errors": errors,
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
            "InvalidAccessKey",
        ]
        try:
            body_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            body_text = ""
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
            count = await page.locator(f"{parent_sel} {child_sel}").count()
            passed = count > 0
        elif relation == "direct-child":
            count = await page.locator(f"{parent_sel} > {child_sel}").count()
            passed = count > 0
        else:
            passed = False
            count = 0

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
            return {
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
            # 非数值容差回退默认值，避免在比较处抛 TypeError。
            tolerance = 2.0

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

        if len(positions) < 2:
            return {
                "type": "alignment",
                "layer": 4,
                "selector": selector,
                "pass": True,
                "note": "少于2个元素，跳过对齐检查",
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
