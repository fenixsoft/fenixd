import { App, Button, Input, Select, Typography } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { getPrompts, saveProjectPrompt } from '@/services/dashboard';
import type { PromptsData } from '@/services/dashboard';
import { usePanelDirty } from '../panelDirty';

const { Text, Title } = Typography;
const { TextArea } = Input;

// key 集合与后端 AGENT_PROMPT_FILES 严格一致（含 code-review 共 12 个 agent，
// 勿增删；code-review item f62e36d1531f：旧注释写 10 个，已漂移）
const AGENT_LABELS: Record<string, string> = {
  implementer: 'Implementer（实现）',
  verifier: 'Verifier（验证）',
  'planner-plan': 'Planner Plan（场景设计）',
  'planner-judge': 'Planner Judge（结果裁决）',
  'fast-track': 'Fast-Track（实现+验证）',
  administrator: 'Administrator（运维处置）',
  'self-review': 'Self-Review（自省）',
  'dispute-judge': 'Dispute Judge（交付物终审）',
  evolution: 'Evolution（自改进）',
  'spec-review': 'Spec Review（方案评审）',
  // add-code-review-agent-and-quality-tab：新增 code-review（周期性仓库级代码审查）
  'code-review': 'Code-Review（代码审查）',
  // add-code-review-auto-fix：新增 code-fix（自动修复车道，可改码）
  'code-fix': 'Code-Fix（自动修复）',
};

interface PromptsPanelProps {
  /** undefined = 用户级视图；项目名 = 项目级视图 */
  project?: string;
}

// 项目附加提示词提取单点（code-review item 190361647678）：加载回填、
// serverDraftFor、保存后回填三处共用同一空安全与缺省规则，防止漂移。
function projectExtraOf(d: PromptsData | null | undefined, agentType: string): string {
  return d?.project ? d.project.extras[agentType] ?? '' : '';
}

// HTTP-200 错误载荷提取单点（code-review item e0dc33bb37d4）：初始加载与保存后
// refetch 两处共用同一提取规则，新增调用点一律复用此助手，避免漏掉错误载荷检查
// 历史上曾静默吞错（见 9a019b10302a / 441adfad7a94）。
const errorPayloadOf = (d: unknown): string | undefined =>
  (d as { error?: string } | null | undefined)?.error;

export default function PromptsPanel({ project }: PromptsPanelProps) {
  // 提示经 App.useApp() 取上下文实例（code-review item 3254bd677d01）：antd v5
  // 静态 message 不消费 App/ConfigProvider 上下文，与 index/useGatedFormPanel
  // 及同族面板口径统一
  const { message } = App.useApp();
  const [data, setData] = useState<PromptsData | null>(null);
  const [activeAgent, setActiveAgent] = useState<string>('implementer');
  const [extraDraft, setExtraDraft] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  // 保存重入守卫（code-review item 6e35a8c1d5cd，比照 SystemPanel 8ccf20511320）：
  // handleSave 是异步，保存请求在飞期间连点保存按钮会发出重叠的 saveProjectPrompt
  // 请求（并发写同一提示词文件，落盘结果取决于到达顺序）——saving 期间按钮置
  // loading/disabled 并在入口短路；setSaving 渲染生效存在 React 调度间隙，经
  // savingRef 写读同帧原子拦住连点，state 只负责按钮视觉反馈。
  const savingRef = useRef(false);

  const isProjectScope = Boolean(project);

  // 面板当前内容归属的项目（code-review item f0be525a11f2 / f2830281595d）：
  // handleSave 闭包里的 project 与 refetch 都是保存发起时的快照；用户在请求
  // 在飞期间切换项目（或拒绝了切换确认、面板仍显示旧项目内容）时，以
  // loadedFor 与当前 project 对账决定 setData/保存是否生效——旧项目内容
  // 不再盖回新项目视图、也不会被写进新项目。
  const loadedForRef = useRef<string | undefined>(undefined);

  // activeAgent 镜像 ref（code-review item cd7f269ddd5f）：handleSave 闭包里的
  // activeAgent 是保存发起时的快照，refetch 回填守卫 `targetAgent === activeAgent`
  // 两边同源恒相等，拦不住「保存请求刚发起的同一帧内切换 agent」——Select 的
  // disabled={saving} 是 state 口径、setSaving 渲染生效有调度间隙（同上方
  // savingRef 条目结论），切换事件已把草稿置为新 agent 的服务端值，此后回填
  // 却把旧 agent 的服务端 extra 写进草稿而选择器显示新 agent，再点保存即把
  // 旧 agent 内容写进 .fenix/agents/<新agent>.md（跨 agent 错写）。比照
  // loadedForRef 口径以 ref 同帧记录当前 agent，回填前对账。
  const activeAgentRef = useRef<string>('implementer');

  // 保存发起帧的草稿快照（code-review item ea3dc8b8bd53）：比照上方 activeAgentRef
  // 口径以 ref 同帧固化本次提交的 extraDraft。TextArea 的 disabled={saving} 是
  // state 口径、setSaving 渲染生效有调度间隙（同上方 savingRef 条目结论），点击
  // 保存同帧内键入的字符会进草稿却不在已发出的保存载荷里；回填前与快照对账，
  // 不一致则保留现值不回填，避免这几个字符被服务端值静默覆盖。
  const savedDraftRef = useRef<string>('');

  // 判脏口径单点（code-review item 5836b8df59e9）：面板当前内容相对服务端是否
  // 有未保存改动，供 usePanelDirty 探针、项目切换确认 effect、handleAgentChange
  // 三处复用，任一处调整口径只改此处，避免「切页签弹确认、切 agent 不弹」的
  // 漂移不一致。data 为空时以「草稿非空即脏」兜底（加载失败/未加载时草稿不
  // 代表服务端现值）；data 为空时 projectExtraOf 恒返回 ''，与该兜底分支等价。
  const isDirty = () =>
    data ? extraDraft !== projectExtraOf(data, activeAgent) : extraDraft !== '';

  // 页签/作用域切换丢弃确认（code-review item 8a3eb01dc2b9）：本面板自持草稿
  // 而非 antd Form，按既有判脏口径（同下方项目切换确认）向 index 注册探针，
  // 切页签前由 index 统一弹确认；切项目确认（f2830281595d）保持原位不动。
  usePanelDirty(isDirty);

  useEffect(() => {
    // 项目切换丢弃确认（code-review item f2830281595d）：与 handleAgentChange
    // 同语义——切换 agent 前询问，切换 project 却静默覆盖草稿。此处读到的
    // data/extraDraft 仍是旧项目的渲染快照（effect 跑在 project 已变、state
    // 未变的渲染之后）。拒绝则保留当前内容、不加载新项目；此时 loadedFor
    // 与当前 project 不一致，handleSave 的对账会拦住跨项目错写。
    // 加载失败场景（code-review item c542789d7297）：data 为 null 时 extra
    // 输入框仍渲染可编辑，仅以 data 判脏会跳过确认、静默丢弃用户键入的
    // 草稿——data 为空但草稿非空同样视为脏。
    const dirty = isDirty();
    if (dirty && !window.confirm('当前项目的修改尚未保存，切换将丢弃，确定继续？')) {
      return;
    }
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const d = await getPrompts(project);
        if (!cancelled) {
          // HTTP-200 错误载荷显式上报（code-review item 9a019b10302a）：
          // _api_prompts_get 出错时经 _json 返回 {error: "…"} 且 HTTP 200
          // （request() 仅在 !res.ok 时抛），旧实现静默吞掉——错误响应与
          // 「合法空提示词」不可区分（面板渲染空只读视图无反馈）。
          const errPayload = errorPayloadOf(d);
          if (errPayload) {
            message.warning(`提示词加载返回错误：${errPayload}`);
            setData(null);
            setExtraDraft('');
            loadedForRef.current = undefined;
            return;
          }
          setData(d);
          loadedForRef.current = project;
          // 切换项目时同步把 activeAgent 复位为 implementer（code-review item
          // 67694883ca76）：旧实现只重置草稿（恒取 implementer 的 extra）而不重置
          // 选择器，用户若先切到 verifier 再切项目，textarea 装的是 implementer
          // 内容而选择器显示 verifier——点保存会把 implementer 内容写进
          // .fenix/agents/verifier.md（静默错写文件）。复位后二者一致。
          // 镜像 ref 同步前移（code-review item cd7f269ddd5f）：activeAgentRef
          // 是回填对账的权威口径，所有 setActiveAgent 处都必须同帧更新。
          activeAgentRef.current = 'implementer';
          setActiveAgent('implementer');
          setExtraDraft(projectExtraOf(d, 'implementer'));
        }
      } catch (e) {
        // 不落 console，避免触发验证场景的 no_console_error 断言（同族面板口径）
        if (!cancelled) {
          message.error(`加载提示词失败：${e instanceof Error ? e.message : e}`);
          // 失败路径复位（code-review item 96880454231c）：切到项目 B 后其
          // fetch 失败时 data/extraDraft 若残留项目 A 的内容，textarea 仍持
          // A 的 extra prompt 且保存可用——handleSave 会把 A 的内容写进 B
          // （跨项目错写）。复位后保存亦被 handleSave 的 data 判空阻断。
          setData(null);
          setExtraDraft('');
          loadedForRef.current = undefined;
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  // 切换 agent 时把项目附加草稿重置为服务端现值；若当前草稿有未保存改动，
  // 先确认再丢弃（code-review item 60bca994744d：旧实现无条件覆盖，静默丢失
  // 用户已输入未保存的内容）。
  const serverDraftFor = (atype: string) => projectExtraOf(data, atype);

  // 刷新失败时的本地已保存基线同步（code-review item 37cec996892e）：保存已
  // 落盘而 refetch 失败（HTTP-200 {error} 载荷或网络异常）时 data 仍持保存前
  // 旧快照，usePanelDirty 探针按 extraDraft !== projectExtraOf(data, activeAgent)
  // 恒判脏，切页签会弹多余的「修改尚未保存」确认——内容实际已落盘。把
  // targetAgent 的 extras 就地同步为刚提交的草稿，使判脏与真实落盘状态一致
  // （不可变更新，不碰其余字段）。
  const syncSavedExtra = (agent: string, draft: string) => {
    setData((prev) =>
      prev?.project
        ? {
            ...prev,
            project: { ...prev.project, extras: { ...prev.project.extras, [agent]: draft } },
          }
        : prev,
    );
  };

  const handleAgentChange = (atype: string) => {
    if (isDirty() && !window.confirm('当前 agent 的修改尚未保存，切换将丢弃，确定继续？')) {
      return;
    }
    // 镜像 ref 在切换事件里同步更新（code-review item cd7f269ddd5f）：保存
    // 在飞期间 refetch 回填以 activeAgentRef 对账，若只靠渲染后 effect 滞后
    // 补写，同一帧内发起的回填仍会读到旧 agent、守卫失效。
    activeAgentRef.current = atype;
    setActiveAgent(atype);
    setExtraDraft(serverDraftFor(atype));
  };

  const activeContent = useMemo(
    // agents 空值防护（code-review item c3407e11dad8）：_api_prompts_get 出错时
    // 经 _json 返回 {error: "…"} 且 HTTP 200（request() 仅在 !res.ok 时抛），
    // 此时 data 非空但 agents 为 undefined，旧实现 .find 抛 TypeError 使面板崩溃。
    () => (data?.agents ?? []).find((a) => a.type === activeAgent)?.content ?? '',
    [data, activeAgent],
  );

  const handleSave = async () => {
    // data 判空（code-review item 96880454231c）：加载失败/尚未成功加载时
    // extraDraft 不代表服务端现值，保存可能把过时/空内容写进当前项目。
    if (!project || !data) return;
    // 目标一致性对账（code-review item f0be525a11f2 / f2830281595d）：面板
    // 内容不属当前 project（保存/加载在飞期间切换了项目，或用户拒绝了切换
    // 确认、面板仍显示旧项目内容）时 extraDraft 是旧项目内容——保存会跨项目
    // 错写，拦截并提示。
    if (loadedForRef.current !== project) {
      message.warning('面板内容与当前项目不一致，请等待重新加载完成后再保存');
      return;
    }
    // 固化本次保存的目标 agent（code-review item 9bb2f4e7caaa）：旧实现
    // 保存后 refetch 时仍读闭包里的 activeAgent，若请求在飞期间用户切换了
    // agent，会把**旧 agent** 的值写回 extraDraft 而 UI 显示新 agent。
    const targetAgent = activeAgent;
    if (savingRef.current) return;
    savingRef.current = true;
    // 固化提交快照（code-review item ea3dc8b8bd53）：与下方载荷读同一个闭包
    // extraDraft，同帧原子记录，供保存成功后的 refetch 回填前对账（见回填处注释）。
    savedDraftRef.current = extraDraft;
    setSaving(true);
    try {
      await saveProjectPrompt(project, targetAgent, extraDraft);
      message.success('项目附加提示词已保存');
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`保存失败：${errorMessage}`);
      // 不落 console，避免触发验证场景的 no_console_error 断言（同族面板口径）
      savingRef.current = false;
      setSaving(false);
      return;
    }
    // 保存已成功，后续 refetch 失败不得报「保存失败」（code-review item
    // 9bb2f4e7caaa 第 1 点）：独立 try/catch，仅提示刷新失败。
    try {
      const d = await getPrompts(project);
      // refetch 归属对账（code-review item f0be525a11f2）：请求在飞期间项目
      // 已切换且新项目已重新加载（loadedFor 已前移）时，无条件 setData(d) 会
      // 把旧项目内容盖回新项目视图——与新项目的 activeAgent/草稿形成跨项目
      // 串数据。仅当面板仍归属发起保存的项目时才回填。
      if (loadedForRef.current === project) {
        // HTTP-200 错误载荷检查（code-review item 441adfad7a94）：与初始加载
        // 路径同款——refetch 恰逢后端读提示词出错时返回 {error}，回填会把
        // 错误载荷当正常数据 setData（agents 缺失渲染空只读视图），且
        // projectExtraOf 返回空串静默清空用户已保存的草稿（下次保存把空串
        // 写进 .fenix/agents/<agent>.md）。检测到错误载荷仅提示刷新失败，
        // 保留现有 data/extraDraft。
        const errPayload = errorPayloadOf(d);
        if (errPayload) {
          message.warning(`已保存，但刷新列表返回错误：${errPayload}`);
          // 错误载荷分支同样同步已保存基线（code-review item 37cec996892e）：
          // 否则 data 保持保存前旧快照，判脏探针恒判脏、切页签误弹丢弃确认。
          syncSavedExtra(targetAgent, extraDraft);
        } else {
          setData(d);
          // 仅当用户仍停在同一 agent 时才回填草稿（避免覆盖刚切到的 agent）。
          // 对账读 activeAgentRef 而非闭包 activeAgent（code-review item
          // cd7f269ddd5f）：闭包值与 targetAgent 同源恒相等，拦不住保存请求
          // 刚发起同帧内发生的切换（saving 的 disabled 尚未渲染生效）。
          // 同 agent 上保存后的键入由 TextArea 的 disabled={saving} 兜底
          // （code-review item cbd7e62160ec），但该 state 口径同样有调度间隙
          // （同上方 savingRef 条目结论）：点击保存同帧内键入的字符已进草稿却
          // 不在已发出的保存载荷里，无条件回填会将其静默丢弃（code-review item
          // ea3dc8b8bd53）。故与提交快照对账，函数式更新读取回填时刻的最新草稿，
          // 仍与快照一致才回填，否则保留现值。
          if (targetAgent === activeAgentRef.current) {
            setExtraDraft((prev) =>
              prev === savedDraftRef.current ? projectExtraOf(d, targetAgent) : prev,
            );
          }
        }
      }
    } catch (e) {
      message.warning(`已保存，但刷新列表失败：${e instanceof Error ? e.message : String(e)}`);
      // 网络失败分支同步已保存基线（code-review item 37cec996892e）：使判脏
      // 与真实落盘一致；项目已在飞期间切换（loadedFor 已前移）时不动 data，
      // 避免把旧项目的内容写进新项目视图（同上方归属对账口径）。
      if (loadedForRef.current === project) {
        syncSavedExtra(targetAgent, extraDraft);
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <div>
      <Title level={5} style={{ marginTop: 0 }}>Agent 提示词</Title>
      <Text type="secondary">
        通用提示词由框架管理（只读）；项目级附加提示词保存到项目
        <code>.fenix/agents/</code>，派发时附加在对应 agent 的 prompt 末尾。
      </Text>

      <div style={{ margin: '12px 0' }} data-testid="prompts-agent-switcher">
        <Text style={{ marginRight: 8 }}>Agent：</Text>
        <Select
          value={activeAgent}
          onChange={handleAgentChange}
          // 保存进行中禁止切换 agent（code-review item 9bb2f4e7caaa）：在飞请求
          // 期间切换会让 refetch 把旧 agent 的值写回草稿而 UI 显示新 agent。
          // 加载中同样禁用（code-review item 96880454231c）：loading 期间
          // data/extraDraft 可能仍是上一项目的残留。
          disabled={saving || loading}
          style={{ width: '100%' }}
          options={Object.keys(AGENT_LABELS).map((k) => ({ value: k, label: AGENT_LABELS[k] }))}
        />
      </div>

      {/* 通用提示词（只读，两种作用域均展示）—— Markdown 渲染，圆角灰底容器 */}
      <Title level={5}>通用提示词（只读）</Title>
      <div
        data-testid="prompts-generic-content"
        style={{
          maxHeight: 800, overflow: 'auto', background: '#fafafa',
          border: '1px solid #f0f0f0', borderRadius: 6, padding: 12,
        }}
      >
        {loading ? (
          '加载中...'
        ) : (
          <Markdown
            remarkPlugins={[remarkGfm, remarkBreaks]}
            components={{
              ...markdownComponents,
              // 提示词正文以 JSON 示例块为主：等宽 pre-wrap 代码块，深一档灰底与容器区分
              pre: ({ children }) => (
                <pre
                  style={{
                    margin: '8px 0', padding: 8, fontSize: 12, lineHeight: 1.6,
                    background: '#f0f0f0', borderRadius: 4,
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowX: 'auto',
                  }}
                >
                  {children}
                </pre>
              ),
            }}
          >
            {activeContent}
          </Markdown>
        )}
      </div>

      {/* 项目级附加提示词（仅项目作用域） */}
      {isProjectScope && (
        <div style={{ marginTop: 16 }} data-testid="prompts-extra-section">
          <Title level={5}>项目附加提示词</Title>
          <Text type="secondary">
            保存在项目 <code>.fenix/agents/{activeAgent}.md</code>，
            为空表示该项目无附加提示词。
          </Text>
          <TextArea
            data-testid="prompts-extra-textarea"
            value={extraDraft}
            onChange={(e) => setExtraDraft(e.target.value)}
            placeholder="自由 Markdown，例如本项目特有的验证规范、选择器约定等"
            autoSize={{ minRows: 6, maxRows: 14 }}
            // 保存/加载进行中禁止编辑（code-review item cbd7e62160ec /
            // 9cc6704ab4c1）：与 Select 的 disabled={saving || loading} 同口径
            // ——在飞期间继续键入的内容不在已提交的 extraDraft 里，加载/回填
            // 会用服务端值无条件覆盖（静默丢失）。
            disabled={saving || loading}
            style={{ marginTop: 8 }}
          />
          <div style={{ marginTop: 12, textAlign: 'right' }}>
            <Button
              type="primary"
              data-testid="prompts-extra-save"
              loading={saving}
              // 加载中禁用（code-review item 96880454231c）：草稿可能是上一
              // 项目的残留内容，保存会跨项目错写。未加载完成/加载失败时
              // data 为空同样禁用（item 3afce137e38e）：handleSave 入口的
              // `!data` 守卫会静默 return，不禁用则点击无任何反馈。
              // 保存进行中一并禁用（code-review item 6e35a8c1d5cd）：仅 loading
              // 时保存请求在飞期间按钮仍可点击，同帧双击可并发发出两次保存
              // （antd loading 拦截依赖重渲染提交后的 handleClick 短路）。
              disabled={saving || loading || !data}
              onClick={handleSave}
            >
              保存项目附加提示词
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
