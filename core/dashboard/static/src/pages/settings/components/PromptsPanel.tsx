import { Button, Input, Select, Typography, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { getPrompts, saveProjectPrompt } from '@/services/dashboard';
import type { PromptsData } from '@/services/dashboard';

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

export default function PromptsPanel({ project }: PromptsPanelProps) {
  const [data, setData] = useState<PromptsData | null>(null);
  const [activeAgent, setActiveAgent] = useState<string>('implementer');
  const [extraDraft, setExtraDraft] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const isProjectScope = Boolean(project);

  // 面板当前内容归属的项目（code-review item f0be525a11f2 / f2830281595d）：
  // handleSave 闭包里的 project 与 refetch 都是保存发起时的快照；用户在请求
  // 在飞期间切换项目（或拒绝了切换确认、面板仍显示旧项目内容）时，以
  // loadedFor 与当前 project 对账决定 setData/保存是否生效——旧项目内容
  // 不再盖回新项目视图、也不会被写进新项目。
  const loadedForRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    // 项目切换丢弃确认（code-review item f2830281595d）：与 handleAgentChange
    // 同语义——切换 agent 前询问，切换 project 却静默覆盖草稿。此处读到的
    // data/extraDraft 仍是旧项目的渲染快照（effect 跑在 project 已变、state
    // 未变的渲染之后）。拒绝则保留当前内容、不加载新项目；此时 loadedFor
    // 与当前 project 不一致，handleSave 的对账会拦住跨项目错写。
    if (
      data &&
      extraDraft !== projectExtraOf(data, activeAgent) &&
      !window.confirm('当前项目的修改尚未保存，切换将丢弃，确定继续？')
    ) {
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
          const errPayload = (d as { error?: string }).error;
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
          setActiveAgent('implementer');
          setExtraDraft(projectExtraOf(d, 'implementer'));
        }
      } catch (e) {
        console.error('Failed to load prompts:', e);
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

  const handleAgentChange = (atype: string) => {
    if (extraDraft !== serverDraftFor(activeAgent) && !window.confirm('当前 agent 的修改尚未保存，切换将丢弃，确定继续？')) {
      return;
    }
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
    setSaving(true);
    try {
      await saveProjectPrompt(project, targetAgent, extraDraft);
      message.success('项目附加提示词已保存');
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save project prompt:', e);
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
        setData(d);
        // 仅当用户仍停在同一 agent 时才回填草稿（避免覆盖刚切到的 agent）
        if (targetAgent === activeAgent) {
          setExtraDraft(projectExtraOf(d, targetAgent));
        }
      }
    } catch (e) {
      message.warning(`已保存，但刷新列表失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
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
          maxHeight: 600, overflow: 'auto', background: '#fafafa',
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
            style={{ marginTop: 8 }}
          />
          <div style={{ marginTop: 12, textAlign: 'right' }}>
            <Button
              type="primary"
              data-testid="prompts-extra-save"
              loading={saving}
              // 加载中禁用（code-review item 96880454231c）：草稿可能是上一
              // 项目的残留内容，保存会跨项目错写。
              disabled={loading}
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
