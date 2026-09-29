<!-- knowledge: capability=shared-result-file-integrity rev=1 sources=spec/archive/2026-09-18-fix-fasttrack-resultfile-missing-redispatch -->

# 共享结果文件完整性

主树共享实现结果文件的 stamp 严格匹配与消费后清理：跨 spec 残留一律拒绝采信，成功 run 不因残留误判失败。

## 现行规则

- stamp 严格匹配：读取主树共享结果文件 `.fenix/.fenix-run-result.json`（`_read_implementer_result` 的 fallback 路径）时，仅当文件 `spec` 字段为字符串且严格等于当前 spec 名才采信；`spec` 缺失、为空、非字符串或与当前 spec 不符（含旧格式/异常残留）一律 ignore（返回 None），无 stamp 残留不 fail-open 采信。
- 消费后清理：共享结果文件被某 spec 采信消费并落盘 per-spec 快照（`.fenix/verify-progress/<spec>/impl-result.json`）后即时删除，已消费残留不跨 spec 存留，消除对后续 spec 死亡判定/读侧的误拦与噪声；删除失败仅记 WARNING 不阻塞主流程（fail-open，残留由 stamp 严格校验兜底拒绝）。
- 残留语义：共享结果文件与 spec 不符视为残留——残留不作为失败证据，成功 run 不因残留误判失败。

## 溯源

- 史前复原 — 迁移期基线：共享结果文件与 spec 不符视为残留；残留不作为失败证据，成功 run 不因残留误判失败
- [2026-09-18 fix-fasttrack-resultfile-missing-redispatch](spec/archive/2026-09-18-fix-fasttrack-resultfile-missing-redispatch/) — 固化 stamp 严格匹配契约（关闭无 stamp 的 fail-open 洞）与消费落盘快照后的即时删除
