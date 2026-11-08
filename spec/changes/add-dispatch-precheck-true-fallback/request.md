在 /root/fenixd 项目立项新手首次使用易用性改进，共 3 个 SPEC：①对称回落纪律+派发自检归因+systemd PATH 卫生 ②provider 引用校验+告警治理 ③init/setup/模板引导

（本 SPEC 为①。补充上下文：用户裁定 dsh+fenix 走「真对称回落」——bundle 侧 assertModelExplicit 放宽，
无 patch 时回落 dsh 全局默认档；cloud-phone 新项目首跑暴露 claude CLI 因 systemd EnvironmentFile
PATH 缺 /root/.local/bin 而全部派发失败的自吞噬循环。）
