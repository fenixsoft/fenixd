# 修复族谱收敛治理

<!-- knowledge: capability=fix-family-convergence-governor rev=1
     sources=spec/archive/2026-09-02-improve-scheduling-noise-governance -->

限制 fix 族谱自动派生的深度与宽度，越界转人工并支持单次显式放行。

## 规则

- 自动创建 fix 子 SPEC 前计算候选子代的族谱度量：深度 = 规范名中连续 `fix-` 前缀层数；宽度 = 同父（去除一层 `fix-` 前缀后同根）且状态非 done/pushed 的兄弟数量。
- 深度超过 `pm.family.max_depth`（缺省 3）或宽度超过 `pm.family.max_width`（缺省 2）时中止自动创建：不创建新 SPEC、无新分支/工作树，父 SPEC 状态保持 bug-found 不变，日志记录拦截原因。
- 被拦截的派生请求转为 `family_explosion` 困境信号（severity=major）写入 admin_alerts 并唤起 Administrator 处置。
- 处置动作「放行一次」为该父 SPEC 设置豁免位 `_family_waiver=true`：下一轮 bug_found 处理允许再创建恰好一个子 SPEC，用后豁免位自动复位为 false；放行语义显式记录，不递归派生。
- 度量计算基于 STATE 全量读取，不受 fix-dispatch-orphan 字段保留策略（implementer_run 历史值保留）影响；对历史已存在的超限命名首次扫描即按现值评估，不追溯惩罚已 done/pushed 的祖先。

## 溯源

- 史前基线 — bug-found 派生已确立族谱收敛治理方向：family_explosion 越界转人工并支持单次显式放行，放行语义显式记录，不递归派生。
- [2026-09-02 2026-09-02-improve-scheduling-noise-governance](spec/archive/2026-09-02-improve-scheduling-noise-governance/) — 契约化：深度/宽度上限参数（`pm.family.max_depth`=3 / `max_width`=2）、越界转 family_explosion 信号、单次放行豁免位与计数口径兼容。
