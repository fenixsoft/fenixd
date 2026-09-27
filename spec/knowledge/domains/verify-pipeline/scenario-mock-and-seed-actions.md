<!-- knowledge: capability=scenario-mock-and-seed-actions rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 场景 seed 与 mock 动作

验证场景支持 `seed` 与 `mock_api` 两类特殊动作，用于预置状态与离线模拟外部 API。

## 现行规则

- `seed`：target 是 localStorage 键（非 CSS 选择器），执行时写入 localStorage 后整页重载；重载后的首帧渲染等待与 navigate 分支同口径。
- `mock_api`：按 URL 模式拦截请求并返回固定 JSON，使依赖外部 API 的场景可离线验证。
- mock 隔离：注册首个 `mock_api` 时一并拦截同页 SSE——活体推流会绕过已 mock 的 REST 路由，把场景 DOM 污染成真实数据（SSE route 持久于 page，须显式阻断）。
- mock 状态码语义：状态码取场景声明的 `status` 字段并做 `int()` 强转，非法值结构化失败（不静默回退）；4xx/5xx 场景必须按声明失败返回，禁止一律按 200 成功处理。
- target 语义按动作分流：通用操作用 web 语义（CSS 选择器）；`mock_api` 的 target 为 URL 模式；`seed` 的 target 为 localStorage 键。需要 target 的动作集合与不需要的集合在场景结构中显式登记。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
