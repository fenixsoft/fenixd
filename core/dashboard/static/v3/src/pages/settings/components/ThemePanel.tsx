import { Card, Radio, Typography } from 'antd';
import { useState, useEffect } from 'react';

const { Text } = Typography;

interface ThemePanelProps {
  onThemeChange: (theme: 'light' | 'dark') => void;
}

export default function ThemePanel({ onThemeChange }: ThemePanelProps) {
  const [theme, setTheme] = useState<'light' | 'dark'>(
    (localStorage.getItem('fenix.theme') as 'light' | 'dark') || 'dark',
  );

  useEffect(() => {
    // 初始化时应用主题
    onThemeChange(theme);
  }, []);

  const handleThemeChange = (e: any) => {
    const newTheme = e.target.value as 'light' | 'dark';
    setTheme(newTheme);
    localStorage.setItem('fenix.theme', newTheme);
    onThemeChange(newTheme);
  };

  return (
    <div>
      <h3>界面风格</h3>
      <Card>
        <Radio.Group value={theme} onChange={handleThemeChange}>
          <Radio.Button value="light">亮色</Radio.Button>
          <Radio.Button value="dark">暗色</Radio.Button>
        </Radio.Group>
        <div style={{ marginTop: 16 }}>
          <Text type="secondary">
            选择后立即全站生效，并保存到浏览器本地存储。
          </Text>
        </div>
      </Card>
    </div>
  );
}