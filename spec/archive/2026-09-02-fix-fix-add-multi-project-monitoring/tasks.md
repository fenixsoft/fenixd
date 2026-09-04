# Tasks: 修复 fix-add-multi-project-monitoring 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/fix-add-multi-project-monitoring/verification-report.md`，定位「真实产品 Bug」的根因并修复

> **调查结论（无真实产品 Bug 可修）**：父 SPEC `fix-add-multi-project-monitoring` 目录下不存在
> `verification-report.md`（该 SPEC 仅含 proposal.md 与 tasks.md），其验证失败记录于
> `.fenix/verify-progress/` 与 run 日志：3 次尝试全部因**测试基础设施**失败——
> a1/a2「claude CLI Max turns (150) reached」、a3「API Error: 400 Model do not support
> image input」（验证器读取截图时模型不支持图片）。依据本 SPEC proposal「伪失败
> （测试框架/场景缺陷）不在修复范围内」，这些不构成需修复的真实产品缺陷。
>
> 作为替代性核实，已将 `fix-add` 的 8 个验收场景与父父 SPEC `add-multi-project-monitoring`
> 的 17 个场景逐一对照当前实现（`app.js`/`watcher.py`/`data.py`/`registry.py`/`server.py`）：
> daemon 徽标 `running`/`stopped` 严格匹配、unknown 值不渲染、缺失字段容错、`自动发现`
> 徽标（`st-muted`）、顶栏下拉 `（自动）` 后缀、`路径不存在` 标注、项目名 `esc()` 转义
> （XSS 安全）、2s 心跳（`refresh` 事件仅在 overview 视图触发重拉，commmit 4c6ef8c）均已正确
> 实现。验证器 a1/a3 的真实数据测试也确认心跳修复生效。**无代码改动需求。**

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过
  - 不适用：Dashboard 前端为原生 JS（`core/dashboard/static/`），仓库无 `package.json` 构建链。
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归
  - `python3 -m pytest tests/ -v` → **262 passed**（覆盖 dashboard/registry/daemon-health/SSE 心跳等，无回归）。
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
  - 生成 `dist/fenixd-20260825.tar.gz`（232K）。
