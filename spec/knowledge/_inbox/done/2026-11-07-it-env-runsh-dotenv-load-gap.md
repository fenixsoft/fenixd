# 集成测试环境（add-integration-test-env）裁决遗留事实

- run.sh 未实现 `.env` 自动加载：tasks 1.2 与 design L43 声称「真实模式启动前 set -a; source tests/integration/.env; set +a（进程变量优先）」，但 as-built run.sh 全文无 `.env` 字面量（两树 grep 计数 0），凭据自检（run.sh L102-104）仅读环境变量。预置 .env（provider bigmodel.cn / glm-5.3-flash，gitignored）当前是死文件，真实双轮须手工 export 三要素。
- 连带陷阱：若日后补齐 .env 加载，场景 `it-real-mode-missing-credentials-fail-loud` 在本机（.env 在场）会翻车——`env -u` 卸掉进程变量后文件值回填 → 凭据齐 → 不再 exit 2。补功能时须给该场景加豁免开关（如 FENIX_IT_ENV_FILE=none 语义）或改在无 .env 环境验证。
- purity 场景键值字面量 grep 必须 `--exclude=.env`：设计内 gitignored 凭据文件在配置好凭据的机器上必然命中，否则确定性误报（2026-11-07 裁决实录，已在场景文件修复）。
- FENIX_IT_GIT_REPO 目录形态（run.sh 取 git-common-dir 只读挂载 → 容器内本地克隆）是消除克隆网络抖动的自建夹具通道；但「每次运行从 GitHub 拉取」是本 SPEC 回归底线（proposal L7/L12），smoke 主链场景不可钉本地源，仅 orchestration 类场景（如 it-dual-round，已修复钉 $PWD）适用。
- 判别锚点：GitHub 大克隆失败指纹 = GnuTLS recv error (-110) / RPC failed curl 92 HTTP/2 stream CANCEL / early EOF / fetch-pack invalid index-pack output，属传输中断型网络故障；同源克隆数分钟后成功即可判 env 而非产品缺陷。
