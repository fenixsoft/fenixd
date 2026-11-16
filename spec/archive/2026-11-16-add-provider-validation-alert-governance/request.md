在 /root/fenixd 项目立项新手首次使用易用性改进，共 3 个 SPEC：①对称回落纪律+派发自检归因+systemd PATH 卫生 ②provider 引用校验+告警治理 ③init/setup/模板引导

（本 SPEC 为②。补充上下文：新项目把全局 config 的 models 块复制进项目后，provider 名
bigmodel.cn 与项目注册的 bigmodel-cn 一字之差，48 条「已跳过，不阻塞加载」静默失效；
首个 SPEC 实现期 verify_contract_missing 以 major 每 5 分钟召唤 Administrator 形成噪音；
配置修复后 28 条旧告警永久滞留面板。）
