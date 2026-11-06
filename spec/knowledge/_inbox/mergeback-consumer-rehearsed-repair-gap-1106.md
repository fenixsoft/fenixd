# merge-back 消费者失败路径未接预演语义冲突直通 repair（框架缺口）

- **发现于**：add-spec-chinese-title mergeback_wip_overlap→defer_stuck 人工处置（2026-11-06，admin run admin-add-spec-chinese-title-1793954563）
- **现象**：带 `_wip_gate_deferred=True` 的条目经周期消费者 `_retry_merge_back_only` 重试合回时，若预演检出语义冲突（真内容冲突形态），失败路径只做「清 _wip_gate_deferred 标志 → 交回既有失败通道」（queue.py `_retry_merge_back_only` 内 3963-3983 行段），`_direct_rehearsed_to_repair`（预演语义冲突直通 repair，add-merge-tree-rehearsal D2）仅在实现主路径 merge-back 站点（queue.py ~2565 行）接线。
- **后果**：WIP 等待车道（wip-defer-merge-retry）的条目撞内容冲突时不进 repair 车道，而是清等待标志走真失败通道——按 merge-back 失败分类可能落 `_merge_streak` 指纹熔断/ready 降级清锚点，已完成实现的工作面被降级、分支锚点有孤儿化风险（memory「复位 ready 会清锚点勿走」同类）。本次人工处置实测：预演确认 list.tsx 语义冲突存在，若收编 WIP 后放任消费者自动重试，即落入该通道。
- **建议方向**：消费者失败路径对 `merge_info` 的 rehearsed 语义冲突形态补同型直通 repair 接线（复用主路径 `_direct_rehearsed_to_repair`，`_repair_round` 上限语义不变）；接线前该形态由 admin 人工 SOP 覆盖（定点收编+手工 merge+镜像 `_finalize_merge_success` 清账，2026-11-06 add-spec-chinese-title 实证可行，见 admin_disposition 留痕与 .history/mergeback-surgery-add-spec-chinese-title-20261106/ 备份）。
- **关联**：worktree-vc 域 merge-rehearsal / wip-defer-merge-retry / merge-back-precheck 三页。
