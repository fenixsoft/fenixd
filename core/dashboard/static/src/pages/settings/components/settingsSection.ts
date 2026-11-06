import type { ConfigData } from '@/services/dashboard';

/**
 * 堆叠双面板页签下各配置卡片暴露给父页签的收集句柄。
 *
 * 页签底部只有唯一一个「保存」按钮，由设置页统一触发各卡片各自校验并
 * 收集本节配置，合并后一次提交（避免多次写入与多条成功提示）。
 * 现有两族消费方：自进化页签（StaleCodeSelfhealPanel + SuggestedImprovementsPanel）、
 * 仲裁页签（ArbiterPanel + ChainPanel），先例为自进化（原
 * SelfEvolutionSectionHandle，2026-11-05 仲裁页签收口单保存时改本通用名）。
 *
 * collect() 语义：表单校验失败返回 null（antd 已在表单内渲染错误提示），
 * 项目级作用域的只读卡片返回空对象（不提交全局键），成功返回本节补丁。
 */
export interface SettingsSectionHandle {
  collect: () => Promise<Partial<ConfigData> | null>;
}
