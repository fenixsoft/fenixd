## Deliverables

```yaml
- path: core/pm_engine/arbiter.py
  kind: modify
- path: agents/arbiter.md
  kind: modify
- path: tests/test_arbiter_lane.py
  kind: modify
- path: spec/knowledge/_inbox/arbiter-filing-retire-gap-todo-routing.md
  kind: new
```

## 1. 立项通道退役（arbiter.py）

- [ ] 1.1 移除调查报告提案消费写点（三限节流+同主题查重+物化+add_spec 全链）与 `_materialize_proposal`；删除常量 `PROPOSAL_MAX_PER_RUN` / `PROPOSAL_WEEKLY_QUOTA` 及孤立 import；gaps 为空时报告处理零动作
- [ ] 1.2 gaps→todo 路由：消费 `gaps` 数组逐条记 todo.md（走 fs_utils todo 锁 + todo_format 结构契约，标题带 `[arbiter:<签名前8>]` 来源前缀、正文带触发 run_id，按可立项粒度五字段标签）；记录前做轻量同主题去重（标题关键词包含判定，命中跳过）
- [ ] 1.3 台账 kind 演进：记 todo 与去重跳过落 `gap-noted`（含 topic、todo 行号或已存在条目指引）；切换窗检测到旧 `proposals` 字段记 WARNING `gap-noted` 后丢弃（不抛异常不落池）；既有 `spec-proposed` 台账条目不清洗

## 2. prompt 契约红线（agents/arbiter.md）

- [ ] 2.1 红线段改写：「修复走裁决包建议人类或立项」→「修复走裁决包建议人类，框架缺口经报告 gaps 数组上报，由框架记 todo 自进化统一立项」；移除立项节流三限段
- [ ] 2.2 报告 schema 的 proposals 字段改 gaps（含可立项粒度填写说明：topic/证据/影响面/候选方向），与消费端同 commit 切换

## 3. 测试

- [ ] 3.1 退役断言：任意调查报告完结后无新 drafted SPEC（无目录物化、无 add_spec 调用）；旧代码调用点（立项方法/常量）不存在
- [ ] 3.2 路由断言：gaps 数组逐条落 todo.md（结构契约、来源前缀、run_id、锁互斥）；同主题去重命中跳过并落台账；台账 gap-noted 三形态（记入/去重跳过/旧字段容错）
- [ ] 3.3 prompt 与消费端 schema 一致性：报告样例含 gaps 数组可被消费端解析；白名单处置动作回归不受扰（解冻/重验既有用例仍绿）

## 4. 收尾

- [ ] 4.1 全量回归通过 + compileall 自证
- [ ] 4.2 知识治理投递：`spec/knowledge/_inbox/arbiter-filing-retire-gap-todo-routing.md`（arbiter-proposal-filing 页退役注记 + arbiter-lane 页立项节流→禁立项红线改写素材，含本 SPEC 溯源）
- [ ] 4.3 落位 restart_request 信号文件（根路径，JSON：reason/origin/date）并冒烟预演（全新进程 + 消费方 import + arbiter 报告消费链核心 API）；实际重启由 supervisor 消费该信号完成
