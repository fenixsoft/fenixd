// 迁移自 claudecodeui src/components/chat/utils/messageKeys.ts。
// getIntrinsicMessageKey 的定义本体收敛到 runEvents.ts（与消息稳定引用复用层
// 同处）：node:test 直载 .ts 单测按 ESM 解析 runEvents.ts，无扩展名运行时相对
// 导入无法解析（ERR_MODULE_NOT_FOUND），故 runEvents.ts 不得反向 import 本模块。
// 本文件保留再导出，ClaudeMessageList 等消费方导入路径不变。
export { getIntrinsicMessageKey } from './runEvents';
