# 设计 — verifier-result-single-source

## 读取抽象
- verification.py 新增统一入口 _read_verdict(spec_name)：verify-progress/<spec>/.fenix-run-result.json → 缺失或不可读时回退主树共享（经 _verifier_result_is_stale 双校验）→ 仍无则返回 unreadable。
- legacy（_run_legacy_verification）与 planner（_read_planner_result 裁决应用处）全部改走该入口，删除各自独立路径。

## 写入隔离
- implementer run 收尾写 verify-progress/<spec>/impl-result.json（多数 spec 已遵守，add-web-ui/impl-result.json 存在）；主树共享文件写路径补 role=verifier 与 spec 戳字段，无 role 视为废弃。
- 兼容期：读侧对主树共享文件先验 spec 戳，不匹配即丢弃（现状 _verifier_result_is_stale 已有 spec 戳=mismatch 判据）。

## 回归护栏
- 新增 impl-result 污染自检：主树共享文件 status=success 且 role≠verifier 时，系统记录 deliverable-dispute 而非作为验证裁决。

## 改动点
- .fenix/core/pm_engine/verification.py：统一 _read_verdict 入口 + 双校验回退。
- .fenix/core/pm_engine/engine.py：主树共享写路径挂 role/spec 戳。
- tests/test_verdict_contamination.py：污染回归测试。