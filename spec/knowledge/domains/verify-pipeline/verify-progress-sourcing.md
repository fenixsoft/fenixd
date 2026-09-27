# 验证进度读取源
<!-- knowledge: capability=verify-progress-sourcing rev=1 sources=spec/archive/2026-09-11-fix-verify-progress-fasttrack -->

Dashboard 验证进度数据源契约：进度文件优先，缺失时回退 fast-track 裁决结果文件合成，双缺维持空态。

## 现行规则

- 数据源优先级（`core/dashboard/data.py` 的 `parse_verify_progress`）：① 进度文件 `.fenix/verify-progress/<spec>.json` 存在且可解析 → 使用之（full 模式 verify_engine 逐场景推进路径）；② 进度文件缺失 → 回退读裁决结果文件 `.fenix-run-result.json` 的 `verification.scenarios`（fast-track schema）合成进度；③ 进度文件与结果文件皆不可得 → 返回 `exists: false`（空态语义，前端「暂无验证进度」与列表兜底展示生效）。
- 回退合成口径：`total` = 场景条目数；`done` = 含 `status` 字段的条目数（fast-track 一次性判定，正常等于 total）；`current` = 终态文案「验证完成: N通过, M失败, K错误」——`pass` 计通过、`fail`/`failed` 计失败（双用词兼容）、`error` 计错误、`warning`/`exempt` 为豁免类不计入三桶。
- 结果文件查找顺序：`.fenix/verify-progress/<spec>/.fenix-run-result.json`（专属副本）→ `.fenix/.fenix-run-result.json`（主树共享文件，携带 spec 与当前 SPEC 不符时忽略）。
- 来源可区分：回退合成成功时返回对象携带 `source: "run-result"` 标记；进度文件路径携带 `source: "file"` 或不携带——两形态可区分，供展示层与测试分辨数据来源。
- 列表空数据兜底：spec 列表「验证」列在验证数据整体缺失（`verify_total` 为 0）时展示 `—` 而非 `0/0`，消除「数值计数」与「尚无验证数据」的语义混淆；`verify_total > 0` 时维持 `done/total` 数值展示。

## 溯源

- 2026-09-11 fix-verify-progress-fasttrack — 新增 fast-track 裁决结果文件回退合成验证进度并加来源标记（fast-track 不产进度文件，spec 列表验证列此前恒 0/0 空态）、列表空数据改「—」占位
