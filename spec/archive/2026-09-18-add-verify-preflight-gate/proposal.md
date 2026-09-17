# Proposal: add-verify-preflight-gate

## Why

验证契约与环境错误「跑完全场才暴露」家族已四次实锤烧钱：

1. **2026-09-10 fenix-server add-web-ui**：契约 `serve.cmd: node dist/server.js` 指向不存在入口（真实 `dist/server/index.js`），prepare 缺 web build——32 场景全 ERR_CONNECTION_REFUSED，admin 处置 $13.67/68min 修复（4497ffc）。
2. **同项目 add-ssh-foundation 11:16**：主树 prepare 裸跑 `tsc: not found` exit 127（另案 add-main-tree-deps-provision 立项治理供给面，本 SPEC 治理预检面）。
3. **契约自证工具在、门槛没接上**：`validate_contract`/`fenix_verify_contract.py`（prepare→serve→ready 三段自证）已存在且 admin 处置实证有效，但验证管线全库**零调用点**（grep 实证）——契约起草期（add-verify-contract-autodraft）有自证门，消费期没有。
4. **已侦测偏差无通道蒸发**：add-ssh-foundation planner 09:5x 转录已精确写出「serve command references `dist/server.js` but the build outputs `dist/server/index.js`」，但无权修契约、无上报机制，错误潜伏 3 小时后烧掉整轮。

共同根因：验证管线把「契约/入口/依赖」类确定性环境错误推迟到场景执行甚至整轮结束才暴露；错误证据（Popen `stdout=DEVNULL` 吞掉 `Cannot find module`）与侦测情报（planner 已发现）双双湮灭。

## What Changes

- **入口存在性静态预检（fail-fast，spawn 前）**：serve.kind=command 的 cmd 启动前，机械解析命令中的脚本入口路径（`node <path>` 等形态），路径不存在时**不 spawn、不跑场景**，直接产生结构化失败（含正确路径建议——同目录 `index.js` 等确定性候选），走既有 `verify_contract_missing` 信号通道呼叫 admin；错误 1 次探活内暴露而非 32 场景空转。
- **契约消费期自证（首验轮轻量门）**：契约 mtime 变化后的首个验证轮，执行 `validate_contract` 的轻量版（serve 段合法性 + ready 探针鉴别力自检，不重复 prepare 构建）；自证失败按契约错误处理，不进入场景执行。
- **planner 契约偏差 findings 通道**：planner-plan 出题期对契约做只读一致性检查（serve 入口 vs package.json start/构建产物、场景端口 vs 契约端口），偏差结构化落盘复用 `scenario_static_findings.json` 情报注入机制直达 admin prompt——「侦测到但不拦截」升级为「侦测到必送达」。
- **兜底 spawn 错误捕获**：`_ensure_app_reachable` 兜底 spawn 的 `stdout=DEVNULL` 改为捕获落盘（`verify-serving/` 下 per-spec 文件），探活失败时错误文本附入 blocked 告警——admin 不再靠猜。
- **主树 prepare 预检前移**：`add-main-tree-deps-provision`（已立项 ready）覆盖主树依赖供给；本 SPEC 在其入口同一位置加「prepare 可执行性预检」（build 工具存在性），两案在验收时对齐边界、不重复实现。

## Capabilities

### New Capabilities

- `verify-preflight-gate`: 验证前置自检门——spawn 前入口存在性预检 + 契约消费期轻量自证 + 兜底 spawn 错误捕获落盘，契约/入口类确定性错误在场景执行前 fail-fast。
- `planner-contract-findings`: planner 出题期契约偏差情报通道——只读检查偏差落盘并注入 admin/judge prompt，侦测必送达。

### Modified Capabilities

（无——`spec/specs/` 无既有能力声明验证前置自检需求面；归档中 `verify-environment-sanity-gate` 治理「场景结算后探针」，本能力治理「场景执行前预检」，互补不重叠。）

## Impact

- 代码：`core/verify_contract.py`（入口路径解析/轻量自证纯增函数）、`core/pm_engine/verification.py`（两处 spawn 点接入预检 + DEVNULL 改捕获落盘）、`core/admin_store.py` 或 `verify_engine/`（findings 落盘扩展字段）、`core/agent_runner/prompt_builder.py`（admin prompt 注入契约 findings 段）
- 测试：`tests/test_verify_preflight_gate.py`（新增）、`tests/test_pm_verification.py`（回归）
- 与 `add-main-tree-deps-provision`（ready）：同在 `_ensure_app_reachable` 主树 prepare 点接入，本 SPEC 预检在其供给动作之后执行，验收时联合对齐；无需求面冲突。
- 与 `add-verify-contract-autodraft`（pushed）：起草期三段自证语义不变；本能力是消费期对同一工具的轻量复用。
- 行为影响：契约正确时每轮仅多毫秒级文件存在性检查；契约错误时从「32 场景空转 + 整轮废弃」降为「1 次预检 fail-fast + 确定性错误指引」。
