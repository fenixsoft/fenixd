# v2 数据适配层

<!-- knowledge: capability=v2-data-adapters rev=1
     sources=spec/archive/2026-09-05-v2-data-adapters -->

后端 API JSON 到 AMIS/视图模型的纯函数适配集：生命周期排序、fix 树分组、三级回退与链校验。

## 规则

- 适配层为纯函数集（UMD 模块：浏览器挂 `window.Adapters`，node 直接 require），10 个导出：`SPEC_LIFECYCLE`、`adaptSpecs`、`adaptOverview`、`adaptProjects`、`adaptSpecDetail`、`adaptAlerts`、`adaptActivities`、`adaptConfig`、`buildConfigPayload`、`validateChain`；字段映射以后端 `/api/*` 响应为唯一输入、字段名与视图模型逐字对齐。
- `adaptSpecs`：输出行按 `SPEC_LIFECYCLE` 生命周期序严格升序排序；`fix-<父名>` 前缀行归入对应父行的 children（树行，子行含 `isFixChild:true`），父行聚合子任务进度。
- 计数字段数字化：`adaptOverview`/`adaptSpecDetail` 对所有计数字段 `Number()` 归一（NaN→0），兼容服务端输出字符串 `"0"` 的形态。
- 配置适配：`adaptConfig` 对缺失 llm 键兜底 `{providers: []}`；`buildConfigPayload(form, snapshot, defaults)` 对数字字段按「表单空/NaN → snapshot → defaults」三级回退合并。
- `validateChain(chainValue, providers)` 校验链完整性：必填角色齐全且模型名存在于 provider，否则返回错误文案（非 true）。
- 配 node 单测（`tests/v2/adapters.test.mjs`）与真实 API 响应样本 fixtures，纯函数逻辑在 node 侧可独立验证。
- 能力退役注记：v2 壳已移除（根路由 302 重定向到 v3），适配层不再被现行前端消费，本页规则仅供追溯（`tests/v2/` 单测仍留存）。

## 溯源

- 史前复原 — v2 数据适配为纯函数层：后端 JSON 与视图模型双向映射（adaptConfig 展开/收编 models 链），配 node 单测
- 2026-09-05 2026-09-05-v2-data-adapters — 落地 10 导出适配纯函数（生命周期排序、fix 树分组、计数字段归一、三级回退、链校验）与 node 单测/fixtures
- 2026-09-02 git:ea88dd5a — v1/v2 dashboard 壳整体移除，适配层随壳退役
