# 处置留痕（非方案 proposal）

> **本文档不是方案成文。** 它由 spec-review run
> `spec-review-fix-arbiter-proposal-materialize-spec-dir-3bf67a-1793494945`
> 于评审收尾时物化，用途是让该幽灵 STATE 条目拥有可审计的载体与完整处置记录。
> 本条目从未有过真实方案——评审结论为 **rejected（format）**，建议人工**清退**
> 本条目而非补写方案重走流程。

## 本条目是幽灵条目的事实链

1. **立项来源**：arbiter 对前一 SPEC `fix-planner-scenario-entry-schema-selfcheck`
   评审器连续失败至尝试上限 3 的处置立项，台账条目
   `arb-ledger-1793494429581`（`.fenix/arbiter_ledger.jsonl`，created
   2026-11-01T00:53:49Z），`action_or_upgrade = "立项落 drafted:
   fix-arbiter-proposal-materialize-spec-dir"`。
2. **立项缺陷**：当时运行中 daemon 的 `_apply_proposals` 只写
   `.fenix/STATE.md` 条目、不创建 `spec/changes/<name>/` 目录——正是提交
   `7f7ee45e2`「fix: arbiter 立项物化草稿目录——裸 STATE 注册产幽灵条目」
   所修的缺陷。
3. **时序竞态**：条目创建于 00:53:49Z，修复 `7f7ee45e2` 落库于
   2026-11-01T08:52:06+08:00（= 00:52:06Z）——**晚于修复落库 103 秒**，
   属旧 daemon 未加载新代码窗口内的重复立项。
4. **循环实况**：spec-review 两次尝试（44ab7e、本 run 3bf67a）均因
   「SPEC 目录不存在」无法完成结论落账（STATE.md 条目
   `_review_attempts: 2`，`MAX_REVIEW_ATTEMPTS = 3`）。

## 主题冗余：方案已被 7f7ee45e2 交付

本条目名称所描述的修复——arbiter 立项时物化 `spec/changes/` 目录——
**已由 `7f7ee45e2` 实现并合入 main**（`core/pm_engine/arbiter.py`
`_materialize_proposal`，先物化后注册、物化失败跳过立项只记台账、重放幂等）。
且现役 daemon（PID 4081668，2026-11-01T08:56:07+08:00 启动）晚于修复落库，
已加载该代码；幽灵条目残留的原因仅是修复不重放存量条目。

**结论**：即使人工补写方案，其内容也与已合入实现完全重合。本条目应直接
清退（cancel / 删除 STATE 条目），不应补写 proposal 重走 impl 流程。

## 评审结论

- 评审结果文件：`.fenix/spec-review/fix-arbiter-proposal-materialize-spec-dir/.fenix-run-result.json`
- status = `rejected`，rejection_class = `format`（被评审对象整体缺失）
- 溯源：`arb-ledger-1793494429581`、`.fenix/STATE.md`（fix-arbiter-proposal-materialize-spec-dir 条目）、git commit `7f7ee45e2`
