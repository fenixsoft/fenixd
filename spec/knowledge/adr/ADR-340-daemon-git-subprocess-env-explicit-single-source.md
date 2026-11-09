# ADR-340：daemon 侧 git 子进程环境显式构造单源，禁裸继承

date: 2026-11-09
status: accepted

## Context

systemd 承载的 daemon 进程环境不可信：PATH 缺失已有既定基线范式（systemd-env-path-hygiene），HOME 缺失在 2026-11-09 cloud-phone 推送事故中实证（`/proc/<pid>/environ` 缺键，git 子进程报 `fatal: $HOME not set`）。daemon 内 done→pushed 自动推送的 git 子进程裸继承 daemon 进程环境，HOME 缺失时 `~/.git-credentials`/`~/.gitconfig` 均不可达，凭证只剩 remote URL 内嵌 token 单腿；token 吊销（`Authentication failed`）后全部项目推送瘫痪。若启动自检、env 捕获、unit 渲染等站点各自实现 HOME 判定，会形成多源漂移。

## Decision

daemon 侧 git 子进程环境以单源解析器（`core/git_env.py`）显式构造：HOME 三级解析序（daemon env 非空 `HOME` → `pwd` passwd 目录 → 配置 `pm.push.credential_home` 覆盖），一个判定产出三面共享——解析后 HOME、git 子进程 env、credential helper 参数；git push MUST 以显式 `env=` 运行，MUST NOT 裸继承 daemon 进程环境。凭证为双腿并存兼容——remote URL 内嵌 token + credential helper 文件（`-c credential.helper=store --file=<abs>`，单一 argv 元素）；三级皆空时 fail-open 不注入 HOME、不抛异常，由启动自检告警兜底。后续所有触碰 daemon 侧 git 子进程环境的新站点 MUST 复用该单源，不得自建平行解析。

## Consequences

推送不再依赖 daemon 进程恰好带 HOME，双腿任一可用即可推送；运行时（显式 env 注入）、承载层（env 候选稿补齐留痕、unit 模板 `Environment=HOME` 保底行、迁移摘要卫生结论）与启动自检三个消费面共用同一解析判定，零漂移。代价：HOME 注入使 git 对 `~/.gitconfig` 恢复可见（alias/credential 配置生效属预期行为，风险登记）；三级皆空的极端容器环境回退现状单腿凭证，依赖自检告警人工补齐。与 ADR-141（agent run 级隔离 HOME）分层不冲突：彼为 agent 子进程凭据隔离，此为 daemon 自身 git 子进程环境确定性。
