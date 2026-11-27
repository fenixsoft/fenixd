# 设计：prepare 装配与回归白名单一致性预检

## Context

regression.cmd 纯数据驱动（core/regression.py:988/:1084/:1099-1106，框架只执行项目声明字符串），契约解析（core/verify_contract.py:790-874）只校验 cmd/output 必填与形态，无任何「regression 须覆盖 prepare 所装包」检查；模板 core/verify_contract_template.yaml 无镜像注册指引。fix worktree 供给结构性覆盖不到插件目录（sub_dirs 由 prepare 步骤 cwd 属性派生，core/worktree_manager/lifecycle.py:554——--dir 内联形态无 cwd 属性、恒为 ["."]；provision_worktree_node_modules（core/verify_contract.py:2194）落根 npm ci 秒退），worktree 内 tsc/vitest 恒不可用——回归是插件面验证的唯一通道，声明面盲区让它空转。「扩编做一半」族跨日三度在案。

## Goals / Non-Goals

- **Goals**：半收编契约在装载面即发声（WARNING+缺口清单）；模板层把同步注册写进作者指引；不阻断、不 replan、零迁移。
- **Non-Goals**：不代改项目侧 verify.yaml（gitignored 运行时文件，人工/项目侧步骤，登记 todo.md）；不动 worktree 供给机制（sub_dirs 扩展属独立结构性课题）；不做 regression 自动发现全部测试套件（声明面显式注册优先，动态发现可作后续演进）。

## Decisions

**D1 检查挂契约解析/校验路径，纯读侧。** 解析期两段同场可见（单点、零新触发器）；WARNING 不阻断——配置面软告警与消费期硬门（回归通过才合回）分工，与 verify-contract-serve-sync 草稿的「前置校验不阻断落盘」裁定同型。

**D2 包目录启发式识别，保守跳过。** prepare 步骤按 `--dir <pkg> install/build`（pnpm 形态）提取包目录集；regression 引用集取 cmd 文本包含判定；识别不出形态即跳过——误报比漏报更伤（会稀释真缺口告警）。提取形态覆盖两变体：`--dir <pkg> install`（含尾随 flags）与 `--dir <pkg> run build`（dsh-plugins 契约实文形态）。regression 段整体缺省时视同非包形态保守跳过——模板明文「缺省不配 = 未配置全量回归」是合法引导态（分面显示、不派发、零报错），常驻全量缺口告警与之冲突；本检查只治「regression 已配置但收编不全」。

**D3 缺口告警带定向情报。** WARNING 附缺口包清单与 regression 段行号指引（对照 serve_missing_for_scenario_kinds 的「携带定向补段情报」先例），让下一次扩编一步到位。行号指引实现口径：复用解析路径既有同源 raw 文本（`_load_verify_contract_with_raw` 单次 read_text）做锚点扫描定位 regression 段行号，不引 yaml Mark。

## Risks

- 识别启发式漏判（非 pnpm 形态装配）：保守跳过不误报；模板指引兜住作者侧。
- 告警疲劳：对称契约零输出（Scenario 钉死），仅真实缺口发声。