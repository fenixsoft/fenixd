# Design: add-main-tree-deps-provision

## Context

`provision_worktree_node_modules(worktree_root, project_root, sub_dirs, mode, logger)`（core/verify_contract.py:703）已实现按 deps_mode 双模式把依赖装进**指定目录**：hardlink=主树 node_modules 硬链接副本（主树无 node_modules 时自动降级 prefer-offline）；prefer-offline=`npm ci --prefer-offline` 失败回退 `npm install --prefer-offline`，900s 超时，失败记 warning 继续不抛。单目录供给前提：目标目录有 package.json 且缺 node_modules。

但它当前跳过逻辑是「目标目录（wt_dir）缺 node_modules 才装」，且 hardlink 源固定取 `project_root/sub/node_modules`——主树路径复用时 `worktree_root == project_root`，hardlink 源与目标重合（self-copy），须新增路径处理。

## Goals / Non-Goals

- Goals：三处主树裸跑点（verification.py L699/L745、worktree_manager.py `_run_dist_build` L2420）在 prepare 执行前完成依赖预检与预装；已安装时零开销；缺件预装失败不阻塞主流程（best-effort，与 worktree 供给同哲学——prepare 失败仍会照常报不可达）。
- Non-Goals：不改 deps_mode/static_scope 配置语义；不做 Dashboard UI（无新配置键，既有 `verify.deps_mode` 设置页已在）；不给实现 worktree 供给加新功能；不处理非 npm 生态（python/pip 等后续另案）。

## Decisions

### D1：新增独立入口 `ensure_main_tree_deps(project_root, sub_dirs, mode, logger)`，不改造既有函数

在 `core/verify_contract.py` 新增顶层函数，内部复用 `resolve_deps_mode` 与 npm 安装命令序列。理由：`provision_worktree_node_modules` 的 hardlink 分支语义（源=主树→目标=worktree）与主树自装（源=无，目标=主树）不同，塞同一函数要加分支参数，易破坏既有调用方与 5 个既有测试；独立入口让「worktree 供给」与「主树自装」各自可测。

行为规格：

- 对每个 sub：`(project_root/sub)/package.json` 不存在 → 跳过；`node_modules` 已存在 → 跳过（零开销幂等）。
- mode 解析：调用方传 `resolve_deps_mode(contract, ...)` 结果（与 worktree 路径同源）；主树自装时 hardlink 无意义（源就是自己），**一律走 prefer-offline 安装**（`npm ci --prefer-offline --no-audit --no-fund` → 失败回退 `npm install --prefer-offline --no-audit --no-fund`，900s 超时）。
- 成功/失败均记日志：成功 INFO（含目录与包规模不强制）、失败 WARNING（含 stderr 尾部）——主树供给此前完全不可见，失败要能被 admin 从日志定位。
- 返回已装目录列表（相对 project_root），供调用方记日志；不抛异常。

### D2：三处调用点统一「prepare 前预装」，sub_dirs 取 prepare 步骤 cwd 集合

`sub_dirs = sorted({(s.cwd or ".") for s in contract.prepare})`——与 worktree_manager.py:278 同式复用。三处调用点均为：

```
if contract.prepare:
    ensure_main_tree_deps(project_root, sub_dirs, logger=...)
    err = run_prepare_steps(contract, <主树根>)
```

1. verification.py 纯 cli 分支（L699 附近）：`contract.prepare` 存在即预装（原逻辑保留：纯 cli 无实例形态，prepare 仍执行）。
2. verification.py 主树作用域分支（L745 附近，`not wt_scope` 时）：预装后再 `run_prepare_steps`。
3. worktree_manager.py `_run_dist_build`（L2420）：预装后再执行（merge 后重建 dist 同样会被缺依赖卡住）。

worktree 路径（`_ensure_serving_worktree` L438）不动——已有 `provision_worktree_node_modules`。

### D3：供给失败不短路，交 prepare 自身报错

预装失败（npm 网络故障等）只记 WARNING，继续执行 prepare——若 prepare 因此失败，现有「prepare 失败＝验证环境错误→门禁拦截→admin 升级」链路照常接管，不新增第二套失败通道。这与 worktree 供给「best-effort 不阻塞派发」同哲学。

### D4：主树自装不加锁，容忍并发重复安装

主树 prepare 可能与实现 worktree 供给并发（多 spec 并行）。npm ci 到同目录并发可能冲突——Windows 下会，Linux 下通常各自原子 rename，实测可接受（fenixd 仅 Linux 部署）。不为小概率场景引入文件锁复杂度。

## Risks / Trade-offs

- 首次预装耗时（冷缓存 npm ci 可能分钟级）：可接受——比「整轮验证废掉 + admin 处置」便宜两个数量级；PREPARE_STEP_TIMEOUT=600 不约束供给（供给自带 900s）。
- `[[directory]]` 场景：monorepo workspace（如 fenix-server `npm --workspace web run build`）下 `web/node_modules` 缺失但根 `node_modules` 存在——npm workspaces 依赖提升，`web/node_modules` 可能永不存在且不需要。cwd=web 的步骤会触发误装。缓解：npm workspaces 形态下根安装已覆盖 workspace 依赖，对 cwd=web 预装 `npm ci` 也能跑（幂等、走缓存），开销可接受；不做 workspaces 检测（复杂度不值）。
- 主树 node_modules 由框架写入：与「human 主树不污染」无冲突——node_modules 本就 gitignore 排除。

## Migration Plan

纯增量：新函数 + 三处调用点各插一行预装 + 测试。无配置迁移、无存量数据。零迁移成本。

## Open Questions

无——修复方向 09-11 定案（用户拍板走 fast-track），复用既有 supply 机制非新造。
