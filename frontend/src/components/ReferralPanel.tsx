/** 内推管理（R-13）：内推列表、增删改 + 顶部转化率小卡 + 内推码/图片备注/状态分色。
 *
 * ``converted`` 由后端按关联漏斗后置位派生，前端只展示、不自己算口径。顶部转化率卡展示
 * 有效内推总数、已转化数与转化率。备注图片先上传拿相对路径，再随表单写入 ``note_images``。
 */
import {
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import {
  createReferral,
  deleteReferral,
  getReferralStats,
  listReferrals,
  updateReferral,
  uploadReferralImage,
} from "../api/referrals";
import { REFERRAL_STATUS_COLORS, REFERRAL_STATUS_LABELS, referralImageUrl } from "../types";
import type { Referral, ReferralPayload, ReferralStats, ReferralStatus } from "../types";
import { classifyAttachment, IMAGE_ACCEPT, MAX_ATTACHMENT_BYTES } from "../utils/attachments";

/** 与后端 ``schemas/referral.MAX_NOTE_IMAGES`` 保持一致。 */
const MAX_NOTE_IMAGES = 9;

interface Option {
  value: number;
  label: string;
}

interface Props {
  jobOptions?: Option[];
  trackOptions?: Option[];
}

export default function ReferralPanel({ jobOptions = [], trackOptions = [] }: Props) {
  const { message } = App.useApp();
  const [items, setItems] = useState<Referral[]>([]);
  const [stats, setStats] = useState<ReferralStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string | undefined>();
  const [keyword, setKeyword] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Referral | null>(null);
  const [saving, setSaving] = useState(false);
  const [uploadingImages, setUploadingImages] = useState(false);
  const [noteImages, setNoteImages] = useState<string[]>([]);
  const [form] = Form.useForm<ReferralPayload>();

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listReferrals({ status: status || undefined, keyword: keyword.trim() }));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取内推失败");
    } finally {
      setLoading(false);
    }
  }, [status, keyword, message]);

  const loadStats = useCallback(async () => {
    try {
      setStats(await getReferralStats());
    } catch {
      /* 统计卡失败不打断列表，静默即可 */
    }
  }, []);

  useEffect(() => {
    void loadList();
    void loadStats();
  }, [loadList, loadStats]);

  const openCreate = () => {
    setEditing(null);
    setNoteImages([]);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (item: Referral) => {
    setEditing(item);
    setNoteImages(item.note_images ?? []);
    form.setFieldsValue({
      company: item.company,
      position: item.position,
      job_title: item.job_title,
      referrer_name: item.referrer_name,
      referrer_contact: item.referrer_contact,
      relation: item.relation,
      channel: item.channel,
      status: item.status as ReferralStatus,
      job_id: item.job_id ?? undefined,
      track_id: item.track_id ?? undefined,
      submitted_at: item.submitted_at,
      note: item.note,
      referral_code: item.referral_code,
    });
    setModalOpen(true);
  };

  const removeImage = (path: string) => {
    setNoteImages((prev) => prev.filter((item) => item !== path));
  };

  const beforeImageUpload = async (file: File) => {
    const classified = classifyAttachment(file);
    if (!classified || classified.kind !== "image") {
      message.error("只能上传 png/jpg/webp/gif/bmp/tiff 图片");
      return Upload.LIST_IGNORE;
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
      message.error("单张图片不能超过 2 MB");
      return Upload.LIST_IGNORE;
    }
    if (noteImages.length >= MAX_NOTE_IMAGES) {
      message.error(`最多上传 ${MAX_NOTE_IMAGES} 张备注图片`);
      return Upload.LIST_IGNORE;
    }
    setUploadingImages(true);
    try {
      const { path } = await uploadReferralImage(file);
      setNoteImages((prev) => [...prev, path]);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "上传图片失败");
    } finally {
      setUploadingImages(false);
    }
    // 阻止 antd 的默认上传：文件已由 uploadReferralImage 落盘。
    return Upload.LIST_IGNORE;
  };

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    const payload: ReferralPayload = {
      ...values,
      job_id: values.job_id ?? null,
      track_id: values.track_id ?? null,
      referral_code: values.referral_code ?? "",
      note_images: noteImages,
    };
    try {
      if (editing) await updateReferral(editing.id, payload);
      else await createReferral(payload);
      message.success(editing ? "已更新内推" : "已新增内推");
      setModalOpen(false);
      await loadList();
      await loadStats();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存内推失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item: Referral) => {
    try {
      await deleteReferral(item.id);
      message.success("已删除");
      await loadList();
      await loadStats();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const convertedRate = stats?.total ? Math.round((stats.rate ?? 0) * 100) : 0;

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card size="small" title="内推转化率">
        <Row gutter={16}>
          <Col span={8}>
            <Statistic title="有效内推" value={stats?.total ?? 0} />
          </Col>
          <Col span={8}>
            <Statistic title="已转化" value={stats?.converted ?? 0} />
          </Col>
          <Col span={8}>
            <Statistic
              title="转化率"
              value={convertedRate}
              suffix="%"
              valueStyle={{ color: convertedRate >= 50 ? "#389e0d" : undefined }}
            />
          </Col>
        </Row>
      </Card>

      <Card size="small" title="内推记录">
        <Space wrap>
          <Input.Search
            allowClear
            placeholder="搜索公司 / 岗位 / 内推人"
            style={{ width: 240 }}
            onSearch={(value) => setKeyword(value)}
          />
          <Select
            allowClear
            placeholder="状态筛选"
            style={{ minWidth: 140 }}
            value={status}
            onChange={setStatus}
            options={REFERRAL_STATUS_LABELS_OPTIONS()}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增内推
          </Button>
        </Space>
      </Card>

      {loading ? (
        <Spin />
      ) : items.length === 0 ? (
        <Empty description="还没有内推记录，把找人内推的机会记下来吧" />
      ) : (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Tooltip key="edit" title="编辑">
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    aria-label={`编辑内推 ${item.referrer_name || item.position}`}
                    onClick={() => openEdit(item)}
                  />
                </Tooltip>,
                <Popconfirm
                  key="delete"
                  title="删除这条内推？"
                  description="删除后可在回收站里找回，不会立刻彻底删除。"
                  okText="删除"
                  okButtonProps={{
                    danger: true,
                    "aria-label": `确认删除内推 ${item.referrer_name || item.position}`,
                  }}
                  cancelText="取消"
                  cancelButtonProps={{
                    "aria-label": `取消删除内推 ${item.referrer_name || item.position}`,
                  }}
                  onConfirm={() => void remove(item)}
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    aria-label={`删除内推 ${item.referrer_name || item.position}`}
                  />
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={6} wrap>
                    <span>
                      {item.referrer_name || "未记内推人"}
                      {item.position ? ` · ${item.position}` : ""}
                    </span>
                    <Tag color={REFERRAL_STATUS_COLORS[item.status as ReferralStatus] ?? "default"}>
                      {REFERRAL_STATUS_LABELS[item.status as ReferralStatus] ?? item.status}
                    </Tag>
                    {item.converted && <Tag color="green">已转化</Tag>}
                  </Space>
                }
                description={
                  <Space direction="vertical" size={2} style={{ width: "100%" }}>
                    <Typography.Text type="secondary">
                      {item.company}
                      {item.relation ? ` · ${item.relation}` : ""}
                      {item.channel ? ` · ${item.channel}` : ""}
                    </Typography.Text>
                    {item.referral_code && (
                      <Typography.Text type="secondary">
                        内推码：{item.referral_code}
                      </Typography.Text>
                    )}
                    {item.note && <Typography.Text type="secondary">{item.note}</Typography.Text>}
                    {(item.note_images ?? []).length > 0 && (
                      <Space size={4} wrap>
                        {(item.note_images ?? []).map((path) => (
                          <img
                            key={path}
                            src={referralImageUrl(path)}
                            alt="备注图"
                            style={{ width: 32, height: 32, objectFit: "cover", borderRadius: 3 }}
                          />
                        ))}
                      </Space>
                    )}
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}

      <Modal
        title={editing ? "编辑内推" : "新增内推"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void save()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{ status: "active" }}>
          <Space style={{ display: "flex" }} align="start">
            <Form.Item label="公司" name="company" style={{ flex: 1 }}>
              <Input maxLength={128} placeholder="公司名" />
            </Form.Item>
            <Form.Item label="内推岗位" name="position" style={{ flex: 1 }}>
              <Input maxLength={128} placeholder="岗位名" />
            </Form.Item>
          </Space>
          <Form.Item label="内推人" name="referrer_name">
            <Input maxLength={128} placeholder="姓名 / 称呼" />
          </Form.Item>
          <Space style={{ display: "flex" }} align="start">
            <Form.Item label="联系方式" name="referrer_contact" style={{ flex: 1 }}>
              <Input maxLength={128} placeholder="微信 / 邮箱等" />
            </Form.Item>
            <Form.Item label="关系" name="relation" style={{ flex: 1 }}>
              <Input maxLength={64} placeholder="朋友 / 前同事 / 网友…" />
            </Form.Item>
          </Space>
          <Space style={{ display: "flex" }} align="start">
            <Form.Item label="渠道" name="channel" style={{ flex: 1 }}>
              <Input maxLength={32} placeholder="牛客 / 脉脉 / 熟人直递…" />
            </Form.Item>
            <Form.Item label="内推码" name="referral_code" style={{ flex: 1 }}>
              <Input maxLength={64} placeholder="官网内推码（选填）" />
            </Form.Item>
          </Space>
          <Form.Item label="状态" name="status">
            <Select
              options={REFERRAL_STATUS_LABELS_OPTIONS()}
            />
          </Form.Item>
          <Form.Item label="关联岗位（选填，删除岗位不影响内推）" name="job_id">
            <Select allowClear showSearch optionFilterProp="label" options={jobOptions} />
          </Form.Item>
          <Form.Item label="转化关联漏斗（选填，进入面试及以上即视为转化）" name="track_id">
            <Select allowClear showSearch optionFilterProp="label" options={trackOptions} />
          </Form.Item>
          <Form.Item label="投递日期" name="submitted_at" extra="YYYY-MM-DD，留空表示未知">
            <Input maxLength={10} placeholder="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item label="图片备注（选填，最多 9 张）">
            <Upload
              accept={IMAGE_ACCEPT}
              multiple
              showUploadList={false}
              beforeUpload={beforeImageUpload}
              disabled={uploadingImages}
            >
              <Button
                icon={<UploadOutlined />}
                loading={uploadingImages}
                disabled={noteImages.length >= MAX_NOTE_IMAGES}
              >
                上传备注图
              </Button>
            </Upload>
            {noteImages.length > 0 && (
              <Space wrap size={4} style={{ marginTop: 8 }}>
                {noteImages.map((path, index) => (
                  <span
                    key={path}
                    style={{ position: "relative", display: "inline-block", lineHeight: 0 }}
                  >
                    <img
                      src={referralImageUrl(path)}
                      alt={`备注图 ${index + 1}`}
                      style={{ width: 56, height: 56, objectFit: "cover", borderRadius: 4 }}
                    />
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<CloseOutlined />}
                      aria-label={`移除备注图 ${index + 1}`}
                      style={{ position: "absolute", top: -10, right: -10 }}
                      onClick={() => removeImage(path)}
                    />
                  </span>
                ))}
              </Space>
            )}
          </Form.Item>
          <Form.Item label="备注" name="note">
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} placeholder="补充说明（选填）" />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

/** 状态选项：分色在列表 Tag 上体现，这里只给标签。 */
function REFERRAL_STATUS_LABELS_OPTIONS(): { value: ReferralStatus; label: string }[] {
  return (Object.keys(REFERRAL_STATUS_LABELS) as ReferralStatus[]).map((value) => ({
    value,
    label: REFERRAL_STATUS_LABELS[value],
  }));
}
