// /v2/projects/:name — v2 项目详情页（redesign-dashboard-v2-ui 2.2）。
//
// UI 真相源：spec/changes/redesign-dashboard-v2-ui/prototype/project-detail.html
// （标题带 + 四页签磁贴 + SPEC 表格，批注修订：页签对齐现产功能开发/代码审查/
// 测试回归/会话接入，后三页签本期为占位说明）。数据消费 /api/specs 真实端点；
// 列语义（进度 phase / 验证计数 / 耗时格式）与现产 projects/list 同源同口径，
// 不重造判定。原型「新建 SPEC」按钮无对应端点（services 无 createSpec），按
// 交互契约不渲染无定义行为的控件。
//
// 2026-11-06 用户指令六项（原型豁免点随指令修订）：
// 1. 页底改纯白 + 内容列随外部容器满宽、左右固定 30px（V2Page
//    variant="projects"，镜像 v2.less `.v2-page.v2-projects`）；
// 2. 页标题收编全站统一标题栏控件（V2Page titleBar 槽位 + PageTitleBar，同
//    原版 projects/list 逻辑：返回箭头回概览 + 项目名 + 「共 N 个 SPEC」计数
//    随迁标题栏；自画 V2TitleBand 退役）；
// 3. 表格撑满容器（满宽内容列承载）；
// 4. 表格分页参考原版（pageSize 20 + showSizeChanger + 「共 N 条」）；
// 5. 状态过滤下拉参考原版：LIST_STATUSES 全 11 态恒显（旧实现只列表内
//    出现过的状态键，空态不可过滤）；
// 6. 页签与原版保持一致：六分面全量对齐——代码审查/测试回归/架构蓝图/
//    项目知识/会话接入复用现产组件（active 门控按需加载），占位说明页签退役。
import { Alert, App, Button, Dropdown, Input, Progress, Radio, Select, Spin, Table, Tabs } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import { deleteSpec, getSpecs, statusMeta } from '@/services/dashboard';
import type { SpecSummary } from '@/services/dashboard';
import { fmtDuration } from '@/utils/duration';
import { pct } from '@/utils/percent';
import { PageTitleBar, TitleBarNum } from '@/components/PageTitleBar';
// 状态过滤值域与页签类型单源对齐现产（2026-11-06 用户指令五/六：下拉全 11 态、
// 页签键域与 projects/list 同表）
import { LIST_STATUSES } from '@/pages/projects/listFilters';
import type { ListTab } from '@/pages/projects/listFilters';
import QualityTab from '@/pages/projects/components/QualityTab';
import RegressionTab from '@/pages/projects/components/RegressionTab';
import ArchitectureTab from '@/pages/projects/components/ArchitectureTab';
import KnowledgeTab from '@/pages/projects/components/KnowledgeTab';
import SessionPanel from '@/pages/projects/components/SessionPanel';
import { V2IconDots, V2Page, V2Pill, V2StatusPill } from './shared';
import {
  useV2IsMobile,
  V2_HAIRLINE,
  V2_RAMP_GATES,
  V2_RAMP_IMPLEMENTING,
  V2_RAMP_PLANNING,
  V2_RAMP_VERIFYING,
  V2_SPLIT,
  V2_TEXT,
  V2_TEXT_QUATERNARY,
  V2_TEXT_TERTIARY,
} from './theme';

// 现产口径：mode fast-track=快速 / full=标准
const MODE_LABEL: Record<string, string> = { 'fast-track': '快速', full: '标准' };

// 已完结终态（「已完成」Radio 过滤口径；其余非终态全算「进行中」）
const DONE_STATUSES = new Set(['pushed', 'archived', 'done']);

// 状态过滤选项单源对齐现产（2026-11-06 用户指令「下拉内容参考原版全部显示」）：
// LIST_STATUSES 全 11 态恒显（v2 旧实现派生自表内出现过的状态键，空态/新态
// 不可过滤），label 单源 statusMeta（与 projects/list 同款映射）
const STATUS_OPTIONS = LIST_STATUSES.map((k) => ({ value: k, label: statusMeta(k).label }));

/** 任务进度单元（现产 list 语义：impl 任务计数 / gates 门禁计数 / verify 验证
 * 计数；verify 未开始而出题进度可见时展示出题青。原型 PHASE 四态的 planning
 * 由 generation 分支承载）。 */
function PhaseProgressCell({ s }: { s: SpecSummary }) {
  const isVerify = s.progress_phase === 'verify';
  const showGeneration =
    isVerify && s.verify_total === 0 && s.generation != null && s.generation.total > 0;

  let label = '实现';
  let color = V2_RAMP_IMPLEMENTING;
  let done = s.task_done;
  let total = s.task_total;
  if (s.progress_phase === 'gates') {
    label = '门禁';
    color = V2_RAMP_GATES;
    done = s.gates_done ?? 0;
    total = s.gates_total ?? 0;
  } else if (showGeneration) {
    label = '出题';
    color = V2_RAMP_PLANNING;
    done = s.generation!.done;
    total = s.generation!.total;
  } else if (isVerify) {
    label = '验证';
    color = V2_RAMP_VERIFYING;
    done = s.verify_done;
    total = s.verify_total;
  }
  const percent = pct(done, total);
  const current = s.progress_phase === 'gates' ? s.gates_current : isVerify ? s.verify_current : undefined;

  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>{label}</span>
        <span className="v2-num" style={{ fontSize: 12, fontWeight: 600 }}>
          {done}/{total} · {percent}%
        </span>
      </div>
      <div style={{ marginTop: 6 }}>
        <Progress percent={percent} size="small" strokeColor={color} railColor={V2_HAIRLINE} showInfo={false} />
      </div>
      {current ? (
        <div className="v2-ellipsis" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 4 }} title={current}>
          {current}
        </div>
      ) : null}
    </div>
  );
}

/** 验证单元（现产口径：verify_error 异常 / 无验证数据未执行 / 其余计数——
 * 计数完成不断言「通过」，验证结论属 spec 详情 verdict 数据，列表不伪装）。 */
function VerifyCell({ s }: { s: SpecSummary }) {
  if (s.verify_error) {
    return (
      <V2Pill tone="critical" style={{ cursor: 'default' }}>
        <span title={s.verify_error}>验证异常</span>
      </V2Pill>
    );
  }
  if (!s.verify_total) return <V2Pill tone="muted">未执行</V2Pill>;
  const running = s.verify_done < s.verify_total;
  return (
    <V2Pill tone={running ? 'info' : 'muted'} style={{ cursor: 'default' }}>
      <span className="v2-num">
        {s.verify_done}/{s.verify_total}
      </span>
    </V2Pill>
  );
}

function SpecDevPane({
  project,
  specs,
  onChanged,
  mobile,
}: {
  project: string;
  specs: SpecSummary[];
  onChanged: () => void;
  mobile?: boolean;
}) {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [statusSel, setStatusSel] = useState<string[]>([]);
  const [modeSel, setModeSel] = useState<'all' | 'fast-track' | 'full'>('all');
  const [lifeFilter, setLifeFilter] = useState<'all' | 'active' | 'done'>('all');
  const [busy, setBusy] = useState(false);

  const list = useMemo(() => {
    let out = specs;
    if (lifeFilter === 'active') out = out.filter((s) => !DONE_STATUSES.has(s.status || ''));
    if (lifeFilter === 'done') out = out.filter((s) => DONE_STATUSES.has(s.status || ''));
    if (statusSel.length) out = out.filter((s) => s.status && statusSel.includes(s.status));
    if (modeSel !== 'all') out = out.filter((s) => s.mode === modeSel);
    const kw = keyword.trim().toLowerCase();
    if (kw) out = out.filter((s) => s.name.toLowerCase().includes(kw));
    return out;
  }, [specs, keyword, statusSel, modeSel, lifeFilter]);

  const confirmDelete = (s: SpecSummary) => {
    modal.confirm({
      title: `删除 SPEC ${s.name}？`,
      content: '将从项目中删除该 SPEC 目录，不可撤销。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setBusy(true);
        try {
          await deleteSpec(project, s.name);
          message.success('已删除');
          onChanged();
        } catch (e) {
          message.error(e instanceof Error ? e.message : String(e));
        } finally {
          setBusy(false);
        }
      },
    });
  };

  // 行操作三点菜单单源（桌面操作列与移动卡片流两形态共用，v2-commercial-ui
  // 「双形态分支」行级组件两形态复用）——菜单项与跳转口径只此一份，新增菜单
  // 项或改路径不再两处同改。
  const buildRowMenu = (s: SpecSummary) => (
    <Dropdown
      menu={{
        items: [
          { key: 'detail', label: '打开详情' },
          { key: 'topo', label: '协作拓扑' },
          { type: 'divider' },
          { key: 'delete', label: '删除', danger: true, disabled: busy },
        ],
        onClick: ({ key, domEvent }) => {
          domEvent.stopPropagation();
          if (key === 'detail') navigate(`/v2/projects/${encodeURIComponent(project)}/${encodeURIComponent(s.name)}`);
          if (key === 'topo')
            navigate(
              `/projects/${encodeURIComponent(project)}/${encodeURIComponent(s.name)}/topology`,
            );
          if (key === 'delete') confirmDelete(s);
        },
      }}
      placement="bottomRight"
      trigger={['click']}
    >
      <Button type="text" size="small" icon={<V2IconDots />} aria-label="更多操作" />
    </Dropdown>
  );

  const columns: ColumnsType<SpecSummary> = [
    { title: '状态', dataIndex: 'status', width: 96, render: (_, s) => <V2StatusPill status={s.status} /> },
    {
      title: '模式',
      dataIndex: 'mode',
      width: 84,
      render: (_, s) =>
        s.mode ? (
          <V2Pill tone={s.mode === 'fast-track' ? 'warning' : 'muted'}>{MODE_LABEL[s.mode] || s.mode}</V2Pill>
        ) : (
          <span className="v2-num" style={{ color: V2_TEXT_QUATERNARY }}>—</span>
        ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      render: (_, s) => (
        <div style={{ minWidth: 0 }}>
          <span
            className="v2-ellipsis"
            style={{ fontSize: 13.5, fontWeight: 600, cursor: 'pointer', display: 'block', color: V2_TEXT }}
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/v2/projects/${encodeURIComponent(project)}/${encodeURIComponent(s.name)}`);
            }}
            title={s.name}
          >
            {s.name}
          </span>
          {/* add-spec-chinese-title：英文名主行下方中文标题副标题（v2 台账
              次级文字 token、小于主行字号、单行省略）。副标题不承载独立
              点击目标（点击落行 onClick 跳详情，与既有行点击一致）；
              title 缺失/空不渲染（保持既有单行形态）。 */}
          {s.title ? (
            <div className="v2-ellipsis" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
              {s.title}
            </div>
          ) : null}
        </div>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 84,
      render: (_, s) =>
        s.priority != null ? (
          <span className="v2-num" style={{ fontSize: 13 }}>P{s.priority}</span>
        ) : (
          <span className="v2-num" style={{ color: V2_TEXT_QUATERNARY }}>—</span>
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'created',
      width: 100,
      render: (_, s) =>
        s.created ? (
          <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
            {dayjs(s.created).format('MM-DD')}
          </span>
        ) : (
          <span className="v2-num" style={{ color: V2_TEXT_QUATERNARY }}>—</span>
        ),
    },
    { title: '任务进度', key: 'task', width: 220, render: (_, s) => <PhaseProgressCell s={s} /> },
    { title: '验证', key: 'verify', width: 92, render: (_, s) => <VerifyCell s={s} /> },
    {
      title: '耗时',
      dataIndex: 'total_duration',
      width: 84,
      align: 'right',
      render: (v: number) => (
        <span className="v2-num" style={{ fontSize: 12.5, color: V2_TEXT }}>
          {v ? fmtDuration(v) : '—'}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'act',
      width: 64,
      align: 'right',
      render: (_, s) => buildRowMenu(s),
    },
  ];

  // 移动形态（prototype/m-project-detail.html）：筛选双下拉（状态/模式）+
  // SPEC 卡片流（名称+状态/模式/验证胶囊+阶段进度+耗时）；生命周期 Radio 与
  // 搜索框为桌面形态工具，移动端按原型收敛（渐进披露，过滤语义由双下拉承载）。
  if (mobile) {
    return (
      <div style={{ paddingTop: 4 }}>
        <div data-proto-id="pd-toolbar" style={{ display: 'flex', gap: 8, paddingBottom: 10 }}>
          <Select
            size="small"
            mode="multiple"
            placeholder="状态"
            style={{ flex: 1, minWidth: 0 }}
            maxTagCount={1}
            value={statusSel}
            onChange={setStatusSel}
            allowClear
            options={STATUS_OPTIONS}
          />
          <Select
            size="small"
            placeholder="模式"
            style={{ flex: 1, minWidth: 0 }}
            value={modeSel === 'all' ? undefined : modeSel}
            onChange={(v) => setModeSel((v as 'all' | 'fast-track' | 'full') ?? 'all')}
            allowClear
            options={[
              { value: 'fast-track', label: '快速' },
              { value: 'full', label: '标准' },
            ]}
          />
        </div>
        <div>
          {list.map((s) => (
            <div key={s.name} data-proto-id={`pd-row-${s.name}`} style={{ borderTop: `1px solid ${V2_SPLIT}`, padding: '12px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span
                  className="v2-ellipsis"
                  style={{ fontSize: 14, fontWeight: 600, flex: 1, cursor: 'pointer', color: V2_TEXT }}
                  onClick={() => navigate(`/v2/projects/${encodeURIComponent(project)}/${encodeURIComponent(s.name)}`)}
                  title={s.name}
                >
                  {s.name}
                </span>
                {buildRowMenu(s)}
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <V2StatusPill status={s.status} />
                {s.mode ? (
                  <V2Pill tone={s.mode === 'fast-track' ? 'warning' : 'muted'}>{MODE_LABEL[s.mode] || s.mode}</V2Pill>
                ) : null}
                <VerifyCell s={s} />
                <span
                  className="v2-num"
                  style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginLeft: 'auto', alignSelf: 'center' }}
                >
                  {s.total_duration ? fmtDuration(s.total_duration) : '—'}
                </span>
              </div>
              <div style={{ marginTop: 8 }}>
                <PhaseProgressCell s={s} />
              </div>
            </div>
          ))}
          {!list.length ? (
            <div style={{ padding: '14px 0', fontSize: 12, color: V2_TEXT_TERTIARY }}>无匹配 SPEC</div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div style={{ paddingTop: 4 }}>
      <div
        data-proto-id="pd-toolbar"
        style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '8px 0 12px' }}
      >
        <Input.Search
          placeholder="搜索 SPEC"
          size="small"
          allowClear
          style={{ width: 200 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select
          size="small"
          mode="multiple"
          placeholder="状态"
          style={{ minWidth: 140 }}
          maxTagCount={2}
          value={statusSel}
          onChange={setStatusSel}
          allowClear
          options={STATUS_OPTIONS}
        />
        <Radio.Group
          optionType="button"
          size="small"
          value={lifeFilter}
          onChange={(e) => setLifeFilter(e.target.value)}
          options={[
            { label: '全部', value: 'all' },
            { label: '进行中', value: 'active' },
            { label: '已完成', value: 'done' },
          ]}
        />
      </div>
      <div className="v2-bento-table" data-proto-id="pd-table">
        <Table
          columns={columns}
          dataSource={list}
          rowKey="name"
          // 分页参考原版（2026-11-06 用户指令四）：pageSize 20 + 可换页大小 +
          // 「共 N 条」合计，口径与 projects/list DevTab 同款
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          size="middle"
          scroll={{ x: 1080 }}
          onRow={(rec) => ({
            onClick: () => navigate(`/v2/projects/${encodeURIComponent(project)}/${encodeURIComponent(rec.name)}`),
            style: { cursor: 'pointer' },
          })}
        />
      </div>
    </div>
  );
}

export default function V2ProjectDetailPage() {
  const { name = '' } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const mobile = useV2IsMobile();
  const [specs, setSpecs] = useState<SpecSummary[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const res = await getSpecs(name);
      if (seq !== seqRef.current) return;
      // v1 兼容契约：未知项目 200 + {error, specs: []}
      if (res.error) {
        setError(res.error);
        setSpecs(res.specs || []);
      } else {
        setError('');
        setSpecs(res.specs || []);
      }
    } catch (e) {
      if (seq !== seqRef.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [name]);

  useEffect(() => {
    void load();
    return () => {
      seqRef.current += 1;
    };
  }, [load]);

  const activeCount = useMemo(
    () => (specs || []).filter((s) => s.run_activity?.active).length,
    [specs],
  );

  // 页签选中态（2026-11-06 用户指令六：六分面对齐现产 projects/list，键域单源
  // ListTab）。现产把 tab 持久化到 URL 参数属过滤粘滞域，v2 页维持改造前
  // defaultActiveKey 等价的内存态，不引入 URL 契约。
  const [activeTab, setActiveTab] = useState<ListTab>('dev');

  return (
    <V2Page
      variant="projects"
      titleBar={
        // 统一标题栏声明（2026-11-06 用户指令二，同原版 projects/list 逻辑）：
        // 返回箭头回 /v2/overview + 项目名 + 「共 N 个 SPEC · M 个活跃」计数
        // 随迁（TitleBarNum 等宽）。行壳位（embed/移动端）满宽贴顶由 V2Page
        // titleBar 槽位结构保证（.v2-page 直下、.v2-inner 之前）。
        <PageTitleBar
          back={() => navigate('/v2/overview')}
          title={name}
          subtitle={
            specs ? (
              <>
                共 <TitleBarNum>{specs.length}</TitleBarNum> 个 SPEC ·{' '}
                <TitleBarNum>{activeCount}</TitleBarNum> 个活跃
              </>
            ) : undefined
          }
        />
      }
    >
      {error ? (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message="SPEC 列表加载失败" description={error} />
      ) : null}
      {loading && !specs ? (
        <div className="v2-bento" style={{ padding: 48, textAlign: 'center' }}>
          <Spin size="large" />
        </div>
      ) : null}
      {specs ? (
        <div className="v2-bento" data-proto-id="pd-panel" style={{ padding: '4px 20px 16px' }}>
          <Tabs
            activeKey={activeTab}
            onChange={(k) => setActiveTab(k as ListTab)}
            items={[
              {
                key: 'dev',
                label: '功能开发',
                children: <SpecDevPane project={name} specs={specs} onChanged={() => void load()} mobile={mobile} />,
              },
              {
                key: 'quality',
                label: '代码审查',
                // 现产组件复用（2026-11-06 用户指令六）；active 门控未选中零请求
                children: <QualityTab project={name} active={activeTab === 'quality'} />,
              },
              {
                key: 'regression',
                label: '测试回归',
                children: <RegressionTab project={name} active={activeTab === 'regression'} />,
              },
              {
                key: 'architecture',
                label: '架构蓝图',
                children: <ArchitectureTab project={name} active={activeTab === 'architecture'} />,
              },
              {
                key: 'knowledge',
                label: '项目知识',
                children: <KnowledgeTab project={name} active={activeTab === 'knowledge'} />,
              },
              {
                key: 'session',
                label: '会话接入',
                children: <SessionPanel project={name} active={activeTab === 'session'} />,
              },
            ]}
          />
        </div>
      ) : null}
    </V2Page>
  );
}
