<!-- knowledge: capability=deliverable-dispute-preclassify rev=1 sources=spec/archive/2026-09-24-evo-deliverable-declaration-drift-align -->

# 交付物争议漂移笔误机械对齐

拆包/改名漂移特征缺件的确定性机械对齐通道，以及被取代草案（SUPERSEDED.md）的派发前收敛检查。

## 现行规则

- 漂移对齐三条件（全部满足方机械对齐声明并解除 blocked）：①声明路径在主树与实现分支 HEAD 均不存在（git cat-file / 文件系统核实）；②git 历史对该路径有命中（`git log --all -- <path>` 非空，该文件曾存在——拆包/改名漂移特征，区别于零引用孤儿）；③候选新落点可唯一定位。
- 候选定位确定性规则：候选 = 旧路径 basename 去 `.py` 所得包目录内、且落在本次实现分支改动集合（`git diff --name-only --diff-filter=AM <merge-base>..<branch>`）内的 `.py` 文件；交集唯一且该候选在实现分支 HEAD 真实存在（`file_exists_on_branch`）方判可对齐。候选定位不依赖函数名或任何非字面证据，不得用全仓 rglob 同名文件兜底（同名文件会伪造唯一性）。
- 复用既有原语、通道互斥：复用陈日信号 `is_stale_declaration`、生效声明解析 `resolve_effective_declaration`、改写 `relocate_declared_path`、凭据 `register_relocation_credential`，不另起一套。与陈日预分类通道（`_preclassify_stale`）互斥——同一轮同一 spec 不得由两条通道各改写一次声明；本通道失败即回退既有人工通道，不再触发重定位改写。
- 对齐动作：改写**生效声明所在位置**的 tasks.md Deliverables 段 path 为实际落点（生效声明来源为分支版本、无落盘位置时改走凭据登记，不直写主树声明——写读错层即本通道的立项根因）；改写后立即提交该文件以防 merge 死锁；审计写入 dispute audits（`verdict=drift-aligned`、`actual_path`、判断依据，同时以 `type=relocation` 形态落册以命中收缩防护的重定位凭据豁免）；解除 blocked 后自动重入实现。
- fail-open：任一环节异常（生效声明不可读、条目不存在、候选零个或多个、改写或提交失败）回既有 blocked 待人工通道，不半途改写；回人工的异议带「存在漂移特征但无法唯一定位」说明供人工快速裁决。
- 派发前同源草案收敛检查：implementer/fast-track 派发前（`_on_spec_ready` 及队列候选筛选入口）检查本 spec 目录自身是否含 `SUPERSEDED.md`——命中则禁止派发、spec 置 blocked（error 附 SUPERSEDED.md 路径），待收敛（该文件移除或目录删除）后恢复派发。同源判定以「显式点名」（目录名以 inline code/路径形态出现在 SUPERSEDED.md 正文）与「本目录自身含 SUPERSEDED.md」为判据；不依赖 `.spec.yaml` 的 capability 字段；不只因「平级存在名字归一后相同的草案」就拦截（被点名的生效落点与收敛源按名字归一会互为命中，误拦会把生效草案永久冻住）。
- 审计留痕：机械对齐的 dispute_audits 记录含 instrument 路径、actual_path、候选唯一性证据（git 历史命中数、候选清单）与判据（drift-aligned）。

## 溯源

- 2026-09-24 2026-09-24-evo-deliverable-declaration-drift-align（spec/archive/2026-09-24-evo-deliverable-declaration-drift-align） — 确立漂移三条件与确定性候选定位、既有原语复用与通道互斥、对齐动作审计，及 SUPERSEDED.md 派发前收敛检查
