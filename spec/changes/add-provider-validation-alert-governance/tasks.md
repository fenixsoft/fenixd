## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/dashboard/static/src/components/alert-shared.tsx
  kind: modify
- path: tests/test_provider_ref_validation.py
  kind: new
- path: tests/test_alert_supersede.py
  kind: new
- path: tests/test_contract_precheck_noise.py
  kind: new
```

## 1. provider 引用校验单源化与相似名建议（D1/D2）

- [x] 1.1 抽取公共校验函数（含角色遍历、provider 字符串/对象数组两形态、坏名收集），`config_admin.py` 保存路径改为调用该函数（拒绝语义与既有文案兼容，附相似名建议）
- [x] 1.2 daemon 加载路径（`core/config.py`）接入同一校验函数：未注册引用不再静默跳过，改为该角色链标记失效 + 按「角色+坏名集合」指纹发单条 major 配置告警（文案含角色名、未注册名、注册表清单/相似名建议、修复指引）；同指纹一次性去重，修复后指纹消失自动复位
- [x] 1.3 相似名建议实现：规范化（小写、`.-_` 归一）+ 编辑距离 ≤2 命中「是否意指 `<已注册名>`」；无候选输出注册表清单
- [x] 1.4 pytest 单测（tests/test_provider_ref_validation.py）：未注册引用告警 + 相似名建议断言、合法引用零变化、指纹去重与复位、Dashboard 保存路径拒绝语义回归、两路径规则同源（同一函数）

## 2. 无分配与分配失效划界（D3）

- [x] 2.1 加载侧产出每角色链解析结果（有效条目集 + 失效原因 + 原始条目），runner 侧消费同一结果：分配失效态（有条目但链空）不回落、不打 harness-default WARN、派发按 `[model-chain-unavailable]` 既有语义归因，告警 evidence 含原始链条目
- [x] 2.2 无分配态回归：对称回落 + 一次性 WARN 行为与现状一致（对接 SPEC ① bundle 侧回落，回归用例防互踩）
- [x] 2.3 pytest 单测：分配失效不回落断言、告警 evidence 原始条目、无分配回落语义回归

## 3. 实现期契约预检降噪（D4）

- [x] 3.1 `admin_monitor.py` 巡检分级：spec 处于实现中状态时 `verify_contract_missing` 降 info + 同 spec 一次性（去重键 `signal_type:spec`，持久化随告警账本，重启不重发）；spec 离开实现流程去重态复位、契约仍缺时按既有 major 语义发信号
- [x] 3.2 pytest 单测（tests/test_contract_precheck_noise.py）：实现期单条 info 不召唤、状态迁移后恢复 major、契约已裁决零信号、重启不重发

## 4. 告警根因标签与批量 supersede（D5）

- [x] 4.1 告警账本增量 `cause` 字段（封闭枚举：model-chain / harness-cli / init-stray / contract / daemon-error / unknown），信号入账时由产生方标注；读侧缺席容错为 unknown
- [x] 4.2 supersede 触发器：每根因修复观测点（model-chain = 校验干净加载 + 其后首派发成功；harness-cli = 启动自检可达对接 SPEC ① 自检态，SPEC ① 未合回时该观测点暂不启用），观测点通过时同根因未处理告警单事务批量标记 superseded（失效时间 + 触发观测点记录），升级链引用解除、未处理计数扣除
- [x] 4.3 面板呈现（`alert-shared.tsx`）：根因分组过滤/折叠「已失效」组（默认收起可展开）、未处理计数同步、人工撤销 supersede 恢复未处理入口
- [x] 4.4 pytest 单测（tests/test_alert_supersede.py）：观测点触发批量失效原子性、观测点不全不触发、既有终态路径不受影响、撤销 supersede、unknown 根因不参与自动失效
- [x] 4.5 前端构建验证：alert-shared 改动后 dashboard 前端构建通过（worktree 内既有构建链路）
- [x] 4.6 存量账本 cause 回填：daemon 启动首轮按 signal_type→cause 高置信封闭映射为无 cause 未处理告警回填（resolve_note 注「存量回填：」前缀），无法映射保持 unknown 不参与 supersede；单测断言回填与 unknown 豁免（并入 tests/test_alert_supersede.py）
