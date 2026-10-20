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
  // 最近一次 setDirty(true) 的时刻（code-review item e52769cbc6c5）：供
  // snapshotPanelDirty 区分「发起保存前的既有脏」与「在飞保存期间的同面板
  // 再编辑」。所有置脏都经 usePanelDirty 返回的单个 setDirty 写入（面板侧
  // 无其他脏标记写点），单点记录即全覆盖；Date.now() 同一 JS 运行时单调
  // 可比，快照与再置脏之间隔至少一个事件循环任务，同毫秒碰撞不可达。
  lastDirtyAt: number;
}

const entries = new Set<PanelDirtyEntry>();

/** 活跃面板是否存在未保存改动（index 切页签/切作用域前的统一查询入口）。 */
export function anyPanelDirty(): boolean {
  for (const entry of entries) {
    if (entry.isDirty()) return true;
  }
  return false;
}

/**
 * 保存发起时锁定当前在场面板集合，返回仅复位这批面板脏标记的复位函数
 * （code-review item 1b0adfd4fcaa）。旧 resetPanelDirty 在保存成功后遍历全部
 * 在册条目，而保存是多段异步链（写盘往返 + 重载），期间页签切换未被阻断：
 * 用户在在飞保存期间经丢弃确认切到其他页签并编辑置脏，成功回调的全量复位会把
 * 新页签的脏标记一并抹掉，后续切换不再弹丢弃确认、未保存编辑被静默丢弃。
 * 面板按 activeKey 条件渲染、发起保存时被保存页签必在场，故发起时刻的快照
 * 恰为被保存面板的条目（自进化页签两张卡片各一份、同属被保存页签）：
 * 仅复位快照内仍挂载的条目，此后挂载/编辑的其他面板不受波及；保存失败时
 * 调用方不执行复位，被保存面板的脏标记原样保留（编辑仍未落盘）。
 *
 * 同面板再编辑守卫（code-review item e52769cbc6c5）：面板未锁定，在飞期间
 * 用户仍可在被保存面板上继续编辑并 setDirty(true)，若成功回调无条件复位，
 * 这批未落盘的再编辑会被抹脏、后续切页签静默丢弃。复位前比对 lastDirtyAt：
 * 仅复位「快照后未再置脏」的条目——快照时刻已脏且此后未再置脏（编辑确已
 * 落盘）才复位；快照后新置脏（lastDirtyAt > 快照时刻）的一律保留。快照
 * 时刻未脏的条目本就无脏可清，复位与否行为等价，无需逐条目记录快照时值。
 * probe 型面板 reset 本为 no-op，脏状态由面板自身归零，不受此门禁影响。
 */
export function snapshotPanelDirty(): () => void {
  const armed = new Set(entries);
  const snapshotAt = Date.now();
  return () => {
    for (const entry of armed) {
      if (!entries.has(entry)) continue;
      // 在飞保存期间的同面板再编辑不被复位（code-review item e52769cbc6c5）
      if (entry.lastDirtyAt > snapshotAt) continue;
      entry.reset();
    }
  };
}

/**
 * 面板判脏挂钩：默认由面板在用户编辑事件（Form onValuesChange / 受控输入
 * onChange）里 setDirty(true) 置脏，保存成功后由 index 对发起保存时快照的
 * 在场面板统一复位（snapshotPanelDirty）；PromptsPanel 等自持草稿的面板可传入
 * probe 按既有判脏口径注册（probe 每次实时求值，忽略内部 dirtyRef）。
 * 卸载自动注销。
 *
 * 复位契约：reset 只清 dirtyRef，对 probe 型面板是有意的 no-op——其脏状态由
 * 面板自身在保存成功后同步草稿与基线/服务端快照来归零（PromptsPanel 的
 * refetch/syncSavedExtra、ProjectProfilePanel 的基线回打），不经
 * snapshotPanelDirty 统一复位；探针实时比对口径下外部清脏反而会掩盖仍与
 * 落盘不一致的草稿（见 ProjectProfilePanel 对单一脏布尔连带清标记的取舍）。
 */
export function usePanelDirty(probe?: () => boolean): { setDirty: (dirty: boolean) => void } {
  const dirtyRef = useRef(false);
  // probe 经 ref 间接引用（镜像 index.tsx 的 scopeRef 模式）：内联箭头每次
  // 渲染都是新引用，注册效果只跑一次、探针读到的始终是最新闭包
  const probeRef = useRef(probe);
  // 注册表条目经 ref 镜像回 setDirty（code-review item e52769cbc6c5）：条目
  // 在注册 effect 内创建，setDirty 需要引用它记录置脏时刻；卸载即注销并清
  // 引用，迟到的 setDirty（面板卸载后事件不可达，防御性兜底）不写已注销条目
  const entryRef = useRef<PanelDirtyEntry | null>(null);
  useEffect(() => {
    probeRef.current = probe;
  }, [probe]);
  useEffect(() => {
    const entry: PanelDirtyEntry = {
      isDirty: () => (probeRef.current ? probeRef.current() : dirtyRef.current),
      reset: () => {
        dirtyRef.current = false;
      },
      lastDirtyAt: 0,
    };
    entryRef.current = entry;
    entries.add(entry);
    return () => {
      entries.delete(entry);
      if (entryRef.current === entry) entryRef.current = null;
    };
  }, []);
  return {
    setDirty: (dirty: boolean) => {
      // 置脏即记录时刻（code-review item e52769cbc6c5）：snapshotPanelDirty
      // 以此区分在飞保存期间的新编辑与发起保存前的既有脏。setDirty 是全部
      // 非探针置脏路径的唯一入口，此处单点记录即覆盖所有面板的置脏调用
      if (dirty) {
        const entry = entryRef.current;
        if (entry) entry.lastDirtyAt = Date.now();
      }
      dirtyRef.current = dirty;
    },
  };
}
