import type { ConfigData } from '@/services/dashboard';

/**
 * 自进化页签下各配置卡片暴露给父页签的收集句柄。
 *
 * 页签底部只有唯一一个「保存」按钮，由设置页统一触发两张卡片各自校验并
 * 收集本节配置，合并后一次提交（避免多次写入与多条成功提示）。
 *
 * collect() 语义：表单校验失败返回 null（antd 已在表单内渲染错误提示），
 * 项目级作用域的只读卡片返回空对象（不提交全局键），成功返回本节补丁。
 */
export interface SelfEvolutionSectionHandle {
  collect: () => Promise<Partial<ConfigData> | null>;
}
