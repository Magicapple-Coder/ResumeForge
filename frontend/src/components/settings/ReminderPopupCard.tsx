/**
 * 提醒弹窗开关：打开应用时若有未完成提醒，是否弹窗列出。
 *
 * 卡片自带取数与保存（与 SearchCard / UpdateCard 一致）：它是一套独立设置，不走「编辑设置」
 * 那个全局编辑态。开关即改即存，不设单独的保存按钮。
 */

import { App, Card, Space, Spin, Switch, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { getReminderPopupSetting, saveReminderPopupSetting } from "../../api/settings";

export default function ReminderPopupCard() {
  const { message } = App.useApp();
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setEnabled((await getReminderPopupSetting()).enabled);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载提醒弹窗设置失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (checked: boolean) => {
    if (saving) return;
    setSaving(true);
    setEnabled(checked);
    try {
      const saved = await saveReminderPopupSetting(checked);
      setEnabled(saved.enabled);
      message.success(
        saved.enabled ? "已开启：打开应用时弹出近期提醒" : "已关闭：打开应用时不再弹出提醒",
      );
    } catch (err) {
      // 保存失败回滚到切换前的状态。
      setEnabled(!checked);
      message.error(err instanceof Error ? err.message : "保存提醒弹窗设置失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="提醒弹窗" className="settings-card">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        打开应用时，若还有未完成的日历提醒，是否弹出「近期提醒」列表。
      </Typography.Paragraph>
      <Spin spinning={loading}>
        <Space direction="vertical" size={4}>
          <Switch
            checked={enabled}
            loading={saving}
            checkedChildren="开"
            unCheckedChildren="关"
            aria-label="打开应用时弹出提醒"
            onChange={(checked) => void toggle(checked)}
          />
          <Typography.Text type="secondary">默认开启，可随时在这里关闭。</Typography.Text>
        </Space>
      </Spin>
    </Card>
  );
}
