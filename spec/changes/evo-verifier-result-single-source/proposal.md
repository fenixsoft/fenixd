# verifier-result-single-source — 验证结果文件读取单一来源

## 背景
主树共享 .fenix/.fenix-run-result.json 同时被 implementer（写入 status=success/error）与 verifier（写入验证裁决）两种写入者使用，语义异义。add-web-ui 事件链中，legacy verifier 读到主树共享文件里的 implementer 残留 status='success'（白名单外）判 blocked，验证链冻结约 3 小时、+$24.6 空转、4 次 admin 处置。同一缺陷已复发两次（_read_planner_result 路径修过一次、legacy 路径漏修一次）。读取侧 D5 修复已落地（verify-progress 优先 + spec 戳/mtime 双校验），但结构性风险未消除且回归测试缺失。

## 目标
- verifier 结果读取仅以 verify-progress/<spec>/.fenix-run-result.json 为单一来源；主树共享文件仅作兼容回退，且回退必须过 spec 戳 + mtime 双校验。
- 消除「implementer 写主树共享文件」这一语义异义：implementer 结果改写到 verify-progress/<spec>/ 或带明确 spec 戳 + role 字段。
- 补「implementer 残留 success 污染」回归测试，固化 D5 行为，防第三次复发。

## 非目标
- 不改验证裁决稳定性（judge 重跑上限，见 judge-rerun-stability）。
- 不改费控语义（见 infra-failure-budget-exempt）。

## 验收
- 单测：implementer 残留 status=success 污染主树共享文件时，任何读取路径不将其当验证裁决。
- 主树共享文件被写入时带 role 字段（implementer/verifier）与 spec 戳。
- 回归：重放 add-web-ui 事件链不再产生 unknown-status 误判。