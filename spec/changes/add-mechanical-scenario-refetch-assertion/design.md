# Design: add-mechanical-scenario-refetch-assertion

## Context

verify_engine 的 web 场景步骤操作白名单（「未知操作 'xxx'，支持: clear, click, contextmenu, dialog, drag, hover」验收错误的来源，`grep -rn "未知操作" core/verify_engine/` 定位注册结构）只描述页面操作，无网络层断言。现有断言器（assertions.py/api_assertions.py）面向页面态与 API 响应体，无「步骤执行窗口内网络行为」维度。BUG-1 实证缺口：LLM 轮借 performance 网络日志发现筛选切换 0 请求，机械轮的筛选场景只能断言 UI 回显——缺陷在机械验证中不可见、不可回归。

playwright 侧能力现成：page.on("request"/"response") 事件流可在步骤窗口收集请求 URL。

## Goals / Non-Goals

**Goals:**
- 「交互后应发请求而未发」类缺陷机械可暴露、可回归锁定
- 契约校验、引擎执行、planner 契约三处一致放行

**Non-Goals:**
- 不做请求体/响应体内容断言（只做 URL 模式 + 计数；响应体断言是 api_assertions 既有辖域）
- 不做全场景级网络快照（只做步骤窗口级，避免跨步骤请求归因歧义）
- 不改既有操作白名单内步骤的行为语义

## Decisions

- **D1 字段挂在交互步骤上而非独立新 op**：`{click: ..., expect_network: [...]}` 与操作同对象，监听窗口=该步骤执行起止。独立 op（如 `expect_network:` 单独步骤）存在窗口歧义（上一操作的请求可能落入），挂步骤上语义精确。
- **D2 收集实现**：browser.py 步骤执行器在带 expect_network 的步骤前后挂 playwright response 事件监听（request URL 匹配子串或 re.search），窗口结束即断言。URL 匹配支持纯子串（默认）与 `re:` 前缀正则，与既有断言器风格对齐。
- **D3 契约校验三处同源**：白名单注册点新增 expect_network 的形态校验（非交互步骤携带→验收拒绝；形态非法→逐条报错），校验函数与引擎断言共用同一形态定义（单点，防校验/执行漂移）。交互/非交互判据落为显式集合（收口于 scenarios.py：`_validate_web` 与 WEB_ACTIONS 旁新增交互集）：交互 = click/type/clear/select/scroll/hover/drag/contextmenu/dialog；非交互 = navigate/wait/seed/mock_api——消除 spec「click/hover/contextmenu 等」的「等」字歧义，防验收与实现各自解释漂移。
- **D4 planner 契约段更新遵循既有口径**：agents/*.md 契约段补一句能力声明 + 最小示例；按「改 prompt 先 merge main」既有处方执行（fix 链落分支时契约段先并 main）。
- **D5 失败归因**：断言失败计入场景 fail（产品归因），明细结构与其他断言一致（type/message），不做新的失败分类。

## Risks / Trade-offs

- **监听窗口竞态**：请求在步骤标记完成后 50-100ms 才入栈的尾部请求可能漏计——窗口结束用**固定短静默窗（约 300ms，单测钉死）**——MUST NOT 用 `wait_for_load_state("networkidle")`：本仓库页面常驻 SSE、networkidle 永不满足，browser.py 文件头设计决策已明确移除该等待（评审实测 browser.py:8），短超时形式也只沦为每步固定空等且与既有决策相悖；漏计方向只影响「该过的场景失败」（保守方向），不产生假通过。
- **轮询干扰**：60s 静默轮询场景与交互断言窗口重叠可能误计背景请求——url_pattern 由场景作者精确到筛选端点路径区分，文档示例示范；引擎不做背景请求过滤（保持机制简单）。
- **planner 滥用新字段**：出题产出过多/过严的 expect_network 导致场景易碎——契约示例给「min_count: 1 + 端点子串」的稳健形态，验收对 min_count > 3 给 WARNING 提示。
