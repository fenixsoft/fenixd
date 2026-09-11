# 设计：验证进度 fast-track 数据源回退（fix-verify-progress-fasttrack）

## Context

- 验证进度数据源 `.fenix/verify-progress/<spec>.json`（total/done/current）唯一写入方是 full 模式验证引擎（`core/verify_engine/engine.py` 的 `_write_progress`，终态文案 `验证完成: {passed}通过, {failed}失败, {errors}错误`，engine.py:141-144）；fast-track 单 agent 全包不经过该引擎，该文件全程不存在。
- `core/dashboard/data.py::parse_verify_progress`（1246 行）现状：文件缺失即返回 `{exists: False, total: 0, done: 0}`，无任何回退。下游两处消费：列表 `verify_done/verify_total`（`list.tsx:203` 硬渲染）、详情页「验证进度」卡片（`detail.tsx:1367` 按 `exists` 分支）。
- fast-track 裁决结果文件 `.fenix-run-result.json` 的场景明细在 `verification.scenarios` 嵌套键（`core/fast_track_result.py` schema，status 枚举 `{pass, fail, error, warning, exempt}`）；读取路径与 spec 匹配守卫已在同日修复中定型于 `data.py::parse_run_result_scenarios`（专属副本优先 → 主树回退且 spec 不符忽略）。
- 同根因家族已修两处（场景结果页签、验证报告合成器场景表）；本 change 补齐第三处（验证进度通道），保持三处语义同源。

## Goals / Non-Goals

**Goals**

- fast-track SPEC 列表「验证」列显示真实验证结果（N/N），详情页「验证进度」卡片显示进度条 + 终态文案。
- full 模式行为零回归（进度文件优先不变）。
- 双缺省时维持现状空态语义（列表 `—`、详情「暂无验证进度」）。

**Non-Goals**

- 不改 fast-track 结果文件写入端 schema（agent 侧契约不动）。
- 不改 verify_engine 写入逻辑与 full 模式逐场景推进。
- 不做 fast-track「伪实时」逐场景推进——fast-track 验证一次性完成，进度恒终态。
- 不改裁决/闸门逻辑（verdict_check、verify-report-gate 不在触碰范围）。

## Decisions

1. **回退合成内聚在 `parse_verify_progress`，复用 `parse_run_result_scenarios` 取场景**
   进度文件缺失时调用 `parse_run_result_scenarios(project_root, spec_name)` 拿场景列表（归一化不影响 `status` 字段），按口径合成 total/done/current。非空 → `exists: True` + `source: "run-result"`；空 → 维持 `exists: False`。
   *备选*：抽 `_load_run_result_raw` 公共 helper 两函数共用——否决，`parse_run_result_scenarios` 已在产（场景结果页签与验证报告合成器间接依赖其行为语义），动它扩大回归面；嵌套调用一次 IO，数据层读侧本就是按需短路径读，无性能顾虑（缓存层 `_RUN_TASK_CACHE` 模式不变）。

2. **计数口径对齐裁决链既有枚举**
   通过 = `pass`；失败 = `fail`/`failed`（`verdict_check.py` 双用词兼容）；错误 = `error`；`warning`/`exempt` 为豁免类不计入三桶（与 `NON_PASS_STATUSES`/豁免语义一致）。文案格式与 full 终态完全一致（`验证完成: N通过, M失败, K错误`）。
   `total` = 场景条目数；`done` = 含 `status` 字段的条目数（fast-track 一次性判定，正常恒等于 total；条目缺 status 按 0 场景防御）。

3. **`source` 标记区分数据来源**：回退合成成功 → `source: "run-result"`；进度文件路径 → `source: "file"`。前端不依赖该字段（仅语义可追溯与测试断言用），保持两形态可区分。

4. **列表兜底取实现简者**：`verify_total === 0` 时渲染纯文本 `—`（不包 Popover）；`> 0` 时维持 `done/total` + 既有 Popover 不变。排序器（`list.tsx:801` 按 pct 排序）无需改动——total=0 的 pct 恒 0，排尾语义正确。

## Risks / Trade-offs

- [fast-track 场景 status 含 `warning`/`exempt`，三桶计数之和可能小于 total] → 文案仍与 full 终态同构；豁免场景本就不构成失败/错误，不显示比误显示诚实。若三桶全零而 total>0（极端全豁免），文案为「验证完成: 0通过, 0失败, 0错误」——语义正确，进度条 done/total=N/N 仍完整。
- [主树共享文件回退可能读到同 spec 旧一轮结果] → 与现状同险（场景结果页签同源），专属副本优先使实际命中概率低；复用既有守卫，不新增缓解。
- [前端改动引入回归] → 改动为一个三元渲染分支，`> 0` 路径零变化；移动端适配（screen-xs 作用域）与主题切换不触碰。

## Migration Plan

纯读取端兼容，无迁移。部署（merge + 前端重建 dist）即生效：存量 fast-track SPEC 专属副本在盘（抽查 5/5 完好，场景数 6/11/8/4/8），下次拉取列表/详情即出真实进度。回滚 = revert 单 commit，无状态残留。

## Open Questions

（无——枚举口径、查找顺序、守卫语义均已在裁决链与同日两处修复中定型。）
