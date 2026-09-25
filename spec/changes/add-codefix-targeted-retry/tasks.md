## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: agents/code-fix.md
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_codefix_targeted_retry.py
  kind: new
```

## 1. 失败明细结构化落盘

- [ ] 1.1 回归 junit 产物 → 失败用例明细提取（nodeid 近似重构 + 失败摘要），落盘 `.fenix/code-review/fix-reg-failures-<run_id>.json`（`{items, source_run_id, created_at}`），写入点在首轮回归非 passed 分支
- [ ] 1.2 映射失败（非 pytest 形态/字段缺失）时留日志并置 `fallback_full` 标记，重试侧据此回退全量

## 2. 子集回归与重试循环

- [ ] 2.1 `core/agent_runner/maintenance_runs.run_regression` 门面增可选 `subset_nodeids` 参数：项目命令为 pytest 形态且子集非空时追加用例参数执行；否则忽略子集跑全量；锁根/执行根透传语义逐字不变
- [ ] 2.2 `core/code_fix.py` 重试分支改造为定向轮循环（上限 `admin.code_review_fix.targeted_retry_max`，缺省 3）：每轮同 worktree 派 run（注入累计失败明细）→ 子集回归；passed 走既有合回；耗尽走既有现场即弃（档案含明细引用）
- [ ] 2.3 轮间累计明细：上一轮子集重跑仍失败的用例合并进下一轮注入集
- [ ] 2.4 `.fenix/config.template.yaml` 增 `admin.code_review_fix.targeted_retry_max`（缺省 3，注释约束 1-5）

## 3. 提示词契约

- [ ] 3.1 `agents/code-fix.md` 增定向修复契约段：失败可能是产品缺陷或测试缺陷、自行判定；修测试时产物行标 `fix_scope=test`；只修失败用例相关问题、MUST NOT 扩面重做全批

## 4. 验证

- [ ] 4.1 单测（tests/test_codefix_targeted_retry.py）：首轮 passed → 零定向轮（现状路径零变化）
- [ ] 4.2 单测：首轮失败 k 例 → 定向轮子集回归只执行 k 例、passed → 合回核销
- [ ] 4.3 单测：修测试路径（`fix_scope=test` 标注落产物行）
- [ ] 4.4 单测：耗尽 3 轮 → 现场即弃（档案含 `branch`/`tip_sha`/明细引用、锁释放、链继续）
- [ ] 4.5 单测：非 pytest 命令或映射失败 → 回退全量重试（fail-closed）
