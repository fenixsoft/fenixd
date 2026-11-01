# 存量幽灵条目结构性清退通道

## Why

7f7ee45e2 只修新立项物化路径，存量幽灵条目（本例 + 孪生 fix-planner-scenario-entry-schema-selfcheck）无终态通道：只能 拒绝×2→冻结→人工升级，本例烧掉 5 个评审 run（约 $3.3 台账成本，另有 1 个被重启打断）+ 一次人工升级，才得出一个证据完全确定的「应清退」结论；存量回填也只能显式跳过「留人工排查」。建议：daemon 启动/回填期对账——非终态条目若满足幽灵指纹（注册以来 spec/changes/<name> 目录从未存在且 git 全历史对该路径零提交）→ 结构性落终态（revoked）或聚合为单条批量人工裁决清单，替代逐条 freeze→escalate。

## What Changes

- （arbiter 提案待人工成文：本文件为调查报告提案的最小诚实成文，补全 What Changes / Capabilities / Impact 后走既有晋升流程）

## Capabilities

### New Capabilities

- `<capability>`: （待成文）

### Modified Capabilities

（无）

## Impact

（待成文）

---

- 立项来源：Arbiter 调查（run_id=None，signature=fix-arbiter-proposal-materialize-spec-dir::spec-review-rejected，source=escalation-alert）
- 立项时间：2026-11-01T01:22:50.659570+00:00
