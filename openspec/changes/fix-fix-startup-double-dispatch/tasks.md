# Tasks: 修复 fix-startup-double-dispatch 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/fix-startup-double-dispatch/verification-report.md`，定位「真实产品 Bug」的根因并修复（裁决：父验证报告 10 个失败场景全部为伪失败——场景断言的状态文本/选择器与产品实际 DOM 不符；父 SPEC 产品代码（单飞守卫、状态回写保护、verifier 终态对账）已正确实现且单测全过，无需改动产品代码。详见本 SPEC 的 `verification-report.md`）

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（v3 dashboard `max build` 通过，构建产出 dist chunk hash 变更属无源码改动的重哈希，不纳入提交）
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归（`tests/` 全量 947 passed；唯一失败 `test_v2_dev_server.py::TestAllocatePort` 为本机 19001 端口被运行中 dev-server 占用的环境相关失败，非产品缺陷。父 SPEC 相关单测 `test_startup_double_dispatch.py` 10 项 + `test_pm_verification.py`/`test_pm_dispatch.py` 56 项全过）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（dist/fenixd-20260902.tar.gz）
