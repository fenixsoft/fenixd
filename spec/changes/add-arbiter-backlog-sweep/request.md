add-arbiter-backlog-sweep —— 跟进 SPEC：Arbiter 存量回扫（启用/启动时扫描 frozen=true 且有成对机器升级告警的存量 spec 入队），fast-track，depends_on add-arbiter-lane，依赖满足后立即执行

（用户对话原话：「spec落地之后，会自动处理evo-refine-midflight-outlier-dims吗？」——答以触发面为事件驱动、存量冻结吃不到，补此回扫 SPEC；用户裁定「走1，立项」即留给 Arbiter 首战，evo-refine-midflight-outlier-dims 作为回扫后首个真实处置对象）
