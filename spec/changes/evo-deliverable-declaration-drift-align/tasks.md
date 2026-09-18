## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_deliverable_drift_align.py
  kind: new
```

## 1. 漂移笔误机械对齐

- [ ] 1.1 core/deliverables.py：在既有孤儿判定分支（历史命中→走人工）前插入漂移对齐判定：声明路径在主树与实现分支 HEAD 均缺 且 git 历史命中 → 进入 _locate_drift_target 候选定位
- [ ] 1.2 新增候选定位（`core/deliverables.py` 纯函数或复用同源原语）：旧路径 basename 去 `.py` 得包目录，候选 = 该目录内 ∩ `git diff --name-only --diff-filter=AM <merge-base>..<branch>` 的 `.py` 文件；MUST NOT 用全仓 rglob 同名文件兜底；交集唯一（1 个）且该路径 `file_exists_on_branch` 为真才算可对齐；零个或多个 → fail-open 回人工（不机械改写）
- [ ] 1.2b 复用既有原语而非重写：陈日信号 `is_stale_declaration`（deliverables.py:877）、生效声明 `Dispatcher._effective_declaration`（adjudication.py:23）、改写 `relocate_declared_path`（deliverables.py:919）、凭据 `register_relocation_credential`（deliverables.py:936）；与 `_preclassify_stale`（adjudication.py:714）互斥——同一轮同一 spec MUST NOT 双通道各改写一次，本通道失败即回退人工通道
- [ ] 1.3 机械对齐执行：改写**生效声明所在位置**（`resolved["spec_dir"]`）的 Deliverables 声明段 path（kind 不变），写回并校验 yaml 可解析；`spec_dir` 为 None（分支来源无落盘位置）→ 走凭据登记、MUST NOT 直写主树声明；改写后复用 `_commit_softened_declaration`（adjudication.py:289）立即提交该文件
- [ ] 1.4 审计记录：`type=relocation` + verdict=drift-aligned、actual_path、候选唯一性证据（git 历史命中数、分支改动集合、候选清单）+ reasoning，含 before/after diff（`type=relocation` 用以命中收缩防护 `_has_relocation_credential` 豁免）
- [ ] 1.5 对齐成功后解除 blocked（清 error、置回原实现态或 ready 重排）；生效声明不可读 / 条目不存在 / 候选零或多 / 改写或提交失败任一环节即中止对齐走人工，MUST NOT 半途改写

## 2. 派发前同源草案收敛检查

- [ ] 2.1 core/pm_engine/engine.py `_on_spec_ready`：派发 implementer/fast-track 前扫描 spec/changes/ 下所有 SUPERSEDED.md；同口径须同样落在队列候选筛选入口（core/pm_engine/dispatch/queue.py `_process_queue`，覆盖不经 `_on_spec_ready` 的定时重派/恢复车道条目）
- [ ] 2.2 **本 spec 目录自身含 SUPERSEDED.md** → 拦截派发、置 blocked（error=同源草案收敛义务未满足，附 SUPERSEDED.md 路径）；被 SUPERSEDED.md 显式点名（inline code / 路径形态）为**生效落点**的一侧 MUST NOT 被拦截（MUST NOT 依赖 `.spec.yaml` capability 字段——实测全仓无该键）
- [ ] 2.3 收敛完成信号：被取代目录的 SUPERSEDED.md 移除或目录删除后派发恢复；名字归一（去 `-\d+$` 后缀，同源 `_NUM_SUFFIX_RE`，core/evolution.py:1498）仅用于识别平级同名草案，MUST NOT 单凭归一命中拦截生效落点

## 3. 测试

- [ ] 3.1 tests/test_deliverable_drift_align.py：覆盖唯一候选机械对齐（改写生效声明+审计+解阻，断言审计记录 `type=relocation`）、零候选/多候选 fail-open 回人工、`spec_dir=None`（分支来源）走凭据登记不改写主树、候选不在分支 HEAD 时回人工；含以 `core/worktree_manager.py` / `core/pm_engine/dispatch.py` 真实拆包形态（包内多文件、分支改动集合唯一命中）为夹具的取证
- [ ] 3.2 tests/test_deliverable_drift_align.py：覆盖同源草案派发拦截（本目录含 SUPERSEDED.md 者被阻断、对侧生效落点正常派发）与收敛（移除 SUPERSEDED.md）后恢复派发