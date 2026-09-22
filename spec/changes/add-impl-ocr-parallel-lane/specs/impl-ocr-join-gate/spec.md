# impl-ocr-join-gate

## ADDED Requirements

### Requirement: testing 出口 join 裁决

`testing → verified` 的门禁自动路径 MUST 增加 ocr 车道完成判据：产物存在、`status` 在白名单（`completed`/`unavailable`）、指纹新鲜。tester 先完成而 ocr 未完成时，spec MUST 停留 testing（tester_run 单飞语义保持，不得重派 tester），由 ocr 车道完成事件唤醒 join 评估。ocr 车道 MUST NOT 单独阻塞在无唤醒的停等态。产物缺失或车道未运行时（如 daemon 重启恢复后 tester 经重派路径再派、无 merge-back 事件），join 判据 MUST 幂等触发车道（在跑单飞去重），MUST NOT 无限停等而车道从未启动。

#### Scenario: tester 先完成时停等 ocr
- **WHEN** tester run 产物判定通过，但 ocr 车道仍在执行
- **THEN** spec 保持 testing、不重派 tester；ocr 车道完成事件触发 join 评估后才发生 testing → verified

#### Scenario: 两车道双绿放行
- **WHEN** tester 产物通过且 ocr 产物 `completed`、指纹新鲜、无非 rejected findings（或 mode=advisory）
- **THEN** join 放行，testing → verified 正常发生

### Requirement: gate 档打回走既有 bug_found 通道且有轮次上限

`verify.impl_code_review_mode: gate`（缺省）时，join 读到 `completed` 且存在非 rejected findings：首次 MUST 经 `testing → bug_found`（reason 注明 ocr findings）→ `implementing` 重派实现者修复，修复轮提示词 MUST 注入 findings 清单与 disposition 处置契约（fixed/rejected/deferred + 非空 reason），修码后重验（定向测试+全量回归）。ocr 修复轮 MUST 有上限 1 次（计数器持久化于 spec entry）；达上限后仍出现的 findings MUST 一律转台账（`items.jsonl`，status=open——台账词表仅 open/resolved/ignored、无 deferred 状态，spec_name 归属本 spec、finding 附处置 reason）且 join 放行。

#### Scenario: gate 档首次发现可修正问题走打回
- **WHEN** gate 档 join 发现 ocr 产物含非 rejected findings，且该 spec 的 `_ocr_fix_rounds` 计数为 0
- **THEN** spec 经 bug_found 打回 implementing，实现者修复轮收到 findings 清单；修复提交后 merge-back、重验、ocr 车道对增量重审；`_ocr_fix_rounds` 递增为 1

#### Scenario: 修复轮上限后 findings 转台账放行
- **WHEN** gate 档 join 再次发现非 rejected findings 且 `_ocr_fix_rounds` 计数已达 1
- **THEN** 全部该批 findings 写入 code-review 台账（`items.jsonl`，status open，供 code-fix 车道消化），join 放行 testing → verified，不打回

#### Scenario: advisory 档永不打回
- **WHEN** `verify.impl_code_review_mode: advisory`，join 读到含非 rejected findings 的 completed 产物
- **THEN** findings 写入台账后 join 直接放行；spec 不进入 bug_found

### Requirement: mode 配置键与 Dashboard 界面

`ConfigLoader` MUST 提供单点读取器 `get_impl_code_review_mode`（缺省 `gate`，仅接受白名单值）；`impl_code_review_concurrency` 缺省值 MUST 从 2 调整为 4（显式配置不受影响）。新增配置键 MUST 在设置页「验证」面板提供受管读写回显（gate/advisory 选择），经既有受管键通道持久化。

#### Scenario: 设置页读写 mode 键
- **WHEN** 用户在设置页「验证」面板把模式从 gate 切为 advisory 并保存
- **THEN** `verify.impl_code_review_mode` 经受管键通道写回 `.fenix/config.yaml`，重读回显 advisory；非法值（如拼写错误）被读取器拒绝并回退缺省 gate
