# 场景交互后网络请求断言

<!-- knowledge: capability=scenario-network-assertion rev=1
     sources=spec/archive/2026-10-30-add-mechanical-scenario-refetch-assertion -->

verify_engine web 场景的交互步骤可携带 `expect_network` 网络请求断言：引擎在该步骤执行窗口内收集网络请求并断言「交互确实触发了数据重拉取」，使「点了但没拉数据」类缺陷可被机械验证暴露与回归锁定（此类缺陷只能靠昂贵的 LLM 验证轮偶然发现，机械验证不得对其结构性失明）。

## 规则

- **字段挂交互步骤，与操作同对象**：形态 `[{"url_pattern": <非空字符串>, "min_count": <正整数>}]`，不设独立的 `expect_network` 步骤 op。只有交互步骤可携带——交互/非交互以显式集合收口（交互 = click/type/clear/select/scroll/hover/drag/contextmenu/dialog；非交互 = navigate/wait/seed/mock_api）；非交互步骤携带该字段在场景验收期拒绝（错误逐条指向该步骤），不进运行时。
- **监听窗口 = 该步骤执行起止**：挂 playwright `request` 事件收集（请求发起即计，响应失败或挂起也算「发了请求」）→ 执行操作 → 静默收窗 → 逐项断言。交互本身失败时按步骤原失败返回，不再叠加网络断言明细混淆归因。
- **静默收窗，禁用 networkidle**：收窗以固定短静默窗判定——单轮 300ms 连续无新请求即收窗，总时长封顶 1500ms（常驻 SSE/高频轮询页面的请求流可能贯穿整个窗口、静默永不到来，封顶防单步骤空等放大）；超封顶按当前捕获即收窗断言。MUST NOT 使用 `wait_for_load_state("networkidle")`——本仓库页面常驻 SSE，networkidle 永不满足。漏计方向只产生「该过的场景失败」的保守偏差，不产生假通过。
- **URL 模式匹配与形态定义单点**：url_pattern 默认纯子串匹配，`re:` 前缀按正则 search；匹配函数与字段形态定义单点收口于 scenarios.py，验收校验与引擎断言共用同一口径（该单点不放 assertions.py——后者顶层 import scenarios 模块，反向依赖成环）。
- **失败计入场景 fail（产品归因）**：明细结构与其他断言一致（type/message），message 含「期望 ≥N 实际 M」计数、窗口捕获总数与至多 3 条去重样例 URL（零匹配时样例为空提示）；记录随步骤结果 `network_assertions` 键落报告，不做新的失败分类。字段坏档（直构绕过验收的残档）按该项失败收场，不给「坏档 = 无断言 = 通过」留假通过通道。
- **验收形态校验**：url_pattern 须为非空字符串（`re:` 正则体非空且可编译）、min_count 须为正整数（bool 不算），非法形态走既有验收错误通道逐条报错；min_count > 3 落 WARNING 提示但不拒绝（稳健用法引导：端点子串 + min_count: 1），不制造新拒绝模式。
- **解析回环保真**：expect_network 是 TestStep 规范字段，from_dict 解析 + to_dict 回环逐字段保真；解析层不清洗不丢键，形态校验在验收期单点进行。
- **契约与实现同源**：planner 出题契约段（agents/planner-plan.md）声明该能力与最小示例（click 筛选 → `[{url_pattern: "/api/command-center/pipeline", min_count: 1}]`，注明稳健用法）；契约段示例形态必须实际通过引擎验收，防契约文档与实现漂移。
- **范围边界**：不做请求体/响应体内容断言（响应体断言是 api_assertions 既有辖域）；不做全场景级网络快照（只做步骤窗口级，避免跨步骤请求归因歧义）；引擎不做背景请求过滤——静默轮询等背景请求由场景作者以精确端点子串区分；无 expect_network 的步骤行为逐位不变。

## 溯源

- 2026-10-30 add-mechanical-scenario-refetch-assertion（spec/archive/2026-10-30-add-mechanical-scenario-refetch-assertion） — 新增本能力：交互步骤 expect_network 网络断言（request 事件窗口收集 + 静默收窗 + 逐项断言与样例明细）、验收形态校验单点与交互/非交互显式集、TestStep 字段回环、planner 契约声明与示例同源校验（动因：command-center 筛选切换 0 新请求滞留 60s 的缺陷在机械场景套件中结构性不可见，LLM 验证轮发现后无法回归锁定）
