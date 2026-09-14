# 设计 — judge-rerun-stability

## 裁决缓存
- 在 verify-progress/<spec>/verdict_cache.json 持久化最近两轮 verdict（status + 失败场景 id 集 + spec 戳 + report.json mtime）。
- 复用判据：spec 戳未变 && report.json mtime 未变 && 两轮 verdict 一致 → 直接复用，不重派 judge。
- 该文件已有雏形（add-web-ui/verdict_cache.json 存在，见 verify-progress 目录）。

## verified 放行
- 在 pm_engine 裁决应用处（verification.py 的 _apply_* 与 _run_legacy_verification 公共出口）加一道「verified 门」：读 .fenix-run-result.json 若 status=verified 且 spec 戳匹配当前 spec、无场景集变更，任何路径不得覆盖为 blocked。
- 与既有 fail-closed（D4/D5）对称：fail-closed 管「不可读不得晋级」，本设计管「已 verified 不得降级」。

## 计数
- judge_rerun_count 写入 STATE.md 增量时间线，run 收尾时增量。

## 改动点
- .fenix/core/pm_engine/verification.py：verified 放行门 + verdict 缓存复用。
- .fenix/core/pm_engine/family.py：judge 重跑计数与硬上限。
- .fenix/core/verify_report.py：verdict_cache.json 读写。