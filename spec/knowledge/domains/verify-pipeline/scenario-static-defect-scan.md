# 场景静态缺陷扫描
<!-- knowledge: capability=scenario-static-defect-scan rev=1 sources=spec/archive/2026-09-15-add-scenario-defect-triage-gate -->

场景执行前的模式表驱动静态扫描：纯 Python 零 token 检出「结构合法但内容必败」的已知缺陷模式，产出结构化情报供 judge 定向修复。只做情报、不拦截执行。

## 现行规则

- 扫描时机：每轮验证的场景执行前（`_apply_scenario_freeze` 完成后）对生效场景集（test_scenarios.json）执行静态缺陷扫描。
- 模式表驱动：扫描器以可扩展的模式表驱动（新增模式不改扫描器主体），初始模式包含——
  - 跨轮字面端口残留（cli/api）：steps `command`/`stdin` 文本中的字面端口号 ≠ 本轮 serving 实例端口 → 报「运行时必须引用 `FENIX_VERIFY_PORT` / `FENIX_VERIFY_BASE_URL` 环境变量」；端口一致时不产出 finding（不报脆弱绑定类低价值情报）。
  - 跨轮 navigate URL 残留（web）：`navigate` 步骤 URL 字面端口 ≠ 本轮 serving 端口 → 报「执行时引擎以契约 base_url 为准，但该场景入口指向已失效端口」。
  - 双汉字文本选择器（web）：steps `target` 或断言中恰好 2 个汉字的文本匹配 → 报「antd Button autoInsertSpace 将双汉字文本渲染为『X X』，建议改用 getByRole(name) 或含空格变体」。
- finding 结构：每条含 `scenario_id`、`rule_id`、`location`（场景内定位）、`message`（缺陷说明与修复方向）。
- findings 落盘与情报注入：findings 结构化落盘 `.fenix/verify-progress/<spec>/scenario_static_findings.json`（每轮覆盖写），并在 judge（planner-judge）prompt 构建时注入定向情报段——段内声明检出场景的缺陷修复属 judge 职责（原地修复协议、申报 scenario-repaired），judge 对已检出场景必须先修复已知缺陷再裁决；findings 为空时不注入该段。
- fail-open 扫描边界：静态扫描属辅助情报，扫描器任何异常（场景文件读取失败、模式匹配异常等）记 WARNING 后跳过本轮扫描，不阻断验证流程、不产生 error 终态；serving 端口未知的轮次，端口比对类模式整体跳过（双汉字等纯文本模式仍可执行）。

## 溯源

- 2026-09-15 add-scenario-defect-triage-gate（spec/archive/2026-09-15-add-scenario-defect-triage-gate） — 新增场景执行前的模式表静态扫描（跨轮端口残留/双汉字文本选择器）、findings 落盘与 judge 情报注入、fail-open 边界（此前场景跨轮环境假设随 replan 写回带进新一轮，seed 未建成导致下游场景连锁失败）
