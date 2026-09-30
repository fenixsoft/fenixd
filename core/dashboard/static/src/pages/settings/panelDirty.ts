import { useEffect, useRef } from 'react';

// 页签/作用域切换丢弃确认的判脏注册表（code-review item 8a3eb01dc2b9）：
// 设置页右侧面板按 activeKey 条件渲染，切页签/切作用域即卸载当前面板、未保存
// 的编辑随之丢弃且无提示；PromptsPanel 对切项目已补 window.confirm 确认（item
// f2830281595d），两套口径并存。现由 index.tsx 在切页签/切作用域前经
// anyPanelDirty() 统一查询「活跃面板是否有未保存改动」，有则弹确认；各面板
// 挂载时经 usePanelDirty() 登记、卸载时自动注销（面板按页签条件渲染，同一时刻
// 至多一个页签在场，自进化页签两张卡片各登记一份，任一为脏即弹确认）。
//
// 判脏采用「用户编辑事件显式置脏」而非 Form.isFieldsTouched()：touched 在保存
// 成功后的 setFieldsValue 回填里不会清除（各面板回填均为内容比较门控、无
// resetFields），已保存的编辑会被误报成未保存、每次切页签都弹确认。

interface PanelDirtyEntry {
  isDirty: () => boolean;
  reset: () => void;
}

const entries = new Set<PanelDirtyEntry>();

/** 活跃面板是否存在未保存改动（index 切页签/切作用域前的统一查询入口）。 */
export function anyPanelDirty(): boolean {
  for (const entry of entries) {
    if (entry.isDirty()) return true;
  }
  return false;
}

/** 保存成功后统一复位（index 的 handleSave 是全部配置面板保存的公共出口）。 */
export function resetPanelDirty(): void {
  entries.forEach((entry) => entry.reset());
}

/**
 * 面板判脏挂钩：默认由面板在用户编辑事件（Form onValuesChange / 受控输入
 * onChange）里 setDirty(true) 置脏，保存成功后由 index 统一 setDirty(false)/
 * resetPanelDirty() 复位；PromptsPanel 等自持草稿的面板可传入 probe 按既有
 * 判脏口径注册（probe 每次实时求值，忽略内部 dirtyRef）。卸载自动注销。
 */
export function usePanelDirty(probe?: () => boolean): { setDirty: (dirty: boolean) => void } {
  const dirtyRef = useRef(false);
  // probe 经 ref 间接引用（镜像 index.tsx 的 scopeRef 模式）：内联箭头每次
  // 渲染都是新引用，注册效果只跑一次、探针读到的始终是最新闭包
  const probeRef = useRef(probe);
  useEffect(() => {
    probeRef.current = probe;
  }, [probe]);
  useEffect(() => {
    const entry: PanelDirtyEntry = {
      isDirty: () => (probeRef.current ? probeRef.current() : dirtyRef.current),
      reset: () => {
        dirtyRef.current = false;
      },
    };
    entries.add(entry);
    return () => {
      entries.delete(entry);
    };
  }, []);
  return {
    setDirty: (dirty: boolean) => {
      dirtyRef.current = dirty;
    },
  };
}
