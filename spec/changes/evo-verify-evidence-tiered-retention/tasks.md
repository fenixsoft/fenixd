## Deliverables

```yaml
- path: core/verify_contract_template.yaml
  kind: modify
- path: core/verify_contract.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_verify_contract.py
  kind: modify
- path: tests/test_verify_evidence_placement.py
  kind: modify
```

## 1. 契约分级字段

- [x] 1.1 core/verify_contract_template.yaml：evidence_dir 注释块（约 141-148 行）新增可选分级声明字段 evidence_retention.max_binary_bytes（缺省 10485760 即 10MB），注释写明分级规则——文本/JSON/哈希/小日志直接入库，超过阈值的二进制不入 git，改以 sha256 sidecar + 复现命令 + 存放路径登记
- [x] 1.2 core/verify_contract.py：load_verify_contract（约 286 行）与 validate_contract（约 714 行）解析 evidence_retention.max_binary_bytes，仿 _positive_int_or_default（约 165 行）的回退范式——缺失/非法值回退缺省 10485760 不报错，并把解析结果暴露给落位指引渲染

## 2. 落位指引分级条款

- [x] 2.1 core/agent_runner/prompt_builder.py：证据落位段（约 1023-1080 行）追加分级留存条款——超过契约阈值的二进制证据不入 git，落 sha256 sidecar 与复现命令、存放路径登记文件；文本/JSON/哈希/小日志直接入库；阈值取自契约解析结果，缺省 10MB

## 3. 测试

- [x] 3.1 tests/test_verify_contract.py：覆盖 evidence_retention.max_binary_bytes 解析三态（声明值生效、非法值回退缺省、缺失走缺省）
- [x] 3.2 tests/test_verify_evidence_placement.py：覆盖落位指引在契约声明阈值与缺省阈值两种形态下均渲染分级条款
