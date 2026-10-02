# verify run 前 dist 新鲜度探针

<!-- knowledge: capability=serving-dist-freshness-probe rev=2
     sources=spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake -->

serving 层在验证开跑前对被测 dashboard 实例构建产物的新鲜度探针与自动重建：dist 滞后先重建再开跑，在源头消灭 dist 时序类 env 失败。

## 规则

- 探针时点与口径：验证链在开跑场景前执行一次（不在场景间反复），比对 dashboard static src 树最新内容时间与本轮 served dist 入口产物（`dist/index.html`）构建时间——src 晚于 dist 即判滞后。比对取 mtime 级时序，不做内容哈希（全树哈希开销大且 vite 产物 hash 文件名会误报）。
- 滞后处置：判滞后 MUST NOT 直接开跑场景——先执行自动重建再开跑。重建调用与 merge-back dist 重建同源的模块级构建入口（`run_dist_build(project_root, static_root, logger)`），构建命令契约从项目 `.fenix/verify.yaml` prepare 段读取，不在 serving 层硬编码构建命令；merge-back 既有重建路径委托同一构建入口。
- 新鲜直通：dist 构建时间晚于 src 最新内容时间时探针直通，零构建耗时与副作用。
- 适用形态：dashboard static 产物存在且被测实例 serve 主树 dist 的形态；worktree serve 形态（prepare 已在本 worktree 构建）天然新鲜直通。
- 重建失败不静默继续：探针判滞后但重建失败时 MUST 显式暴露（run 错误现场 + 日志 error，含构建失败尾部日志），MUST NOT 以陈旧 dist 静默开跑全批场景——继续开跑的决定与环境性失联升级路径联动，使该轮失败可被后续豁免握手与 admin 升级链消费，而非落地为无法归因的 env warning。

## 溯源

- 2026-10-03 2026-10-03-fix-verdict-env-exemption-admin-handshake（spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake） — 新建本页：serving 层 run 前 dist 新鲜度探针（mtime 时序口径、滞后先重建再开跑、新鲜直通、重建失败不静默）；dist 构建执行体提取为模块级 `run_dist_build`，merge-back 单点重建扩散为多触发点。
