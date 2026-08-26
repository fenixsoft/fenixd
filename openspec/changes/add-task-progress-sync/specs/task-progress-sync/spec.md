# Task Progress Sync Spec

## ADDED Requirements

### Requirement: implementer run 成功后 daemon 确定性回写 tasks.md
implementer run 终态为 success 时，系统 SHALL 解析该 run 产物（`.fenix/runs/impl-<spec>-*.jsonl`）中的 TaskCreate subject 内嵌任务 id 与 TaskUpdate completed 集合，将主树 `openspec/changes/<spec>/tasks.md` 中对应 id 的 `- [ ]` 确定性改为 `- [x]`，并以固定格式 message（`[fenix] <spec>: sync task progress from run record`）commit。回写 SHALL 幂等：已勾选的任务跳过；run 产物缺失或解析为空时不做任何修改。agent 已自行勾选的内容 MUST NOT 被撤销。

#### Scenario: run 声明完成但 tasks.md 未勾时回写
- **WHEN** implementer run 终态 success 且其 run 产物含 TaskUpdate completed 对应任务 id「2.1」「2.2」，而主树 tasks.md 中这两项仍为 `- [ ]`
- **THEN** daemon 将这两项改为 `- [x]` 并产生一条 sync commit；重复执行不产生新变更

#### Scenario: run 产物缺失或无可解析完成集时不动作
- **WHEN** run 终态 success 但 run 文件已被清理或不含任何 TaskUpdate completed 记录
- **THEN** tasks.md 保持原样，不报错、不产生空 commit

#### Scenario: agent 自行勾选不被覆盖
- **WHEN** 主树 tasks.md 某任务已为 `- [x]` 而 run 记录未包含该任务
- **THEN** 该勾选保持不变（回写只增不减）

### Requirement: verified→done 任务一致性门禁
SPEC 从 verified 转入 done 前，系统 SHALL 校验任务完成一致性：若最新成功 impl run 的 `.fenix-run-result.json` 声明 success，但存在「tasks.md 未勾选且不在 run 记录 done_ids 中」的任务，则 SHALL 阻断自动推送（不调用 git push），将该缺口写入 STATE.md 的 error 字段供人工裁决；全部任务可确认完成时正常放行。

#### Scenario: 存在未完成任务时阻断推送
- **WHEN** SPEC verified 且 run 声明 success，但任务「4.1」未勾选且不在任何 impl run 的 done_ids 中
- **THEN** 不执行 git push，error 字段记录「未完成任务：4.1」，SPEC 保持 verified 待人工处置

#### Scenario: 全部任务确认完成后放行
- **WHEN** SPEC verified 且所有任务已勾选或出现在 done_ids 中
- **THEN** 门禁通过，按既有流程 auto approve / 人工审批推送

#### Scenario: fix 型 SPEC 同样适用
- **WHEN** fix-* SPEC 走完 verified→done 流程
- **THEN** 一致性门禁以相同规则校验其 tasks.md 与 run 记录
