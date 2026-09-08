import { Alert, Card, Form, Input, Switch, Tabs, TimePicker, Typography } from 'antd';
import { useState } from 'react';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';

const { Text } = Typography;
const { TextArea } = Input;

interface SelfReviewPanelProps {
  /** 项目名；undefined = 用户级作用域（todo.md 为项目级文件，不显示编辑区） */
  project?: string;
  /** todo.md 草稿与状态由 SystemPanel 持有：保存并入页面右下角主保存按钮
      （2026-09-07 用户决策：移除独立的重新加载/保存 todo 按钮），加载后经
      主保存一并提交并回读磁盘 */
  todoDraft: string;
  todoExists: boolean;
  todoLoading: boolean;
  onTodoDraftChange: (value: string) => void;
}

// 自省设置区块：并入系统页签后不再持有独立 Form——字段经 antd context 挂到
// SystemPanel 的表单（name 嵌套于 self_review 段，避免与 admin.enabled 重名），
// 保存由系统页签底部按钮统一提交
export default function SelfReviewPanel({
  project, todoDraft, todoExists, todoLoading, onTodoDraftChange,
}: SelfReviewPanelProps) {
  // todo.md 视图页签：预览在前且为默认（先看渲染效果，需要改动再切编辑）；
  // 切换纯前端状态，草稿由 SystemPanel 持有，两页签共享无损
  const [todoView, setTodoView] = useState<'edit' | 'preview'>('preview');

  return (
    <div style={{ marginTop: 32 }}>
      <h3>自省</h3>
      <Text type="secondary">
        Fenix Daemon 每晚在指定时间由 Administrator Agent 自动执行工作回顾（浪费 /
        失误 / 可改进，回顾窗口为执行前 24 小时），结果追加写入项目根 todo.md 并自动提交。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <div className="switch-inline-row">
          <Form.Item name={['self_review', 'enabled']} valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
          <span className="switch-inline-label">
            启用每日自省<span className="label-note">（admin.self_review.enabled）</span>
          </span>
        </div>
        <Text type="secondary">
          缺省关闭。开启后于每日 run_at 后触发（距上次执行不足 24 小时则顺延至下个巡检周期）。
        </Text>

        <Form.Item
          name={['self_review', 'run_at']}
          label={
            <>
              每日执行时间<span className="label-note">（admin.self_review.run_at，HH:MM）</span>
            </>
          }
          style={{ marginTop: 24 }}
          rules={[{ required: true, message: '请选择执行时间' }]}
        >
          <TimePicker format="HH:mm" allowClear={false} style={{ width: 160 }} />
        </Form.Item>
        <Text type="secondary">
          缺省 02:00。实际触发时刻为 run_at 后的第一个巡检周期；回顾数据窗口为执行前 24 小时。
        </Text>

        <div className="switch-inline-row" style={{ marginTop: 24 }}>
          <Form.Item name={['self_review', 'read_todo']} valuePropName="checked" noStyle>
            <Switch />
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
            项目 <code>.fenix/todo.md</code>——自省 Agent 每晚追加写入工作回顾。
            编辑后经页面右下角「保存」按钮与系统设置一并保存（整文件覆写）；
            注意与 daemon 夜间追加的时序（建议日间编辑）。
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
                    onChange={(e) => onTodoDraftChange(e.target.value)}
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
    </div>
  );
}
