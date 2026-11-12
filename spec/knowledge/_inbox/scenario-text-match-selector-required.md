# inbox：text_match 断言 selector 必填 + 场景校验静默吞错形态

- **能力域**：verify-pipeline（场景 schema 校验与消费面）
- **类型**：排查结论（2026-11-12，add-arbiter-blacklist-disposition 6.3 测试调试中实锤）
- **结论**：
  1. `text_match` 断言类型**必须携带 `selector` 字段**（scenarios.py load_scenarios 校验：`类型 'text_match' 需要 selector`），构造场景 fixture 时漏写会在加载期报错。
  2. 消费面陷阱：`load_scenarios` 抛出的 ValueError 会被部分哈希/指纹类消费面（如 `_failed_assertions_hash`）**静默吞掉回空集**——外部表现为「两次哈希相等」「指纹不变」等静默失真，而不是显式报错。调试此类「哈希意外相等」先直接跑 load_scenarios 看是否 LOAD FAIL。
- **修复先例**：tests/test_escalation_chain.py `_scn` fixture 断言补 `"selector": ".result"`。
- **建议去向**：并入 verify-pipeline 域场景 schema/词表页。
