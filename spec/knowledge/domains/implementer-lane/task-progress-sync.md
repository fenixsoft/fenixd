<!-- knowledge: capability=task-progress-sync rev=1 sources=spec/archive/2026-09-02-add-task-progress-sync -->

# 任务进度同步链路

implementer run 结束后由 daemon 把 run 产物中的任务完成状态确定性回写进主树 `tasks.md`，并在 verified→done 转换处以一致性门禁保证进度声明与任务清单一致——进度数据由写侧确定性保证，不依赖 agent 自觉。

## 现行规则

- 写侧确定性回写：implementer run 终态为 success 时，daemon 解析该 run 产物（`.fenix/runs/impl-<spec>-*.jsonl`）中 TaskCreate subject 内嵌的任务 id 与 TaskUpdate completed 集合，将主树 `spec/changes/<spec>/tasks.md` 中对应 id 的 `- [ ]` 确定性改为 `- [x]`，并以固定 message `[fenix] <spec>: sync task progress from run record` 提交，便于与 agent 提交区分。
- 回写幂等、只增不减：已勾选的任务跳过；agent 已自行勾选的内容不被撤销；重复执行不产生新变更。
- 无可解析完成集时不动作：run 产物缺失或不含任何可解析完成记录时 tasks.md 保持原样，不报错、不产生空提交；完成集的兜底回退语义见 [task-progress-writeback](task-progress-writeback.md)。
- verified→done 一致性门禁：SPEC 从 verified 转入 done 前校验任务完成一致性——最新成功 impl run 的 `.fenix-run-result.json` 声明 success、但存在「tasks.md 未勾选且不在 run 记录 done_ids 中」的任务时，阻断自动推送（不执行 git push），缺口写入 STATE.md 的 error 字段供人工裁决，SPEC 保持 verified；全部任务可确认完成（已勾选或出现在 done_ids）时正常放行。
- 适用范围：fix-* 型 SPEC 的 verified→done 转换以相同规则校验其 tasks.md 与 run 记录。
- 读侧实时叠加保留为 implementing 期间的兜底视图；done/pushed 终态不依赖读侧叠加。

## 关键行为

run 终态 success → 解析 run 产物完成集 → 勾选主树 tasks.md 对应项并产生 sync commit → verified→done 转换时一致性门禁核对勾选与 done_ids → 有缺口则阻断推送并落 error，无缺口则放行既有审批/推送流程。

## 溯源

- 史前基线 — tasks.md 勾选写侧回写与 verified→done 一致性门禁已存在：回写以共享解析函数为准，一致性门禁核对勾选与终态。
- 2026-09-02 2026-09-02-add-task-progress-sync（spec/archive/2026-09-02-add-task-progress-sync） — 机制化写侧回写（run 产物解析、固定 message commit、幂等只增不减）与 verified→done 一致性门禁（阻断推送 + error 暴露缺口），读侧叠加降为兜底视图
