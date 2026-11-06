# 蒸馏批时间轴工作总结

<!-- knowledge: capability=knowledge-distill-run-summary rev=1
     sources=spec/changes/add-distill-run-work-summary -->

蒸馏批 run 在 SPEC 详情运行时间轴上可读出主蒸馏 agent 的工作总结：终态 `result` 行携带总结文本，经既有时间轴总结盒管道自动渲染，蒸馏产出不再零呈现。

## 规则

- 终态行携带总结：蒸馏批产物终态 `result` 行含 `result` 字符串字段，值为主蒸馏 agent 的工作总结（markdown、建议 ≤20 行）；时间轴 run 节点总结盒用与普通 agent 相同的既有 `_run_tail_insights` → `item.summary` 管道渲染，读侧与前端没有针对蒸馏批的特判分支。产物 JSON 字段名必须叫 `result`（读侧契约钉死），执行器内部 dict 键名用 `summary` 避免与 dict 自身语义混淆。
- 文本来源与剥离：总结取主蒸馏 spawn（裸文本 `claude -p`）成功路径的 stdout（即 agent 最终消息），剥离尾部 `KNOWLEDGE_DISTILL_DONE` 标记行后整段装配。标记行是剥离锚点而非成功判据——成功判据仍是退出码 0 + validate_knowledge 通过；标记缺失不判失败，剥除逻辑空转、stdout 全文作总结（fail-open）。
- 截断上限：总结文本超 2000 字符时尾部截断并加「…（截断）」后缀（模块常量，提取为纯函数）。
- fail-open 与向后兼容：stdout 为空、仅含标记行或缺总结文本时，终态行不写 `result` 字段，蒸馏结果与台账行为不受影响；历史蒸馏产物无该字段，时间轴按字段缺失不渲染（与 origin_request 同口径）。
- 失败路径不携带总结：spawn 失败（非零退出/超时/校验违规放弃）时终态 `error` 行不含总结文本，失败诊断形态不变（stderr 尾部进 todo 台账 reason、stdout 摘要进日志照旧）。
- 范围限定主蒸馏：折叠前置段子 run 的 stdout 不进终态行，产物仍只有 `folded`/`fold_failed` 计数（语义不变）；折叠 prompt 完成契约不同步改动。
- 总结必须是 agent 自述，daemon 侧不以 git show --stat 合成摘要替代（非 agent 自陈、无规则语义）；run 观测面其余缺口仍在——`result` 行不含改动文件清单，文件级产出取证仍以 git log 为准（见 [knowledge-distill-pipeline](knowledge-distill-pipeline.md)）。

## 关键行为

主蒸馏成功路径：spawn 返回三元组 `(ok, err, stdout)`（折叠调用点忽略第三位适配）→ 剥标记行 → 截断 → 装配批次 `result["summary"]` → 产物 close 的 ok 分支写 `"result": result.get("summary")` 字段（空/缺失不写该键）→ 读侧既有管道拾取渲染。

## 溯源

- 2026-11-06 add-distill-run-work-summary（spec/changes/add-distill-run-work-summary/） — 新增本能力页：终态 result 行 `result` 字段承载主蒸馏工作总结、`KNOWLEDGE_DISTILL_DONE` 转正为剥离锚（fail-open 非成功判据）、2000 字符截断、spawn 返回值扩三元组、失败与折叠子 run 路径不携带总结
