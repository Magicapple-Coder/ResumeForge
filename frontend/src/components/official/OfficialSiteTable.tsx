import { CloudDownloadOutlined, EditOutlined, ReloadOutlined } from "@ant-design/icons";
import { Empty, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import type { OfficialSite } from "../../types";
import { VERDICT_COLORS } from "../../types";
import { RowActions } from "../common/RowActions";

const { Text } = Typography;

interface Props {
  sites: OfficialSite[];
  loading: boolean;
  busySiteIds: number[];
  submitting: boolean;
  selectedSiteIds: number[];
  onSelectedSiteIdsChange: (ids: number[]) => void;
  onEdit: (site: OfficialSite) => void;
  onCollect: (site: OfficialSite) => void;
  onProbe: (site: OfficialSite) => void;
  onDelete: (site: OfficialSite) => void;
  onOpenReport: (runId: number) => void;
}

function robotsTag(site: OfficialSite) {
  if (site.robots_allowed === null) return <Tag>未检查</Tag>;
  if (site.robots_allowed) {
    return (
      <Tooltip title={site.robots_detail}>
        <Tag color="success">允许</Tag>
      </Tooltip>
    );
  }
  return (
    <Tooltip title={site.robots_detail}>
      <Tag color="error">不允许</Tag>
    </Tooltip>
  );
}

export default function OfficialSiteTable({
  sites,
  loading,
  busySiteIds,
  submitting,
  selectedSiteIds,
  onSelectedSiteIdsChange,
  onEdit,
  onCollect,
  onProbe,
  onDelete,
  onOpenReport,
}: Props) {
  const rowSelection: TableRowSelection<OfficialSite> = {
    selectedRowKeys: selectedSiteIds,
    onChange: (keys) => onSelectedSiteIdsChange(keys.map(Number)),
    getCheckboxProps: (site) => ({
      disabled:
        !site.can_collect ||
        site.latest_status === "running" ||
        busySiteIds.length > 0 ||
        submitting,
    }),
  };

  const columns: ColumnsType<OfficialSite> = [
    {
      title: "公司",
      dataIndex: "company",
      render: (_value, site) => (
        <Space direction="vertical" size={0}>
          <Text strong>{site.company}</Text>
          {site.careers_url && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {site.careers_url}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: "识别结果",
      dataIndex: "source_label",
      render: (_value, site) =>
        site.source_kind ? (
          <Tooltip title={site.probe_evidence}>
            <Space direction="vertical" size={0}>
              <Tag color="blue">{site.source_label}</Tag>
              {site.confidence_label && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {site.confidence_label}
                </Text>
              )}
            </Space>
          </Tooltip>
        ) : (
          <Tooltip title={site.probe_evidence}>
            <Tag>未识别</Tag>
          </Tooltip>
        ),
    },
    { title: "站点许可", dataIndex: "robots_allowed", render: (_v, site) => robotsTag(site) },
    {
      title: "最近一次采集",
      dataIndex: "latest_verdict_label",
      render: (_value, site) =>
        site.latest_status === "running" ? (
          <Tag color="processing">采集中</Tag>
        ) : site.latest_run_id ? (
          <Typography.Link onClick={() => onOpenReport(site.latest_run_id as number)}>
            <Space direction="vertical" size={0}>
              <Tag color={VERDICT_COLORS[site.latest_verdict] || "default"}>
                {site.latest_verdict_label || site.latest_status_label}
              </Tag>
              {site.latest_headline && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {site.latest_headline}
                </Text>
              )}
            </Space>
          </Typography.Link>
        ) : (
          <Text type="secondary">还没采过</Text>
        ),
    },
    {
      title: "操作",
      key: "actions",
      width: 260,
      render: (_value, site) => (
        <Space size={4}>
          <Tooltip title={site.can_collect ? "" : "需要先识别出招聘系统，且站点允许采集"}>
            <RowActions
              disabled={busySiteIds.length > 0 || submitting}
              primary={[
                {
                  key: "collect",
                  label: "采集",
                  icon: <CloudDownloadOutlined />,
                  disabled: !site.can_collect || site.latest_status === "running",
                  onClick: () => onCollect(site),
                },
              ]}
              more={[
                { key: "edit", label: "编辑", icon: <EditOutlined />, onClick: () => onEdit(site) },
                {
                  key: "probe",
                  label: "重新探测",
                  icon: <ReloadOutlined />,
                  disabled: busySiteIds.length > 0,
                  onClick: () => onProbe(site),
                },
                {
                  key: "delete",
                  label: "删除",
                  danger: true,
                  confirm: `删除「${site.company}」？`,
                  onClick: () => onDelete(site),
                },
              ]}
            />
          </Tooltip>
          {busySiteIds.includes(site.id) && <Text type="secondary">处理中…</Text>}
        </Space>
      ),
    },
  ];

  return (
    <Table<OfficialSite>
      className="official-selection-table"
      rowKey="id"
      columns={columns}
      dataSource={sites}
      rowSelection={rowSelection}
      loading={loading}
      pagination={false}
      locale={{
        emptyText: (
          <Empty
            description={
              <Space direction="vertical" size={2}>
                <Text>还没有添加公司</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  点右上角「添加公司」，填入官网地址即可
                </Text>
              </Space>
            }
          />
        ),
      }}
    />
  );
}
