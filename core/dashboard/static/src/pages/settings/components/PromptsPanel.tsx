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

// key 集合与后端 AGENT_PROMPT_FILES 严格一致（10 个 agent，勿增删）
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
};

interface PromptsPanelProps {
  /** undefined = 用户级视图；项目名 = 项目级视图 */
  project?: string;
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
          setExtraDraft(d.project ? d.project.extras['implementer'] ?? '' : '');
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

  // 切换 agent 时把项目附加草稿重置为服务端现值
  const handleAgentChange = (atype: string) => {
    setActiveAgent(atype);
    setExtraDraft(data?.project ? data.project.extras[atype] ?? '' : '');
  };

  const activeContent = useMemo(
    () => data?.agents.find((a) => a.type === activeAgent)?.content ?? '',
    [data, activeAgent],
  );

  const handleSave = async () => {
    if (!project) return;
    setSaving(true);
    try {
      await saveProjectPrompt(project, activeAgent, extraDraft);
      message.success('项目附加提示词已保存');
      const d = await getPrompts(project);
      setData(d);
      setExtraDraft(d.project ? d.project.extras[activeAgent] ?? '' : '');
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save project prompt:', e);
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
          style={{ width: 260 }}
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
