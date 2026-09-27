# testing 出口 ocr join 门

<!-- knowledge: capability=impl-ocr-join-gate rev=1
     sources=spec/archive/2026-09-26-add-impl-ocr-parallel-lane -->

`testing → verified` 门禁自动路径上的 ocr 车道完成判据：两车道双绿才放行；gate 档 findings 经既有 bug_found 通道打回且有轮次上限，advisory 档永不打回。

## 规则

- join 判据：ocr 产物存在、`status` 在白名单（`completed` / `unavailable`）、指纹新鲜。tester 产物通过且 ocr 双绿（`completed` + 指纹新鲜 + 无非 rejected findings，或 mode=advisory）时 join 放行，`testing → verified` 正常发生。
- tester 先完成而 ocr 未完成：spec 停留 `testing`（tester_run 单飞语义保持，不重派 tester），由 ocr 车道完成事件唤醒 join 评估；ocr 车道不单独阻塞在无唤醒的停等态。
- 产物缺失或车道未运行（如 daemon 重启恢复后 tester 经重派路径再派、无 merge-back 事件）：join 判据幂等触发车道（在跑单飞去重），不无限停等而车道从未启动。
- 车道超时、非零退出、环境不可用降级为 `unavailable` 时，join 视为放行（记 WARNING 审计），spec 正常推进。
- mode 配置 `verify.impl_code_review_mode`：缺省 `gate`；`ConfigLoader.get_impl_code_review_mode` 单点读取器，仅接受白名单值，非法值（含拼写错误）被拒绝并回退缺省；设置页「验证」面板提供受管读写回显（gate/advisory 选择），经既有受管键通道持久化。
- gate 档（缺省）：join 读到 `completed` 且存在非 rejected findings 时，首次经 `testing → bug_found`（reason 注明 ocr findings）→ `implementing` 重派实现者修复；修复轮提示词注入 findings 清单与 disposition 处置契约（`fixed`/`rejected`/`deferred` + 非空 reason），修码后重验（定向测试 + 全量回归）、merge-back 后 ocr 车道对增量重审。
- ocr 修复轮上限 1 次（计数器持久化于 spec entry）：达上限后仍出现的 findings 一律转台账（`items.jsonl`，status=open——台账词表仅 open/resolved/ignored、无 deferred 状态；spec_name 归属本 spec，finding 附处置 reason，供 code-fix 车道消化）且 join 放行，不再打回。
- advisory 档：join 读到含非 rejected findings 的 `completed` 产物时，findings 写入台账后直接放行，spec 不进入 bug_found。
- `impl_code_review_concurrency` 缺省值为 `4`（显式配置不受影响）。

## 溯源

- 2026-09-26 add-impl-ocr-parallel-lane — 新建 join 门：testing 出口完成判据与 tester 停等唤醒、产物缺失时幂等触发车道、gate 档 bug_found 打回（修复轮上限 1 次、溢出 findings 转台账放行）与 advisory 档入台账、mode 读取器与设置页键、并发缺省 2→4。
