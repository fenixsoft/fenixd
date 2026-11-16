① daemon 环境缺 $HOME,凭证只能靠内嵌 URL 这一条腿,token 一吊销推送就全瘫;② done 状态的推送退避在 daemon 重启后不重新武装,会永久滞留。这两点给 fenixd 提个改进SPEC，你到fenixd中立项，full，立即执行。
