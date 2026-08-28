# Tasks: 修复 fix-fix-add-spec-context-menu 验证发现的缺陷

## 1. 定位根因并确认伪失败性质

- [x] 1.1 阅读 `openspec/changes/fix-fix-add-spec-context-menu/verification-report.md` 与 `.fenix/verify-progress/fix-fix-add-spec-context-menu/report.json`，复现并定位 11/12 失败的根因
- [x] 1.2 以真实浏览器复现，确认 `.spec-name-cell[data-spec]` 不可见的唯一原因是 `mock_api` 的 URL 模式（`https://localhost/**/api/...`）与被测实例真实地址（`http://127.0.0.1:{port}/api/...`）协议+端口双重不匹配，属测试基础设施伪失败，非产品缺陷
- [x] 1.3 运行框架单元测试（`tests/test_dashboard.py` 中 spec-priority / spec-delete / spec-admin-invoke 相关用例）确认后端 API 健康、前端 app.js 上下文菜单代码已正确实现

## 2. 修复伪失败根因（mock 协议/端口不匹配）

- [x] 2.1 将 `.fenix/verify-progress/fix-fix-add-spec-context-menu/test_scenarios.json` 中所有 `mock_api` 的 target 由 `https://localhost/**/api/...` 修正为与真实被测实例一致的 `http://localhost:8787/**/api/...`（已重写 31 处目标）
- [x] 2.2 同步修正 `.fenix/verify-progress/fix-fix-add-spec-context-menu/report.json` 中对该批场景的误判结论（将「系统性 Critical 产品 Bug」更正为「测试基础设施伪失败 / blocked-env」），并补充根因证据；同步更新 `.fenix-run-result.json`

## 3. 验证与打包

- [x] 3.1 运行框架单元测试（`python3 -m pytest tests/test_dashboard.py -q`）确认无回归（115 passed, 0 failed）
- [x] 3.2 执行 `bash scripts/package.sh` 生成最新扩展包（fenixd-20260828.tar.gz, 332K）
