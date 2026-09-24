import { Alert, Button, Card, Input, Popconfirm, Typography, message } from 'antd';
import { useState, useEffect, useRef } from 'react';
import type { ConfigData } from '@/services/dashboard';
import {
  autodraftVerifyYaml,
  getVerifyYaml,
  getVerifyYamlTemplate,
  regenerateProjectDescription,
  saveVerifyYaml,
} from '@/services/dashboard';

const { TextArea } = Input;
const { Text } = Typography;

interface ProjectProfilePanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  project?: string;
  /** 聚焦信号（时间戳）：质量页签「手工编辑」跳转过来时 >0，滚动定位到
   *  verify.yaml 卡片并聚焦编辑框；常规切页签传 0 不触发 */
  focusVerifySignal?: number;
}

export default function ProjectProfilePanel({ config, onSave, project, focusVerifySignal }: ProjectProfilePanelProps) {
  const [description, setDescription] = useState(config.description || '');
  const [loading, setLoading] = useState(false);
  // 「手工编辑」跳转定位：ref 指向本实例渲染的卡片/编辑框（不用
  // querySelector——设置页切作用域曾出现双 DOM 实例并存，选择器会命中隐藏实例）
  const verifySectionRef = useRef<HTMLDivElement>(null);
  const yamlTextareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setDescription(config.description || '');
  }, [config.description]);

  // 聚焦信号到达：滚到 verify.yaml 卡片并把光标送入编辑框（延迟等待页签
  // 切换后本面板真正挂载渲染完成）
  useEffect(() => {
    if (!focusVerifySignal) return;
    verifySectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const t = setTimeout(() => {
      const el = yamlTextareaRef.current;
      if (el) {
        el.focus();
        const len = el.value.length;
        try {
          el.setSelectionRange(len, len);
        } catch {
          /* setSelectionRange 对特定 type 可能抛错，聚焦已达成即可 */
        }
      }
    }, 300);
    return () => clearTimeout(t);
  }, [focusVerifySignal]);

  const handleSave = async () => {
    try {
      await onSave({ description });
      message.success('保存成功');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save description:', error);
    }
  };

  const handleRegenerate = async () => {
    if (!project) {
      message.error('项目名称缺失，无法重新生成');
      return;
    }

    setLoading(true);
    try {
      const result = await regenerateProjectDescription(project);
      if (result.ok) {
        setDescription(result.description);
        message.success('简介重新生成成功');
        // 刷新配置以确保一致性
        await onSave({ description: result.description });
      } else {
        message.error(result.error || '重新生成失败');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`重新生成失败：${errorMessage}`);
      console.error('Failed to regenerate description:', error);
    } finally {
      setLoading(false);
    }
  };

  // ── verify.yaml 查看与编辑（项目级文件）──
  const [yamlDraft, setYamlDraft] = useState<string>('');
  const [yamlExists, setYamlExists] = useState<boolean>(false);
  const [yamlLoading, setYamlLoading] = useState(false);
  const [yamlSaving, setYamlSaving] = useState(false);
  const [autodraftLoading, setAutodraftLoading] = useState(false);
  // fix-verify-contract-signal-semantics D3：同步防重入锁——setAutodraftLoading 的
  // loading 渲染生效存在 React 调度间隙（实证 100ms 内双击穿透），useRef 写读同帧
  // 原子、无渲染依赖，在途期间重复触发直接 return 不发网络请求。
  const autodraftInFlight = useRef(false);
  // 过期响应守卫：每次发起加载自增序号，响应回来时序号已不是最新（期间切换了
  // 项目或发起了新加载）则丢弃——防止慢响应乱序把旧项目的契约内容写进当前
  // 项目草稿，进而被「保存 verify.yaml」以当前项目名写盘造成跨项目覆盖。
  const yamlLoadSeq = useRef(0);

  const loadVerifyYaml = async (silent = false) => {
    const seq = ++yamlLoadSeq.current;
    if (!project) return;
    if (!silent) setYamlLoading(true);
    try {
      const d = await getVerifyYaml(project);
      if (seq !== yamlLoadSeq.current) return; // 过期响应：丢弃，不回写草稿
      setYamlDraft(d.content);
      setYamlExists(d.exists);
    } catch (e) {
      if (seq !== yamlLoadSeq.current) return; // 过期请求的失败也不打扰当前项目
      console.error('Failed to load verify.yaml:', e);
      message.error(`加载 verify.yaml 失败：${e instanceof Error ? e.message : e}`);
    } finally {
      if (!silent && seq === yamlLoadSeq.current) setYamlLoading(false);
    }
  };

  useEffect(() => {
    loadVerifyYaml();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  const handleYamlSave = async () => {
    if (!project) return;
    setYamlSaving(true);
    try {
      await saveVerifyYaml(project, yamlDraft);
      message.success('verify.yaml 已保存');
      setYamlExists(true);
      await loadVerifyYaml(true);
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save verify.yaml:', e);
    } finally {
      setYamlSaving(false);
    }
  };

  const handleInsertTemplate = async () => {
    try {
      const d = await getVerifyYamlTemplate();
      setYamlDraft(d.template);
      message.info('已插入契约模板：按项目实际取消注释并修改，保存后下一轮验证生效');
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`模板加载失败：${errorMessage}`);
      console.error('Failed to load verify.yaml template:', e);
    }
  };

  const handleAutodraft = async (overwrite: boolean) => {
    if (!project) return;
    if (autodraftInFlight.current) return; // 竞态窗口内重复触发：同步锁拦截
    autodraftInFlight.current = true;
    setAutodraftLoading(true);
    try {
      const result = await autodraftVerifyYaml(project, overwrite);
      if (result.ok) {
        if (result.status === 'dispatched') {
          message.success(result.message);
        } else {
          message.info(result.message);
        }
      } else {
        message.error(result.message || '自动起草失败');
      }
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`自动起草失败：${errorMessage}`);
      console.error('Failed to autodraft verify.yaml:', e);
    } finally {
      setAutodraftLoading(false);
      autodraftInFlight.current = false;
    }
  };

  return (
    <div>
      <h3>项目：{project}</h3>
      <Text type="secondary">项目级的具体设置信息。</Text>
      <Card style={{ marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>项目简介</h3>
        <Text type="secondary">
          项目简介将展示在概览页项目卡片和项目列表页，帮助快速了解项目用途。
        </Text>
        <TextArea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="暂无简介"
          autoSize={{ minRows: 4, maxRows: 8 }}
          style={{ marginTop: 12, marginBottom: 16 }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Button onClick={handleRegenerate} loading={loading}>
            AI 自动生成
          </Button>
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </div>
      </Card>

      {/* verify.yaml 为项目级文件：验证契约查看与编辑 */}
      {project ? (
        <div ref={verifySectionRef}>
        <Card style={{ marginTop: 16 }} data-testid="verify-yaml-section">
          <h3 style={{ marginTop: 0 }}>验证契约（verify.yaml）</h3>
          <Text type="secondary">
            项目 <code>.fenix/verify.yaml</code> 声明应用如何构建（prepare）、如何被服务
            （serve）、何时算就绪（ready）。保存时做 YAML 语法校验；生效于下一轮验证。
            本文件随仓库提交，保存后建议尽快 commit（daemon 派发 agent 前会 stash
            未提交修改）。
          </Text>
          {!yamlExists && !yamlLoading && (
            <Alert
              style={{ marginTop: 8 }}
              type="info"
              showIcon
              message="尚无 verify.yaml（无契约时框架回退旧行为），可插入模板后按项目修改保存。"
              data-testid="verify-yaml-missing-alert"
            />
          )}
          <TextArea
            ref={yamlTextareaRef}
            data-testid="verify-yaml-textarea"
            value={yamlDraft}
            onChange={(e) => setYamlDraft(e.target.value)}
            disabled={yamlLoading}
            placeholder={'# 全注释 = 无契约。可点击「插入模板」开始配置。'}
            autoSize={{ minRows: 12, maxRows: 28 }}
            style={{ marginTop: 12, fontFamily: 'monospace' }}
          />
          <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between' }}>
            <div>
              {yamlDraft.trim() ? (
                <Popconfirm
                  title="当前编辑内容将被模板覆盖"
                  description="未保存的修改会丢失，确定继续？"
                  okText="覆盖"
                  cancelText="取消"
                  onConfirm={handleInsertTemplate}
                >
                  <Button data-testid="verify-yaml-template">插入模板</Button>
                </Popconfirm>
              ) : (
                <Button onClick={handleInsertTemplate} data-testid="verify-yaml-template">
                  插入模板
                </Button>
              )}
              {/* AI 自动生成按钮 */}
              {!yamlExists && !yamlLoading ? (
                <Popconfirm
                  title="AI 起草验证契约"
                  description="将探索项目 → 生成契约 → 三段自证 → 提交仓库，约数分钟"
                  okText="确认起草"
                  cancelText="取消"
                  onConfirm={() => handleAutodraft(false)}
                >
                  <Button
                    style={{ marginLeft: 8 }}
                    loading={autodraftLoading}
                    data-testid="verify-yaml-autodraft"
                  >
                    AI 自动生成
                  </Button>
                </Popconfirm>
              ) : yamlExists ? (
                <Popconfirm
                  title="⚠️ 覆盖现有契约"
                  description="现有验证契约将被覆盖，未保存的编辑也会丢失。确定继续？"
                  okText="确认覆盖"
                  cancelText="取消"
                  onConfirm={() => handleAutodraft(true)}
                >
                  <Button
                    style={{ marginLeft: 8 }}
                    loading={autodraftLoading}
                    data-testid="verify-yaml-autodraft"
                  >
                    AI 自动生成
                  </Button>
                </Popconfirm>
              ) : null}
              <Button
                style={{ marginLeft: 8 }}
                onClick={() => loadVerifyYaml()}
                data-testid="verify-yaml-reload"
              >
                重新加载
              </Button>
            </div>
            <Button
              type="primary"
              loading={yamlSaving}
              onClick={handleYamlSave}
              data-testid="verify-yaml-save"
            >
              保存 verify.yaml
            </Button>
          </div>
        </Card>
        </div>
      ) : (
        <Card style={{ marginTop: 16 }}>
          <Text type="secondary">
            验证契约为项目级文件（<code>.fenix/verify.yaml</code>）。查看与编辑请切换到项目级作用域。
          </Text>
        </Card>
      )}
    </div>
  );
}
