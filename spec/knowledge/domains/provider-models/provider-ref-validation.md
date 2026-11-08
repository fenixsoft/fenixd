# provider 引用校验与分配失效划界

<!-- knowledge: capability=provider-ref-validation rev=1
     sources=spec/changes/add-provider-validation-alert-governance -->

config 加载（含热加载）与 Dashboard 设置保存共用同一条 provider 引用校验：未注册引用不再静默跳过——保存路径当场拒绝、加载路径发带相似名建议的配置告警；角色模型链按「有无分配条目」划界无分配回落与分配失效两形态，判定实现全链单源。

## 规则

**校验规则单源（两路径共用）**

- `agents.models.<role>.provider` 引用的 provider 名必须存在于本项目 `llm.providers` 注册表。校验实现（角色遍历、字符串/对象数组两形态、坏名收集、相似名建议）单源收在 ConfigLoader，加载路径与 Dashboard 保存路径共用，禁止两路径规则漂移。
- 行为差异只收在处置层：Dashboard 保存路径 ValueError 当场拒绝（报错文案同样带相似名建议）；加载路径不阻塞——daemon 不因配置坏拒绝启动，校验结果以配置告警承载，且校验/告警链路 fail-open（异常只记日志不阻断加载）。合法引用零行为变化：加载行为、链解析结果、日志与告警均无新增。

**加载侧告警形态**

- 未注册引用发单条 major 配置告警（signal_type=`provider_ref_invalid`、cause=model-chain、kind=signal 的 daemon 级信号，spec=None），文案含角色名、未注册名、逐坏名修复建议与修复指引（编辑项目 config.yaml 或经 Dashboard 设置页修正）。
- 按「指纹（角色+坏名集合）」一次性去重：同指纹存在未处理记录即不再成条，重启不重发；修复后指纹消失，未处理同型记录按指纹批量 auto-resolve 收口。
- 告警 evidence 保留原始链条目（JSON 序列化）供修复参考。

**相似名建议**

- 规范化比对（小写 + `.`/`-`/`_` 归一为 `-`）后完全相等或编辑距离 ≤2 即命中，输出「是否意指 <已注册名>？」——`bigmodel.cn` → `bigmodel-cn` 即命中分隔符漂移类坏名；无相似项时输出当前全部已注册 provider 名清单，注册表为空时明示「未注册任何 provider」，不输出空清单。

**无分配与分配失效划界**

- 唯一判据是角色有无分配条目：`models` 条目缺席或 `provider` 键缺席/为空 = **无分配**——合法回落形态，走 harness-default-fallback 语义（对称回落 + 一次性 WARN），无新增告警。
- 有 provider 条目但经校验链为空（全部条目引用未注册，或链形态非法）= **分配失效**——配置错误形态，MUST NOT 静默回落：发上述配置告警，派发按 `[model-chain-unavailable]` 归因，日志不出现「回落 harness 默认配置」WARN。
- 部分条目未注册时仅未知元素运行期跳过，不判整链失效（局部坏名不放大成整角色停摆）。
- 链解析三态（unassigned / invalid / ok）由 ConfigLoader 单一实现产出，派发侧只消费同一解析结果，禁另立口径。

## 代码锚点

- 校验与链解析单源：`core/config.py`（collect_unregistered_provider_refs / describe_provider_ref_fix_hint / get_agent_chain_resolution / _report_provider_ref_alerts）
- Dashboard 保存路径消费（ValueError 拒绝 + 建议）：`core/dashboard/data/config_admin.py`
- 派发侧三态消费：`core/agent_runner/runner.py`
- 守卫测试：`tests/test_provider_ref_validation.py`

## 溯源

- 2026-11-08 add-provider-validation-alert-governance（spec/changes/add-provider-validation-alert-governance/） — 新建本能力页：加载路径 provider 引用校验与保存路径校验单源化、相似名建议（规范化+编辑距离 ≤2）、无分配/分配失效划界与链解析三态判定单源
