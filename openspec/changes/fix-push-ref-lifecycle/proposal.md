# Proposal: fix-push-ref-lifecycle

## Why

2026-08-27/28 实证 done→pushed 的 git push 存在四类缺陷：1) 对远端已存在同名分支（SHA 与本地一致）重复推送，本地缺少 remote-tracking 导致 push 变成"创建"命令被远端以 `cannot lock ref: reference already exists` 拒绝（3 例：improve-scheduling-noise-governance、fix-fix-dispatch-orphan、improve-verify-adjudication）；2) 推送失败的 spec 停在 done 状态，每轮 30 分钟扫描的 verified→done recovery 反复重放推送，同类失败永不收敛；3) merge-back 后本地分支被清理的路径上，重推同名分支报 `src refspec does not match any`（5+ 例）；4) origin/main 落后本地 134 个提交——主交付物从未推送，远端只有散落的 feature 分支。用户在多处任务上看到 push failed 信息，实为账面噪音 + 主线缺位。

## What Changes

- **main 为主交付物**：done→pushed 的首要动作改为 `git push origin main`（非 fast-forward 时失败并保留人工介入），feature 分支推送降级为 best-effort 记录性动作。
- **remote-aware 去重**：推送 feature 分支前先 `git ls-remote` 比对远端 SHA——与本地一致视为已推送（成功路径）；本地分支不存在但 main 已包含其工作（merge-back 记录）→ 跳过分支推送。
- **失败重试收敛**：done 态的 push 失败重试按指数退避并设上限（默认 3 次），超限发 push_failed 困境信号交 Administrator，不再每轮扫描无限重放。
- **终态残痕清理**：推送最终判定成功（含去重判定）时清除 error 字段；一次性回填清理现存 2 条 pushed 终态的残痕。

## Capabilities

### New Capabilities
- `push-ref-hygiene`: main 优先推送、remote-aware 去重、失败退避收敛与终态残痕清理

### Modified Capabilities

<!-- 无 -->

## Impact

- **代码**：`core/pm_engine.py`（approve_push、_git_push_branch、_resolve_push_branch、verified→done recovery 的重放路径）
- **配置**：`pm.push.retry_backoff` / `pm.push.max_retries`（默认 [300, 900] 秒、上限 3）
- **测试**：pm_engine push 相关用例扩展（去重三分支、退避矩阵、main 非 FF、残痕清理）
