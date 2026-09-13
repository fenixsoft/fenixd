import { Alert, Button, Card, Form, Input, Switch, Tabs, TimePicker, Typography, message } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { getTodo, saveTodo } from '@/services/dashboard';
import type { ConfigData } from '@/services/dashboard';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';

const { Text } = Typography;
const { TextArea } = Input;

// 自省 run_at 缺省与后端 ConfigLoader.SELF_REVIEW_DEFAULT_RUN_AT 一致（凌晨两点）
const DEFAULT_RUN_AT = '02:00';

interface SelfReviewPanelProps {
  config: ConfigData;
  /** 返回保存是否成功：false 时不再连带提交 todo.md（配置失败不连带覆写） */
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  /** 项目名；undefined = 用户级作用域（todo.md 为项目级文件，不显示编辑区） */
  project?: string;
}

export default function SelfReviewPanel({ config, onSave, project }: SelfReviewPanelProps) {
  const [form] = Form.useForm();
  const selfReview = config.self_review;

  // ── todo.md 草稿状态：保存并入本页签右下角主保存按钮
  //    （2026-09-07 用户决策：移除独立的重新加载/保存 todo 按钮）；
  //    project 变化（作用域切换）时重新加载磁盘内容 ──
  const [todoDraft, setTodoDraft] = useState('');
  const [todoExists, setTodoExists] = useState(false);
  const [todoLoading, setTodoLoading] = useState(false);

  // todo.md 视图页签：预览在前且为默认（先看渲染效果，需要改动再切编辑）；
  // 切换纯前端状态，两页签共享草稿无损
  const [todoView, setTodoView] = useState<'edit' | 'preview'>('preview');

  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    const load = async () => {
      setTodoLoading(true);
      try {
        const d = await getTodo(project);
        if (!cancelled) {
          setTodoDraft(d.content);
          setTodoExists(d.exists);
        }
      } catch (e) {
        console.error('Failed to load todo.md:', e);
        if (!cancelled) {
          message.error(`加载 todo.md 失败：${e instanceof Error ? e.message : e}`);
        }
      } finally {
        if (!cancelled) setTodoLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [project]);

  // 自省字段（self_review.*）：TimePicker 值为 dayjs 对象（结构性保证
  // HH:mm 合法），保存时转回字符串
  const initialValues = {
    enabled: selfReview?.enabled ?? false,
    run_at: dayjs(selfReview?.run_at ?? DEFAULT_RUN_AT, 'HH:mm'),
    read_todo: selfReview?.read_todo ?? false,
  };

  useEffect(() => {
    form.setFieldsValue(initialValues);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.self_review, form]);

  const handleSave = async () => {
    let ok = false;
    try {
      const values = await form.validateFields();
      ok = await onSave({
        self_review: {
          enabled: values.enabled,
          run_at: values.run_at.format('HH:mm'),
          read_todo: values.read_todo,
        },
      });
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示
      return;
    }
    // 配置保存成功后连调 /api/todo 保存 todo.md（同一「保存」动作的两段提交；
    // 配置失败不连带覆写 todo.md）。成功后回读磁盘，兼作原「重新加载」语义
    if (!project || !ok) return;
    try {
      await saveTodo(project, todoDraft);
      const d = await getTodo(project);
      setTodoDraft(d.content);
      setTodoExists(d.exists);
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`todo.md 保存失败：${errorMessage}`);
      console.error('Failed to save todo.md:', e);
    }
  };

  return (
    <div data-testid="self-review-panel">
      <Form form={form} initialValues={initialValues} layout="vertical">
        <h3>自省</h3>
        <Text type="secondary">
          Fenix Daemon 每晚在指定时间由 Administrator Agent 自动执行工作回顾（浪费 /
          失误 / 可改进，回顾窗口为执行前 24 小时），结果追加写入项目根 todo.md 并自动提交。
        </Text>
        <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="enabled" valuePropName="checked" noStyle>
              <Switch data-testid="self-review-control-enabled" />
            </Form.Item>
            <span className="switch-inline-label">
              启用每日自省<span className="label-note">（admin.self_review.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            缺省关闭。开启后于每日 run_at 后触发（距上次执行不足 24 小时则顺延至下个巡检周期）。
          </Text>

          <Form.Item
            name="run_at"
            label={
              <>
                每日执行时间<span className="label-note">（admin.self_review.run_at，HH:MM）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[{ required: true, message: '请选择执行时间' }]}
            data-testid="self-review-field-run_at"
          >
            <TimePicker format="HH:mm" allowClear={false} style={{ width: 160 }} />
          </Form.Item>
          <Text type="secondary">
            缺省 02:00。实际触发时刻为 run_at 后的第一个巡检周期；回顾数据窗口为执行前 24 小时。
          </Text>

          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="read_todo" valuePropName="checked" noStyle>
              <Switch data-testid="self-review-control-read_todo" />
            </Form.Item>
            <span className="switch-inline-label">
              注入既有 todo.md 上下文<span className="label-note">（admin.self_review.read_todo）</span>
            </span>
          </div>
          <Text type="secondary">
            开启时把项目根 todo.md 全文注入自省 prompt，供 Agent 识别历史条目、
            避免重复并标注已闭环项。缺省关闭。
          </Text>
        </Card>

        {/* todo.md 为项目级文件：仅项目级作用域提供查看与编辑 */}
        {project ? (
          <Card style={{ marginTop: 16 }} data-testid="todo-section">
            <h3 style={{ marginTop: 0 }}>todo.md</h3>
            <Text type="secondary">
              自省 Agent 每晚追加写入工作回顾。编辑后经本页签右下角「保存」按钮与自省设置一并保存（整文件覆写）；
              注意与 daemon 夜间追加的时序。
            </Text>
            {!todoExists && !todoLoading && (
              <Alert
                style={{ marginTop: 8 }}
                type="info"
                showIcon
                message="尚无 todo.md（自省首次运行后生成），可保存以下内容提前创建。"
                data-testid="todo-missing-alert"
              />
            )}
            <Tabs
              type="card"
              className="todo-md-tabs"
              activeKey={todoView}
              onChange={(k) => setTodoView(k as 'edit' | 'preview')}
              style={{ marginTop: 12 }}
              items={[
                {
                  key: 'preview',
                  label: '预览',
                  children: (
                    <div
                      data-testid="todo-preview"
                      style={{
                        minHeight: 120, maxHeight: 600, overflow: 'auto',
                        background: '#fff', border: '1px solid #f0f0f0',
                        borderTop: 0, borderRadius: 0, padding: 12,
                      }}
                    >
                      {todoDraft ? (
                        <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={markdownComponents}>
                          {todoDraft}
                        </Markdown>
                      ) : (
                        <Text type="secondary">暂无内容——切到「编辑」页签写入后此处实时渲染。</Text>
                      )}
                    </div>
                  ),
                },
                {
                  key: 'edit',
                  label: '编辑',
                  children: (
                    <TextArea
                      data-testid="todo-textarea"
                      value={todoDraft}
                      onChange={(e) => setTodoDraft(e.target.value)}
                      disabled={todoLoading}
                      placeholder={'## 2026-09-04\n\n### 可改进\n- 证据：……'}
                      autoSize={{ minRows: 10, maxRows: 24 }}
                      style={{
                        fontFamily: 'monospace', borderTop: 0, borderRadius: 0,
                        // 边框颜色钉死与预览容器一致：内联样式压制 antd 默认深灰
                        // 与 hover/focus 态的蓝色边框；焦点外发光一并压掉
                        borderColor: '#f0f0f0', boxShadow: 'none',
                      }}
                    />
                  ),
                },
              ]}
            />
          </Card>
        ) : (
          <Card style={{ marginTop: 16 }}>
            <Text type="secondary">
              todo.md 为项目级文件（<code>.fenix/todo.md</code>）。查看与编辑请切换到项目级作用域。
            </Text>
          </Card>
        )}
      </Form>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave} data-testid="self-review-save-btn">
          保存
        </Button>
      </div>
    </div>
  );
}
