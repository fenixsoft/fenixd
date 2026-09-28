## Deliverables

```yaml
- path: agents/code-fix.md
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
```

## 1. 并行处置协议（提示词改造，D1–D3）

- [x] 1.1 `agents/code-fix.md` 新增「并行处置」段：批含 ≥2 文件组且条目 >2 时以组为粒度派子代理，同波并发 ≤3、完成即补派（波次语义）；组 prompt 携带该组条目 JSON + 修复契约（最小改动/fenix-ignore 标记规则/out 行格式/禁自行写 out_path/禁自行验证提交）
- [x] 1.2 单写者落盘规则：子代理返回结构化结果（每条目一行记录），orchestrator 校验 `item_id`/`status` 必填后**立即**追加写该组全部行到 `{out_path}`；MUST NOT 攒批；单组批/条目 ≤2 不派子代理直接串行处置

## 2. 失败兜底与验证提交（D5–D6）

- [x] 2.1 子代理失败三级兜底写入提示词：报错/超时/产物不可解析 → orchestrator 亲自重做该组；重做仍失败 → 按既有 skipped 语义标注；非法行（缺 item_id/status）→ 该组重试一次，仍非法条目按未处置 skipped 且 MUST NOT 写非法行；单组兜底不阻塞其他组
- [x] 2.2 汇总后一次验证一次提交的既有段落与并行协议衔接（子代理禁自行验证/提交；全部组落盘后按触碰面一次定向验证 + 单次 commit 列全批 item_id）

## 3. 测试

- [x] 3.1 提示词内容回归测试（tests/test_code_fix.py 既有 prompt 测试风格）：并行段关键约束在场（≤3 并发/单写者/单组退化/禁子代理写 out_path）；占位符 {items}/{out_path}/{worktree} 完整性不破
- [x] 3.2 端到端实证（verify 场景驱动）：多组批跑真实 run——子代理并发发生、out 行随组增量出现、单次提交、回归+合回契约不变；对照串行基线记录 agent 段耗时（对比 [[fenixd-codefix-prompt-slim-baseline]] 口径）
