import { history, useModel } from '@umijs/max';
import { useEffect } from 'react';
import { PagePlaceholder } from '@/components/PagePlaceholder';

/**
 * code-review item ea6c09e99dcb：/projects 是菜单「项目」父项的落点（menuItemRender
 * 统一包 Link 可点），而项目真实页面挂在 /projects/:name——裸路径不再停留在
 * 「建设中」占位页，改为重定向到 initialState.projects 首项；列表为空或尚未
 * 就绪时保持占位页兜底（后续 setInitialState 校准出项目后会自动接上重定向）。
 */
export default function ProjectsPage() {
  const { initialState } = useModel('@@initialState');
  const projects = initialState?.projects;

  useEffect(() => {
    const first = projects?.[0];
    // replace 语义：重定向不在历史栈留占位路径，返回键不回弹到本页
    // 非字符串守卫（code-review item 294951ea0d4f）：上游数据异常混入非字符串
    // 元素时 encodeURIComponent 会产出 '[object Object]' 形态路径，宁可不重定向、
    // 留在占位页兜底
    if (typeof first === 'string' && first) history.replace(`/projects/${encodeURIComponent(first)}`);
  }, [projects]);

  return <PagePlaceholder title="项目" />;
}
