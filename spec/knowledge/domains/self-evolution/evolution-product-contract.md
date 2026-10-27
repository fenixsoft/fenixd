# 自进化产物契约校验与部分接受

<!-- knowledge: capability=evolution-product-contract rev=2 sources=spec/archive/2026-09-18-add-framework-self-evolution,spec/archive/2026-10-05-evo-add-evolution-product-salvage,spec/archive/2026-10-27-evo-add-evolution-contract-partial-accept -->

自进化分析 run 产物（`.fenix/evolution/out-<run_id>.json`）的契约校验与落库收尾规则：校验拒绝的粒度到单条，合法条目照常入库，失败现场留档供归因。

## 规则

- 校验错误分文件级与单条目级。文件级错误——产物文件缺失（「产物文件未写出」）、非 UTF-8 编码（含坏字节）、JSON 不可解析、顶层非对象、缺 `items` 数组——在任何口径下都整份抛 `ContractError` 拒绝，不属宽口径豁免面。
- 单条目契约错误（缺必填字段 `project`/`date_section`/`title`、`section` 越三值枚举（浪费/失误/可改进）、缺 `verdict` 对象、`verdict.worth_spec` 非布尔、`id` 为非字符串真值）在默认严格口径（`read_contract` 不传 `lenient`）下仍整份拒绝，既有调用方行为不变；evolution 落库链路以宽口径（`lenient=True`）调用：收集该条错误并跳过、合法条目照常通过——单条非法只牺牲该条。通过校验的字符串 `id` 另过 12 位小写 hex 形态白名单，不满足不硬拒，摘除该 `id` 由落库侧回落复算。
- 全部条目非法仍整份拒绝（fail-closed）：宽口径下 `items` 非空而合法条目为零时抛 `ContractError`（文案含总条数并附首条错误），防模型大面积跑偏的坏数据入库。
- 返回形态：`{"run_id", "degraded", "items", "errors"}`——`items` 为通过校验的条目，`errors` 为逐条错误记录 `[{"index", "message"}]`（严格口径恒为空列表），供落库侧归因。
- 落库部分接受语义：「有逐条契约错误」与「条目不足」同判 partial（与待分析条目数是否已知无关）——合法条目写入 items 存储（id 幂等去重，单条落地失败跳过不阻塞其余）、run 记失败（success=False）、水位不推进，未分析条目由下一检查点幂等补齐；错误文案含「部分接受」、逐条原因与留档路径。
- 失败现场留档：仅「有合法条目的部分接受」路径在收尾清理前把产物文件改名 `<原路径>.failed` 同目录保留（run_id 每轮递增不碰撞），留档文件含全部条目原文；改名失败（OSError）静默跳过——留档尽力而为，非正确性依赖。留档无自动清理与保留期，随部分接受次数累积，清理归外部运维。全非法拒绝与文件级失败路径不扩大留档面，产物文件照常清理删除（清理范围含 `.parts` 残片目录）。
- 与抢救的关系：产物文件缺失或 JSON 不可解析时先走 `.parts` 分片合并抢救（见[自进化车道](self-evolution.md)），抢救恢复出的产物再经同一宽口径校验与部分接受语义落库。

## 关键行为

落库收尾管线顺序：CLI 退出 → 先抢救 → 宽口径校验 → 合法条目逐条 ingest → todo.md 标记批末按项目合并提交 → partial 判定 → 部分接受路径改名留档 → 清理产物与 `.parts` 残片。

## 溯源

- 2026-09-18 2026-09-18-add-framework-self-evolution（spec/archive/2026-09-18-add-framework-self-evolution） — 建立产物契约与整轮拒绝语义（任一契约不满足判整轮失败）
- 2026-10-05 2026-10-05-evo-add-evolution-product-salvage（spec/archive/2026-10-05-evo-add-evolution-product-salvage） — 新增文件级失败归因分级与 `.parts` 分片抢救；部分恢复（条目不足）按失败落地且不推进水位
- 2026-10-27 2026-10-27-evo-add-evolution-contract-partial-accept（spec/archive/2026-10-27-evo-add-evolution-contract-partial-accept） — 修改校验拒绝粒度：单条目契约错误收集跳过、合法条目照常落库（部分接受）；全部非法仍 fail-closed；新增失败现场 `.failed` 留档
