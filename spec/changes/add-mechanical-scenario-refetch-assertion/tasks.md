## Deliverables

```yaml
- path: core/verify_engine/browser.py
  kind: modify
- path: core/verify_engine/assertions.py
  kind: modify
- path: core/verify_engine/scenarios.py
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: tests/test_verify_engine_network_assertion.py
  kind: new
```

## 1. 引擎执行能力

- [ ] 1.1 `core/verify_engine/browser.py`：交互步骤支持 `expect_network`（步骤窗口内 playwright response/request 事件收集，URL 子串或 `re:` 前缀正则匹配，min_count 断言）；窗口收尾含网络静默等待（固定短超时，防尾部请求漏计——保守方向只允许「该过判失败」不允许假通过）；失败明细含期望/实际计数与至多 3 条样例 URL，计入场景 fail；配套 `core/verify_engine/scenarios.py` TestStep 新增 `expect_network` 规范字段（from_dict 解析 + to_dict 回环序列化）——评审实测 from_dict 显式构造全部字段、TestStep 无 extra 字段，不补模型字段则该键在解析层被静默丢弃、引擎不可见
- [ ] 1.2 单测（tests/test_verify_engine_network_assertion.py 新建）：①窗口内 1 个匹配请求 → 通过；②零匹配 → fail 且明细含「期望 ≥1 实际 0」；③窗口尾部静默等待生效（延迟请求不漏计）；④非匹配 URL 不计入

## 2. 契约校验白名单

- [ ] 2.1 场景验收（「未知操作，支持: …」白名单所在校验段）：expect_network 形态校验单点（与引擎断言共用形态定义）——url_pattern 非空、min_count 正整数、非交互步骤携带 → 验收拒绝逐条报错；min_count > 3 → 验收 WARNING
- [ ] 2.2 单测：①合法形态过验收；②非交互步骤携带被拒；③非法形态逐条报错；④min_count>3 落 WARNING 不拒绝

## 3. planner 契约声明

- [ ] 3.1 `agents/planner-plan.md` 契约段补 expect_network 能力声明与最小示例（click 筛选 → `[{url_pattern: "/api/command-center/pipeline", min_count: 1}]`），注明稳健用法（端点子串 + min_count: 1）
- [ ] 3.2 契约示例过引擎验收（示例场景作为验收用例跑通，防契约与实现漂移）

## 4. 回归

- [ ] 4.1 既有 verify_engine 场景执行/验收用例全绿（无 expect_network 的场景行为逐位不变）
