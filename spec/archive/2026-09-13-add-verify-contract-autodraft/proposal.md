# 提案：验证契约自主起草（verify-contract-autodraft）

## Why

`.fenix/verify.yaml` 是项目级验证基建声明，但框架没有任何自主生成路径：人类不写就没人写。2026-09-07 fenix-desktop 项目 notes-standalone-sync spec 被此卡死——验证撞上「场景集含 web 场景但无 serve 配置」后错误被路由为「退回 plan 修复」，而 plan 的职责是生成场景、永远修不了基建缺口，于是烧两轮打回 + blocker（卡 testing 106 分钟）+ 60 分钟升级冷却，最终由 Administrator 应急手写契约才收口。

历史上 43 个 spec「顺利验证」是侥幸（主树恰有活着的 dev server，走了已可达即跳过捷径），不是能力。Agent 反复执行过项目构建，完全知道如何构建产品，缺的只是把这份知识沉淀为机器可写的声明并制度化生成路径。

## What Changes

- **路由修正**：`_ensure_app_reachable` 中「契约缺失 / commands.start 占位符 / 契约解析失败」不再返回打回 plan 的 note，改为产生结构化信号 `verify_contract_missing` 直派 Administrator——确定性死局不等 4 次失败计数与升级冷却（同 spec 信号仍走冷却防重复唤起）。
- **admin 起草 + 自证门**：Administrator 收到信号后为项目起草 `.fenix/verify.yaml`，落盘前必须实证 prepare → serve → ready 三段全通（含就绪探针鉴别力自检）；通过后 git 提交契约、把 spec 复位 ready 触发重验证；2 轮内修不通则 `escalate=true` 并附当前草稿与失败证据（人类只做判断不做体力活）。
- **校验入口**：`core/verify_contract.py` 新增契约校验函数 + `bin/` 小 CLI，Administrator 调用显式入口而非手拼命令。
- **权限边界**：契约缺失即生成；解析失败或明显失效（如 prepare 指向已不存在的 script）可修正并在处置记录留痕；有效契约一律不碰；人类手写始终权威。
- **不变**：prepare 失败（构建被实现破坏）仍打回 plan（那是产品缺陷）；纯 cli 场景集路径不受影响；不加配置开关、不做巡检预生成。

## Capabilities

### New Capabilities
- `verify-contract-autodraft`: 验证契约自主起草——验证撞上契约缺失/损坏时框架自主恢复（admin 起草 + 三段自证 + 提交 + 复位重验证），不再依赖人类生成契约文件。

### Modified Capabilities

（无——`spec/specs/` 无既有能力 spec 声明验证契约的需求面；归档中亦无同名能力。）

## Impact

- `core/pm_engine/verification.py`：无 serve 配置分支的路由信号化（回归风险最高处）
- `core/admin_monitor.py` 或信号写入链路：新信号类型 `verify_contract_missing`
- `agents/administrator.md`：权限清单新增契约生成/修正授权 + 起草手册（模板即 `verify_contract.py` docstring）
- `core/verify_contract.py`：新增 validate 函数（复用 run_prepare_steps / probe_ready）
- `bin/`：新增校验 CLI（Administrator 自证入口）
- 测试：路由三分支单测、自证通过/失败路径、权限边界（有效契约不被覆盖）、解析失败修正路径
- 存量顺手项：fenix-desktop 项目 admin 手写的 verify.yaml 至今未提交，落地后补提交作为首个实战样本
