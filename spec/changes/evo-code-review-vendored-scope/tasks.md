## Deliverables

```yaml
- path: core/code_review.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 出题面 vendored 排除

- [ ] 1.1 core/code_review.py：_EXCLUDED_TOP_DIRS（:773-784）单表加 thirdparty、third_party、vendor（目录段精确匹配）——_EXCLUDED_DIRS（:789-795）与 _EXCLUDED_PREFIXES（:796-798）均由该表派生（:769-772「单表派生消除漂移面」原则），MUST NOT 在派生表重复手写；full 档 collect_manifest（:856-922）与 window 档共用消费点（core/admin_monitor.py:1560-1571 侧）自动生效；非 vendored 路径收集行为不变。
- [ ] 1.2 agents/code-review.md：:20「其中的路径是产品代码」改为如实描述（已排除测试/生成物/vendored 第三方目录）；:56-58 fenix-ignore 复核规则补强——对漏出排除表但带 fenix-ignore 标注且理由为保持上游同步的文件，MUST 只记录不上报缺陷条目。

## 2. 测试

- [ ] 2.1 tests/test_code_review.py：仿 test_excludes_tests（:1138）补 vendored 排除用例——fixture 放 thirdparty/x/a.py、third_party/y/b.py、vendor/z/c.py 断言均不入 manifest、其余源码收集不变；window 档收集同样排除。