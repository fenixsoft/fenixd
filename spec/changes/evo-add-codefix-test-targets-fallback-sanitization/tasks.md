## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_affinity_batching.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: .fenix/verify.yaml
  kind: modify
```

## 1. 回退路径消毒

- [ ] 1.1 core/code_fix.py：新增模块常量 CODE_FIX_TEST_TARGETS_FALLBACK = tests/ 与消毒薄包装（复用 _apply_test_targets，对无占位符 spec 原样返回零迁移）
- [ ] 1.2 core/code_fix.py：_resolve_batch_regression_spec 两个回退出口（约 :2187-2188 链末批/配置关、约 :2200-2204 映射空集）返回消毒副本；定向判别仍用原 spec（ctx 入口不盲替）
- [ ] 1.3 core/code_fix.py：定向重试轮 mapped=False 全回归路径（约 :3609-3612）改用消毒 spec 并纳入 FENIX_TEST_TARGETS 窗口（或等效消毒），覆盖「占位符在场加重试轮」组合

## 2. 测试

- [ ] 2.1 tests/test_code_fix_affinity_batching.py：改写三个断言字面透传的存量测试（约 :557-563/:592-606/:609-615 的 assertIs）为消毒语义
- [ ] 2.2 tests/test_code_fix_affinity_batching.py：新增四组用例——占位符在场乘三类回退场景、重试轮 unmapped 消毒、无占位符零迁移、fenixd 安全注释形态消毒无害（每组覆盖 str 与 list 两态）

## 3. 配置规约落地

- [ ] 3.1 .fenix/config.template.yaml：targeted_regression 注释段（约 :466-476）补安全 cmd 写法样例与「MUST NOT 把 {test_targets} 直接写进参数位」警示，纠正 :471 引导写占位符的表述
- [ ] 3.2 .fenix/verify.yaml：工作区 13 行写法规约入库（若已被其他通道先行提交则核对内容并仅在提交说明互引），提交说明注明与收口滞留清欠的归属关系，一次提交两清