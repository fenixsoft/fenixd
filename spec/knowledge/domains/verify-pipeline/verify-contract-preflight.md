# 验证契约模板态前置预检

<!-- knowledge: capability=verify-contract-preflight rev=1
     sources=spec/archive/2026-10-07-evo-add-verify-contract-preflight -->

spec 尚未进入验证消费时，由周期巡检提前发现「契约文件挂着却从未裁决」的模板态并唤起 Administrator 起草，使契约起草与规划/实现并行，而非在验证消费点串行阻塞。

## 规则

- 触发窗口为 ready/implementing：项目存在状态为 ready 或 implementing 的 spec，且 `.fenix/verify.yaml` 存在但 yaml 解析不产生顶层映射（全注释模板、语法损坏、空文件均属此形态）时，巡检写 `verify_contract_missing` 信号。testing 及之后不写——该形态由验证消费期轻量自证 fail-fast 与其信号通道负责，前置窗口与消费窗口互斥不双发。
- 文件缺失不触发：`.fenix/verify.yaml` 不存在是「无契约回退」的合法形态，前置预检只治理「模板态文件挂着从未裁决」这一缺口，不把无契约项目卷入起草强制流、不扩大触发面。
- 有效契约不触发：`.fenix/verify.yaml` 可解析为顶层映射（含实质 prepare/regression 或 serve 段）即视为已裁决，巡检不写任何契约信号。
- 信号形态零新机制：复用既有 `verify_contract_missing` 信号类型与 store 通道，description 注明「前置预检：验证契约仍为未裁决模板态；spec 仍在实现流程中，起草落位即可，勿复位 spec 状态」，evidence 含项目根与契约路径，recommended_action 沿用既有起草指引；不新增信号类型、不新增去重机制。
- 处置收尾语义随窗口：前置场景不得沿用消费期的「spec 复位 ready 触发重验证」收尾——触发时 spec 可能有活跃实现 run，且 IMPLEMENTING→READY 属合法状态转换，机械复位会把进行中的实现打回重做、与活跃 run 收尾竞态；前置起草落位即可，spec 推进到验证消费点时经契约 mtime 门直接放行。
- 项目级单例信号：同项目多个 ready/implementing spec 命中时只产出一条信号（spec 字段取首个命中 spec）。契约是项目级产物（一个项目一份 verify.yaml），既有节流按 (spec, signal_type) 判定、对不同 spec 不互斥，按 spec 数量产信号会把唤起放大 N 倍。
- 起草质量门不前移：前置触发只提前起草时机，草稿仍须过三段自证（prepare 执行成功、serve 可探活、ready 探针通过）全通才落位生效，权限边界照旧——有效契约一律不碰。
- 在途闭环：信号已写而未唤起期间契约被修正为可解析时，既有前置探测（PREPROBE）判定诉求已满足，免唤起 Administrator，信号闭环。
- 落点单源：只读判定函数 `contract_file_unresolvable(project_root)` 收在 `core/verify_contract.py`，内部复用既有 loader（`_load_verify_contract_with_raw`）单次读取，以「文件存在且解析为 None」为真、文件缺失为假，不二次读取、不引入第二套解析口径；检测器 `_detect_verify_contract_unresolved` 挂 admin_monitor 周期巡检 `_detect` 汇总，产出自动进入既有「落 store → 摄取 → 唤起」链路，检测器自身异常对齐巡检惯例 fail-open（不阻断其余检测器，异常路径不产信号）。

## 溯源

- 2026-10-07 evo-add-verify-contract-preflight（spec/archive/2026-10-07-evo-add-verify-contract-preflight/） — 新增本能力页：实现期契约模板态前置巡检（ready/implementing 窗口、项目级单例、勿复位收尾），把契约起草从验证消费点前移到实现阶段并行（此前每个新项目首个 spec 首次推进到验证段必卡 blocked，等待自主起草解锁，实测单次卡 26 分钟并连发 2 个 admin run）
