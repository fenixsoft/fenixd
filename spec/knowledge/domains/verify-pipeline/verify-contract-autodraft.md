# 验证契约自主起草
<!-- knowledge: capability=verify-contract-autodraft rev=1 sources=spec/archive/2026-09-13-add-verify-contract-autodraft -->

验证撞上契约缺失或损坏时的框架自主恢复路径：Administrator 起草 `.fenix/verify.yaml` 并经三段自证后落盘，验证链不依赖人类手写契约。

## 现行规则

- 契约缺失路由信号化：最终用户验证因「验证契约缺失或无效」无法获得被测实例时（`.fenix/verify.yaml` 不存在、config `commands.start` 为已知占位符、契约 YAML 解析失败按无契约回退），框架产生结构化信号 `verify_contract_missing`（携带 spec 名、项目根、场景 kind 集；解析失败另标注 `parse_error`）派发 Administrator 起草，不将该情形作为打回 plan 的反馈文本（plan 修不了项目基建缺口）。
- 确定性死局立即派发：验证首次撞上「无 serve 配置」判定时信号立即派发，不走 4 次失败计数或 60 分钟升级冷却；同一 spec 的重复信号仍受信号节流约束（冷却窗口内不重复唤起 Administrator）。
- prepare 失败保持打回 plan：契约存在且 `prepare` 构建步骤失败（构建被实现破坏）属验证环境错误走既有打回 plan 路径，不派 `verify_contract_missing` 信号。
- 起草三段自证门：Administrator 落盘前必须实证 `prepare` 步骤全部执行成功、`serve` 实例启动并可探活、`ready` 就绪探针通过（含鉴别力自检）；自证经框架显式校验入口（`core/verify_contract.py` 校验函数或 bin CLI）执行，未全通不落盘生效。
- 起草收尾：契约落盘后 git 提交（验证契约为随仓库提交的声明），并把被卡 spec 复位 ready 触发重验证；起草与自证 2 轮内仍无法通过时置 `escalate=true`，处置记录附当前草稿全文与逐段失败证据，不落盘半成品契约。
- 契约权限边界：可解析且 serve 段合法的有效契约一律不碰（即使命令触发起草任务，也以「契约有效、无需起草」结案），人类手写/手改始终权威；解析失败或明显失效（如 prepare 指向已不存在的 script、serve root 目录不存在）可修正，修正动作在处置记录 `actions_taken` 留痕（含 diff 摘要）。
- 校验入口：`core/verify_contract.py` 提供契约校验函数（输入项目根或契约路径，输出 prepare/serve/ready 逐段结果与错误详情），`bin/` 提供同校验的 CLI；就绪探针鉴别力自检（SPA fallback 形态判定）纳入校验通过条件。

## 溯源

- [2026-09-13 add-verify-contract-autodraft](spec/archive/2026-09-13-add-verify-contract-autodraft/) — 新增契约缺失/损坏的自主恢复路径：路由信号化（不再作为打回 plan 反馈空转）、admin 三段自证起草门、契约权限边界与校验入口（此前人类不写契约就无人写，验证撞墙烧两轮打回升级后仍须人工应急手写）
