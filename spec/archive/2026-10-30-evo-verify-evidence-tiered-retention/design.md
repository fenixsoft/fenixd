# 设计：verify-evidence-tiered-retention

## 根因

框架无 git add 证据的环节可拦，硬闸门不可行也无必要；膨胀源于契约外入库行为无约束，主杠杆是契约字段 + prompt 软约束。

## 方案

三层：
1. 模板：core/verify_contract_template.yaml 的 evidence_dir 注释块（约 141-148 行）新增 evidence_retention.max_binary_bytes 声明与分级规则注释；
2. 解析：core/verify_contract.py 的 load_verify_contract（约 286 行）与 validate_contract（约 714 行）解析新字段，仿 _positive_int_or_default（约 165 行）回退范式，缺省 10485760；
3. 指引：core/agent_runner/prompt_builder.py 证据落位段（约 1023-1080 行）追加分级条款，阈值取契约解析结果。

## 关键取舍

- 软约束优先：不新增执行闸门；tracked 证据体积普查信号（stray_wip 侧）留给告警升级 spec，不在本 SPEC。
- 不动 verify_contract.py 既有落位语义；只加字段与渲染。
- 存量 690MB 不做自动迁移（历史改写风险，人工评估）。

## 风险

- 模板改动影响新项目缺省行为：缺省值取保守 10MB，且字段可配。
- prompt 文本膨胀：分级条款控制在三句以内。