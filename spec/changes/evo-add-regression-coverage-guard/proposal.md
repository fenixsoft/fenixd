# 提案：prepare 装配与回归白名单一致性预检

## Why

verify contract 的「新增被测集扩编」没有 prepare↔regression 一致性约束，扩编做一半静默成立：2026-11-12 admin 为 add-session-advanced-search 环境阻塞把 fenix-dsh-session-advanced-search 加进 dsh-plugins 契约 prepare 段（install+build），regression 段漏收编——regression.cmd 至今只含 cc-import 与 dashboard-bridge。后果已兑现：11-14 18:55 至 11-15 01:20 合并入 main 的 63 条 fixed 项（38+21+1+3）零插件面验证——fix worktree 内 tsc/vitest 结构性不可用（worktree 供给只覆盖根目录，插件目录永无 node_modules——sub_dirs 由 prepare 步骤 cwd 属性派生（core/worktree_manager/lifecycle.py:554），--dir 内联形态无 cwd 属性、恒为 ["."]），链收尾回归每批固定 182 项约 7 秒且与 merge 同秒对齐（182/182 全绿——门是真的、眼睛是瞎的）。63 条修复连同「行为面变化处均同步改写」的测试断言双双零执行，坏断言可无症状滞留 main；SAS 9 个+session-grouper 4 个测试文件至今无任何执行记录，敞口随每次合并与周期回归持续再生（核查时点 02:03 周期回归仍 182 项同形态）。「契约段位扩编做一半」族已跨日三度在案（11-08 模板态、11-09 regression 段、11-11 serve 段，草稿 verify-contract-serve-sync 在案），本条是该族在回归声明面的第 4 度。

## What Changes

- **prepare↔regression 一致性预检（core/verify_contract.py）**：契约解析/校验时对 prepare 段 install/build 步骤声明的包目录集合与 regression cmd 文本引用集做交叉比对，命中「prepare 装配了 X 而 regression 全文无 X 引用」时发 `regression_coverage_gap` WARNING（含缺口包清单与 regression 段行号指引），不阻断加载、不触发 replan——让半收编在配置装载面即发声，而非等消费期事故考古。
- **模板指引同步（core/verify_contract_template.yaml）**：regression 段指引补「新增被测插件进 prepare（install/build）时 MUST 同步在 regression 注册 install+test 条目（--frozen-lockfile --prefer-offline 形态）」，prepare 段指引补对称提示——收编指引在作者当下可见，不依赖事后检查。
- **（人工步骤，登记 todo.md 不入任务书）** dsh-plugins 项目侧 .fenix/verify.yaml regression.cmd 补两个插件的 install+vitest 条目（先例已在同文件 :57/:59）——项目运行时文件由人工/项目侧执行。

## Capabilities

- `specs/regression-coverage-guard/spec.md` — ADDED：prepare 装配与回归白名单一致性预检

## Impact

- **受影响模块**：`core/verify_contract.py`（解析/校验路径追加交叉比对与 WARNING）；`core/verify_contract_template.yaml`（指引文案）；新增专项测试。
- **兼容性**：对称契约（prepare 包 ⊆ regression 引用）零输出；检查为纯读侧 WARNING，不阻断任何现有流程；非包形态契约（纯 pytest cmd）按形态启发式识别，识别不出即保守跳过。
- **无 UI、无数据迁移、无配置键**；直接效果：本例形态的半收编契约在下次装载即发缺口告警，模板指引防再犯。