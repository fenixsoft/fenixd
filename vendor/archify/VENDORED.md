# Vendored: archify

本目录是 [tt-a1i/archify](https://github.com/tt-a1i/archify) skill 包的 **vendored 快照**，
作为本仓库的二进制依赖随库分发——运行时（项目架构图生成，`core/dashboard/routes/
architecture_routes.py`）直接读取本目录，**不执行任何联网安装**（原 `npx skills add
tt-a1i/archify -g` 链路已移除），也不依赖用户环境安装的 skill。

## 溯源

| 项 | 值 |
|---|---|
| 上游仓库 | https://github.com/tt-a1i/archify |
| 快照 commit | `9e35d2b0b39b155553ba9fcfe0b4f2a5198dd993` |
| 上游版本 | 2.17.0-dev.1（SKILL.md metadata.version "2.17"） |
| 许可 | MIT（见本目录 `LICENSE`、`THIRD_PARTY_NOTICES.md`，随包保留） |
| 落库日期 | 2026-09-25 |

## 与上游的差异

- **剔除 `test/`**（约 2.1MB 上游自测套件）：SKILL.md 明示生成流程不读 tests/benchmarks，
  纯开发产物，不入库。其余文件（SKILL.md、schemas/、examples/、references/、renderers/、
  bin/、scripts/、assets/ 等）原样保留——SKILL.md 指引在生成期会按需读取这些伴生文件
  （如 `node bin/archify.mjs validate` 本地校验），不可裁剪。

## 升级方法

从上游对应 commit 重新复制 `archify/` 目录整体替换本目录（再次剔除 `test/`），
更新本文件的溯源表。禁止只替换 SKILL.md——指引与伴生文件（schemas/examples 等）
存在版本耦合。
