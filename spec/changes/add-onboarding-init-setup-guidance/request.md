在 /root/fenixd 项目立项新手首次使用易用性改进，共 3 个 SPEC：①对称回落纪律+派发自检归因+systemd PATH 卫生 ②provider 引用校验+告警治理 ③init/setup/模板引导

（本 SPEC 为③。补充上下文：fenix-init 自己写入的 .fenix/verify.yaml（gitignore ! 放行未入库）、
.claude/agents/*.md、scripts 运行时产物直接触发新项目首批白名单/散件告警；config.template.yaml
「未配置时所有 Agent 使用默认环境变量模型」注释只对 claude harness 成立，对 dsh+fenix 是误导。）
