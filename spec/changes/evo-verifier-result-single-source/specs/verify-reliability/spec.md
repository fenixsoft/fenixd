# 验证结果文件单一来源（verifier-result-single-source）

## 需求

### R1 读取单一来源
- verifier 裁决一律读 verify-progress/<spec>/.fenix-run-result.json。
- 主树 .fenix/.fenix-run-result.json 仅作兼容回退：须先通过 spec 戳匹配 + mtime 新鲜度双校验，任一不通过视为失效，回退不得作为裁决依据。

### R2 写入语义隔离
- 主树共享文件写入时强制带 role 字段（implementer | verifier）与 spec 戳。
- implementer 写主树共享文件改为写 verify-progress/<spec>/impl-result.json（已在部分 spec 落地，见 add-web-ui/impl-result.json），主树共享不再承载 implementer 语义。

### R3 回归测试
- 新增污染回归测试：主树共享文件含 implementer 残留 status=success 时，legacy 与 planner 两路径均不得将其当裁决；unknown-status 走 stale/foreign 护栏 re-dispatch。

## 验收标准
- 场景：add-web-ui 09:06 误判链重放，0 次 blocked 误判。
- 单元测试：双校验回退、role 字段隔离、污染数据 not treated as verdict。