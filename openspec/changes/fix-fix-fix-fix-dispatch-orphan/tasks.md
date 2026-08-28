# Tasks: 修复 fix-dispatch-orphan 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/fix-dispatch-orphan/verification-report.md`，定位「真实产品 Bug」的根因并修复（裁决：10 个失败场景均为伪失败，父 SPEC 产品代码已正确实现且 28 个相关单测全过，无需改动产品代码；详见本 SPEC 的 `verification-report.md`）

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（本仓库无构建源码/package.json，dashboard 为预构建并提交产物；本 SPEC 不改 dashboard 代码，`core/dashboard/static/app.js` 通过 `node --check` 语法校验）
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归（586 passed）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（dist/fenixd-20260828.tar.gz）
