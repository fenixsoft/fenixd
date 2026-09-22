import { Button, Input, Select, Typography, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
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

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const d = await getPrompts(project);
        if (!cancelled) {
          setData(d);
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
        if (!cancelled) message.error(`加载提示词失败：${e instanceof Error ? e.message : e}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
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
    if (!project) return;
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
      setData(d);
      // 仅当用户仍停在同一 agent 时才回填草稿（避免覆盖刚切到的 agent）
      if (targetAgent === activeAgent) {
        setExtraDraft(projectExtraOf(d, targetAgent));
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
          disabled={saving}
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
