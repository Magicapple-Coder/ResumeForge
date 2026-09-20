/**
 * 进度记录的新建 / 编辑表单。
 *
 * 日期字段用 AntD ``DatePicker``（E12）：值在表单里是 Dayjs，提交时再转回 ``YYYY-MM-DD``。
 * 公司和岗位是必填：进度要按这两项合并，缺一个就无从判断该并到哪一条上。
 */
import { SaveOutlined } from "@ant-design/icons";
import { App, Button, DatePicker, Form, Input, Modal, Select, Space } from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useEffect } from "react";
import { createTrack, updateTrack } from "../../api/tracker";
import type { Track, TrackPayload, TrackStatus } from "../../types";
import { TRACK_STATUSES, TRACK_STATUS_LABELS, emptyTrack } from "../../types";

const STATUS_OPTIONS = TRACK_STATUSES.map((value) => ({
  value,
  label: TRACK_STATUS_LABELS[value],
}));

interface FormValues {
  company: string;
  title: string;
  status: TrackStatus;
  stage_note: string;
  applied_at: Dayjs | null;
  status_date: Dayjs | null;
  next_action: string;
  next_action_date: Dayjs | null;
  note: string;
}

const EMPTY: FormValues = {
  company: "",
  title: "",
  status: "applied",
  stage_note: "",
  applied_at: null,
  status_date: null,
  next_action: "",
  next_action_date: null,
  note: "",
};

function toValues(track: Track): FormValues {
  return {
    company: track.company,
    title: track.title,
    status: track.status,
    stage_note: track.stage_note,
    applied_at: track.applied_at ? dayjs(track.applied_at) : null,
    status_date: track.status_date ? dayjs(track.status_date) : null,
    next_action: track.next_action,
    next_action_date: track.next_action_date ? dayjs(track.next_action_date) : null,
    note: track.note,
  };
}

function toPayload(values: FormValues, track: Track | null): TrackPayload {
  return {
    ...emptyTrack(),
    company: values.company.trim(),
    title: values.title.trim(),
    status: values.status,
    stage_note: values.stage_note.trim(),
    applied_at: values.applied_at ? values.applied_at.format("YYYY-MM-DD") : "",
    status_date: values.status_date ? values.status_date.format("YYYY-MM-DD") : "",
    next_action: values.next_action.trim(),
    next_action_date: values.next_action_date ? values.next_action_date.format("YYYY-MM-DD") : "",
    note: values.note.trim(),
    // 手编不碰证据与关联：那是识别/投递台留下的痕迹，不该因为改个状态就丢掉。
    evidence: track?.evidence ?? "",
    job_id: track?.job_id ?? null,
    resume_id: track?.resume_id ?? null,
  };
}

interface Props {
  open: boolean;
  track: Track | null;
  onClose: () => void;
  onSaved: (track: Track) => void;
}

export default function TrackFormModal({ open, track, onClose, onSaved }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const editing = track !== null;

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue(track ? toValues(track) : EMPTY);
  }, [open, track, form]);

  const submit = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return; // 校验失败时 antd 已在字段旁给出提示
    }
    const payload = toPayload(values, track);
    try {
      const saved = editing ? await updateTrack(track.id, payload) : await createTrack(payload);
      message.success(editing ? "已保存" : "已添加");
      onSaved(saved);
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  return (
    <Modal
      open={open}
      title={editing ? "编辑进度" : "添加进度"}
      onCancel={onClose}
      width={680}
      destroyOnClose
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={() => void submit()}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" initialValues={EMPTY}>
        {/* 用普通 flex 而不是 antd 的 Space：Space 会给每个子项再包一层，
            flex 宽度落不到真正的 flex 子项上。 */}
        <div className="track-form-row">
          <Form.Item
            name="company"
            label="公司"
            className="track-form-grow"
            rules={[{ required: true, message: "请填写公司名称" }]}
          >
            <Input placeholder="例如 示例科技" maxLength={128} />
          </Form.Item>
          <Form.Item
            name="title"
            label="岗位"
            className="track-form-grow"
            rules={[{ required: true, message: "请填写岗位名称" }]}
          >
            <Input placeholder="例如 后端开发实习生" maxLength={128} />
          </Form.Item>
        </div>

        <div className="track-form-row">
          <Form.Item name="status" label="当前状态" className="track-form-grow">
            <Select options={STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="stage_note"
            label="阶段说明"
            className="track-form-grow"
            extra="第几轮、什么形式，例如「二面」「HR 面」"
          >
            <Input maxLength={64} />
          </Form.Item>
        </div>

        <div className="track-form-row">
          <Form.Item
            name="applied_at"
            label="投递日期"
            className="track-form-grow"
            // 说清留空的代价。此前只写「YYYY-MM-DD」，留空是阻力最小的路径，而后果
            // （该记录不进投递趋势与周内分布）用户看不到——统计页那张空图就是这么来的。
            // **刻意不预填今天**：投递台的自动记录知道日期（刚投出去的就是今天），
            // 手工录入不知道（可能是三周后照着通知补录），预填会把记录钉在错误的月份上，
            // 在趋势图里造出一个从未发生过的尖峰。给一键填入，让用户自己确认。
            extra={
              <>
                留空表示日期不详——该记录不计入投递趋势与周内分布。
                <Button
                  type="link"
                  size="small"
                  onClick={() => form.setFieldValue("applied_at", dayjs())}
                >
                  填今天
                </Button>
              </>
            }
          >
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name="status_date"
            label="状态更新日期"
            className="track-form-grow"
            extra="通知上写的那天"
          >
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
        </div>

        <div className="track-form-row">
          <Form.Item name="next_action" label="下一步" className="track-form-grow">
            <Input placeholder="例如 确认面试时间" maxLength={255} />
          </Form.Item>
          <Form.Item
            name="next_action_date"
            label="截止日期"
            className="track-form-date"
            extra="过期会标红"
          >
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
        </div>

        <Form.Item name="note" label="备注">
          <Input.TextArea rows={3} maxLength={4000} showCount />
        </Form.Item>
      </Form>
    </Modal>
  );
}
