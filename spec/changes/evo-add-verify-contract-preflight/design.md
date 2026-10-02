# add-verify-contract-preflight design

## Context

- 事故实证：potplayer-base/cimbar-airgap-transfer 2026-10-02，验证消费期轻量自证对全注释模板 fail-fast（core/verify_contract.py:2035-2038），spec 卡 blocked 约 26 分钟（信号 6218aba50ea5 06:35:16Z → 处置 07:01:01Z），2 个 admin run（1790922917 空转、1790923106 落地提交 c7131a5）。
- 既有设计：ADR-080 选择「首次消费检测 + 自主起草」，恢复半程已制度化（add-verify-contract-autodraft / add-verify-preflight-gate / fix-verify-contract-signal-semantics）；本 SPEC 不改该决策，只把同一信号的触发时刻前移。
- 复发面：fenix-init:145-155 无条件向每个新项目写全注释模板；verify_contract.py:2006-2007 缺失放行、:2035-2038 存在即 fail-fast——每个新项目首次验证消费确定性踩一次。

## Goals

- 契约起草与规划/实现并行，消除新项目首个 spec 的验证段串行阻塞与重复 admin run。
- 零新机制：复用既有信号类型、注册表、前置探测、节流与起草指引。

## Decisions

- **检测器挂在 admin_monitor 周期巡检**（core/admin_monitor.py:1932 `_detect` 汇总处加一项）：巡检天然持有 project_root 与 specs 状态，且检测器返回值自动进入既有「落 store → 摄取 → 唤起」链路。不改 pm_engine 派发路径（dispatcher 无契约上下文，改动面更大）。
- **只读判定收在 verify_contract.py**：新增公共函数（如 `contract_file_unresolvable(project_root) -> bool`），内部复用 `_load_verify_contract_with_raw`（:252），以「文件存在且返回 (None, None)」为真；文件缺失返回假。单次读取同源，避免第二套解析口径漂移。
- **触发窗口取 ready/implementing**：spec 进入 testing 后消费期 fail-fast（pipeline.py:2850-2894）已是权威检测点，前置检测器在 testing 及之后静默，保证同一形态不双发信号。
- **description 注明「前置预检」**：与消费期信号文案区分，Administrator 处置可识别触发来源；recommended_action 复用既有起草指引（admin_monitor.py:346），不另写一套。
- **description 须注明「勿复位 spec 状态」**：ADR-080 收尾动作「spec 复位 ready 触发重验证」是消费期场景语义（spec 已被验证失败打断）；前置信号触发时 spec 尚在 ready/implementing、可能有活跃实现 run，且 VALID_TRANSITIONS 允许 IMPLEMENTING→READY（admin_monitor.py:4676）——Administrator 机械复位会把进行中的实现打回重做、与活跃 run 收尾竞态。前置起草落位即可（验证消费点届时经 mtime 门直接放行），description 须写明「spec 仍在实现流程中，起草落位即可，勿复位 spec 状态」。
- **项目级单例信号**：契约是项目级产物（一个项目一份 .fenix/verify.yaml），既有节流按 (spec, signal_type) 判定、对不同 spec 不互斥——检测器若按命中 spec 逐个产出信号，N 个 ready/implementing spec 会放大为 N 次唤起。检测器 MUST 只返回一条信号（spec 字段取首个命中 spec），同项目多 spec 命中不放大唤起。
- **不收「文件缺失」形态**：ADR-080 与 verify_contract.py:2006-2007 的「缺失=合法回退」是既定语义，前置预检只治理「模板态文件挂着从未裁决」这一确定性缺口，避免把无契约项目误入起草强制流。

## Risks

- **信号噪音**：巡检周期内重复命中——依赖既有同 spec 信号节流与 PREPROBE 满足即免唤起；测试须覆盖「有效契约不触发」「已消费期不触发」两个抑制分支。
- **起草时机早于实现定形**：实现中途变更构建体系可能使前置起草的契约失准——既有权限边界已覆盖（「明显失效可修且留痕、有效契约不碰」），且消费期自证 mtime 门会在契约变化时重证。
- **检测器自身异常**：对齐巡检惯例 fail-open（异常不阻断其余检测），不让预检缺陷拖垮监视器。