# 基线失败集合 — refactor-dashboard-data-module

> 基线时间：2026-09-15 | spec: evo-*/fix-* 31252f71
> pytest output: 1 failed, 608 passed, 8 skipped, 16 warnings

## 重构前基线失败

| 测试用例 | 失败原因（短描述） |
|---|---|
| `tests/test_dashboard_api.py::TestServerAPI::test_index_served` | index HTML 页面断言失败（与 data.py 重构无关，存量失败） |

## 说明

- 本基线用于重构后比对：重构引入的新失败 = 重构后失败 - 上述集合
- 该失败与 `core/dashboard/data.py` 拆分无关（index served 测试的是 HTTP server 静态文件服务），属于**存量失败**，不影响重构验收
