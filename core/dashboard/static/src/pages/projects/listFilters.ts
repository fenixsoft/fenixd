// add-spec-list-filter-stickiness D2/D3：SPEC 开发列表过滤状态 ↔ URL 查询参数
// 的白名单与缺省约定。纯函数形态（零依赖、无 JSX），便于纳入 node --test 纯函数单测。

export type ListTab = 'dev' | 'quality' | 'regression' | 'session';
export type ListTypeFilter = '' | 'active' | 'completed';

// 页签合法值域（与项目页分面 Tabs 的 key 同序）
export const LIST_TABS: readonly ListTab[] = ['dev', 'quality', 'regression', 'session'];

// 状态合法枚举（11 项）：与列表「全部状态」过滤下拉同源（list.tsx 的 Select
// options 直接引用此常量），键序即 list.tsx 过滤下拉的既有展示序。
// 注意：与 services/dashboard.ts 的 STATUS_META 键序**不同**——reviewing
// （add-spec-review-gate 追加）在彼处居末位，在此处沿用下拉原有第三位。
export const LIST_STATUSES: readonly string[] = [
  'drafted', 'ready', 'reviewing', 'implementing', 'implemented', 'testing',
  'verified', 'bug-found', 'blocked', 'done', 'pushed',
];

// 类型过滤合法值域。ListTypeFilter 的 '' 仅为解析器「无过滤」回退值，
// 不是合法 URL 值（type= 空串或非法值一律回 ''，缺省不写参），故白名单不含 ''。
export const LIST_TYPES: readonly ListTypeFilter[] = ['active', 'completed'];

export interface ListFilters {
  tab: ListTab;
  q: string;
  statusList: string[];
  type: ListTypeFilter;
  archivedOnly: boolean;
}

// fail-safe 白名单解析（D3）：URL 可被手工改坏——
// - 非法 tab / type 整体忽略回默认；
// - status 逗号分隔逐项校验，非法枚举丢弃（全非法视为无参），去重保序；
// - archived 仅 '1' 视为已归档；
// - q trim 后空串视为无参。
// 解析即消毒：不崩溃、不产生 console error，mount 后写回 effect 首跑会把脏
// 参数清洗为干净形态。
export function parseListFilters(searchParams: URLSearchParams): ListFilters {
  const rawTab = searchParams.get('tab') as ListTab | null;
  const tab: ListTab = rawTab !== null && LIST_TABS.includes(rawTab) ? rawTab : 'dev';

  const q = (searchParams.get('q') || '').trim();

  const statusList = [...new Set(
    (searchParams.get('status') || '')
      .split(',')
      .map((s) => s.trim())
      .filter((s) => LIST_STATUSES.includes(s)),
  )];

  const rawType = searchParams.get('type') as ListTypeFilter | null;
  const type: ListTypeFilter = rawType !== null && LIST_TYPES.includes(rawType) ? rawType : '';

  const archivedOnly = searchParams.get('archived') === '1';

  return { tab, q, statusList, type, archivedOnly };
}
