## Why

provider 链配置的校验在两条路径上不对齐：Dashboard 设置保存路径有引用校验（`config_admin.py` 对未注册 provider 直接拒绝），而**文件编辑/热加载路径静默跳过**（`core/config.py:1700`「引用了不存在的 provider（已跳过，不阻塞加载）」）。新项目 cloud-phone 把全局 config 的 models 块复制进项目后，provider 名 `bigmodel.cn` 与项目注册的 `bigmodel-cn` 一字之差，**48 条 ERROR 全部静默跳过、agent 无可用模型继续派发失败**——用户看到的却是 spawn 失败，完全无法联想到配置名字写错。

配套的两个告警治理缺陷放大了首跑痛苦：

1. **首个 SPEC 实现期契约预检噪音**：`verify_contract_missing` 在 spec 仍处于 implementing 时以 major 级每 5 分钟巡检召唤 Administrator（预检文案自己承认「spec 仍在实现流程中，起草落位即可，勿复位」），首跑产生 6 条 major 告警。
2. **修复后告警永久滞留**：模型配置修复生效后，同根因旧告警（模型链/CLI 失败衍生）不随之失效，28 条未处理告警永久挂在面板——「已修复」与「待处理」在面板上无法区分。

## What Changes

- **config 加载路径 provider 引用校验**：热加载/文件加载对 `agents.models.*.provider` 引用执行与 Dashboard 保存路径同源的校验规则；未注册 provider 不再静默跳过，改为该角色链降级 + 单条 actionable 配置告警（含相似名建议，如 `bigmodel.cn → bigmodel-cn`）
- **「无分配」与「分配失效」划界**：链条目全部无效（引用未注册 provider）后的空链不再等价「无分配回落」语义——回落 WARN 是合法态，分配失效是配置错误态，后者发配置告警并保留原分配内容供修复参考
- **首个 SPEC 实现期契约预检降噪**：spec 处于 implementing 时 `verify_contract_missing` 降为 info 级、同 spec 一次性（不重复召唤 Administrator）；spec 进入验证阶段后按既有 major 语义恢复
- **告警根因分组与 supersede**：告警增加根因标签（模型链/CLI/散件/契约等）；同根因配置修复生效（热加载成功 + 后续派发成功）后，同根因未处理告警自动批量标记 superseded，面板呈现「已失效」折叠组

## Capabilities

### New Capabilities

- `provider-ref-validation`：config 加载路径 provider 引用校验、相似名建议与「无分配/分配失效」划界
- `verify-contract-precheck-noise-reduction`：实现期验证契约预检降噪（降级 + 一次性）

### Modified Capabilities

- `alert-lifecycle`：根因标签、superseded 批量失效与面板分组呈现（既有 auto-resolve / self-heal-marking / terminal-close 语义不变，supersede 为新增终态旁路）

## Impact

- **代码**：`core/config.py`（加载路径校验）、`core/dashboard/data/config_admin.py`（校验规则单源化）、`core/admin_monitor.py`（契约预检分级 + supersede 触发）、告警存储/面板前后端（`core/dashboard/` 告警数据链与前端告警页）
- **兼容性**：既有合法配置零行为变化；显式链正常派发不受校验影响
- **关联**：与 `add-dispatch-precheck-true-fallback`（SPEC ①）互补——①解决「没配模型怎么兜底」，②解决「配错了怎么一眼看出来」
