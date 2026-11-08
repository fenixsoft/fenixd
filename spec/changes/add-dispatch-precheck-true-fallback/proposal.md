## Why

新项目 cloud-phone（2026-11-08）首跑暴露派发链路三处断点，导致首个 SPEC 从 07:52 到 08:49 近一小时全部派发失败并产生 28 条告警：

1. **dsh+fenix 真对称回落只落了 fenixd 侧**：`harness-default-fallback` 能力（2026-11-03）声明「无分配时 dsh 省略 `--patch`、按 profile 自身配置的默认模型启动」，但 dsh-bundle 的 `modelConfig.ts` 在插件创建期无条件断言 `config.model` 显式存在（`assertModelExplicit`，「绝不回退 dsh 默认档」旧纪律残留），无 patch 即 StartupError——required 插件 `headless-runner` 无法激活，回落语义在 dsh 形态实际不可达（秒挂 3 次实证）。
2. **harness CLI 不可达无归因无指引**：systemd 托管 daemon 的 EnvironmentFile PATH 缺 `/root/.local/bin`（claude 安装位置），所有派发报 `[Errno 2] No such file or directory: 'claude'`，不指向任何可行动作。
3. **systemd env 捕获 PATH 自吞噬**：新项目出生即 systemd 托管，env 候选稿唯一可捕获的在跑进程就是 systemd 拉起的最小 PATH supervisor——坏 PATH 被原样落盘并被 unit 每次重启加载，循环封闭（fenixd/fenix-desktop 因 shell 时代迁移幸免）。

用户已裁定（2026-11-08）：dsh+fenix 走**真对称回落**——无分配回落 dsh 全局默认档，兑现 11-03 对称回落裁定的完整语义。

## What Changes

- **dsh-bundle 侧兑现真对称回落**：`modelConfig.ts` 的 `assertModelExplicit` 改为按形态划界——`config.model` 整体缺席（无 patch 回落形态）不再抛错，由 dsh 自身默认模型解析（dsh-base 通道）供数并 WARN 留痕；`config.model` 在场但要素缺失（部分链笔误）保持 fail-fast。显式链 spawn 产物字节级不变（回归红线）。
- **派发前置自检与失败归因**：daemon 启动时与车道派发前探测 harness binary 可达性（`shutil.which`）；不可达的 run 失败归因带显式标记（与既有 `[model-chain-unavailable]` 同层），附 actionable 修复指引（检查 systemd.env PATH / harness 安装）；PATH 缺陷可自愈（自动补目录进 `.fenix/systemd.env` + 落 `restart_request`）。
- **systemd env 捕获 PATH 卫生**：`capture_env_candidate` 对捕获源 PATH 做基线目录集检查（`~/.local/bin`、`/usr/local/bin` 等），缺失目录追加至候选稿 PATH 尾部并留痕注释；unit 渲染内置保底 `Environment=PATH=`（env 文件缺席时兜底）。

## Capabilities

### New Capabilities

- `dispatch-precheck`：派发前置自检（harness binary 可达性）与失败归因标记、自愈闭环
- `systemd-env-path-hygiene`：systemd EnvironmentFile 捕获 PATH 卫生检查、基线并集与 unit 保底 PATH

### Modified Capabilities

- `harness-default-fallback`：bundle 侧兑现「按 harness 自身配置启动」的对称回落语义（现 spec/changes/add-harness-default-key-fallback 声明的 dsh 形态回落实际不可达，本变更补齐 dsh-bundle 侧实现并保持笔误防护划界不变）

## Impact

- **代码**：`dsh-bundle/src/modelConfig.ts`（dist 为 gitignored 构建产物，随构建再生）、`core/agent_runner/harness/dsh_adapter.py`、`core/agent_runner/runner.py`、`core/systemd_hosting.py`、`bin/migrate_to_systemd.py`
- **回归红线**：显式链（provider 三要素齐全）spawn 产物字节级不变——argv 含 `--patch`、patch 渲染三要素、env 桥接 `FENIX_DSH_PROVIDER_API_KEY`
- **部署**：bundle dist 重建后经既有 profile symlink（`/root/.dsh/profiles/fenix/node_modules/fenix-dsh-bundle`）生效，需 daemon 重启
- **既有项目修复**：cloud-phone 等已固化坏 PATH 的项目由自愈链路修复（运行时动作，不在本 SPEC 交付物内，落地后登记 `.fenix/todo.md`）
