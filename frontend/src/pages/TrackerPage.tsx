/**
 * 求职进度：把投出去的岗位收到哪一步了集中在一页看。
 *
 * 页面的判断很少——状态怎么合并、这次识别会改变什么，全在后端算好随数据下发，
 * 前端只负责展示与把用户的选择送回去。漏斗条是纯 CSS 画的，没有引入图表库：
 * 这一页要表达的就是"每个阶段各有多少条"，用一个宽度成比例的横条已经说完了。
 */
import {
  DownloadOutlined,
  FunnelPlotOutlined,
  ImportOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Dropdown,
  Empty,
  Input,
  Select,
  Skeleton,
  Space,
  Statistic,
  Tooltip,
  Typography,
} from "antd";
import type { MenuProps } from "antd";
import { useMemo, useState } from "react";
import { deleteTrack, exportTracks, listTracks } from "../api/tracker";
import TrackCard from "../components/tracker/TrackCard";
import TrackFormModal from "../components/tracker/TrackFormModal";
import TrackImportModal from "../components/tracker/TrackImportModal";
import { useApi } from "../hooks/useApi";
import { downloadBlob } from "../utils/download";
import type { Track } from "../types";
import { FUNNEL_STATUSES, TRACK_STATUSES, TRACK_STATUS_LABELS } from "../types";

export default function TrackerPage() {
  const { message } = App.useApp();
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Track | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const { data, loading, error, reload } = useApi(
    () => listTracks({ status, keyword }),
    [status, keyword],
  );

  const items = useMemo(() => data?.items ?? [], [data]);
  const counts = data?.status_counts ?? {};
  // 漏斗条的宽度按"这条占最大那条的比例"算，这样条目少时也不会全是一小截。
  const funnelMax = Math.max(1, ...FUNNEL_STATUSES.map((key) => counts[key] ?? 0));

  const remove = async (track: Track) => {
    try {
      await deleteTrack(track.id);
      message.success("已删除");
      await reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const doExport = async (format: "csv" | "json") => {
    try {
      const { blob, filename } = await exportTracks(format, { status, keyword });
      downloadBlob(blob, filename);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出失败");
    }
  };

  const exportMenu: MenuProps["items"] = [
    { key: "csv", label: "导出 CSV（可直接用 Excel 打开）" },
    { key: "json", label: "导出 JSON" },
  ];

  return (
    <div className="tracker-page">
      <div className="tracker-page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            求职进度
          </Typography.Title>
          <Typography.Text type="secondary">
            一家公司一个岗位一条记录，随对方发来的通知往前推进。投递台投出去的岗位会自动记一条
            「已投递」，之后的进展把通知粘进来即可。
          </Typography.Text>
        </Space>
        <Space>
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
            从通知导入
          </Button>
          <Dropdown
            menu={{
              items: exportMenu,
              onClick: ({ key }) => void doExport(key as "csv" | "json"),
            }}
            disabled={items.length === 0}
          >
            <Button icon={<DownloadOutlined />}>导出</Button>
          </Dropdown>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            添加进度
          </Button>
        </Space>
      </div>

      <div className="tracker-summary">
        <Statistic title="总数" value={data?.total ?? 0} />
        <Statistic title="进行中" value={data?.active_count ?? 0} prefix={<FunnelPlotOutlined />} />
        <Statistic title="本月投递" value={data?.month_count ?? 0} />
        <Statistic title="Offer" value={data?.offer_count ?? 0} valueStyle={{ color: "#389e0d" }} />
        <Statistic title="已结束" value={data?.rejected_count ?? 0} />
      </div>

      {(data?.total ?? 0) > 0 && (
        <div className="tracker-funnel">
          {FUNNEL_STATUSES.map((key) => {
            const value = counts[key] ?? 0;
            return (
              <Tooltip key={key} title={`${TRACK_STATUS_LABELS[key]}：${value} 条`}>
                <button
                  type="button"
                  className={`tracker-funnel-step${status === key ? " is-selected" : ""}`}
                  onClick={() => setStatus(status === key ? "" : key)}
                >
                  <span className="tracker-funnel-label">{TRACK_STATUS_LABELS[key]}</span>
                  <span className="tracker-funnel-count">{value}</span>
                  {/* 计数为 0 时不画条：留一个 2px 的小疙瘩看着像渲染坏了。 */}
                  {value > 0 && (
                    <span
                      className="tracker-funnel-bar"
                      style={{ width: `${Math.round((value / funnelMax) * 100)}%` }}
                    />
                  )}
                </button>
              </Tooltip>
            );
          })}
        </div>
      )}

      <Space size={12} wrap className="tracker-filters">
        <Select
          value={status}
          onChange={setStatus}
          style={{ width: 160 }}
          options={[
            { value: "", label: "全部状态" },
            ...TRACK_STATUSES.map((value) => ({
              value,
              label: TRACK_STATUS_LABELS[value],
            })),
          ]}
        />
        <Input.Search
          allowClear
          placeholder="搜索公司、岗位、备注或下一步"
          style={{ width: 280 }}
          onSearch={setKeyword}
        />
      </Space>

      {loading && <Skeleton active paragraph={{ rows: 6 }} />}
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
      {!loading && !error && items.length === 0 && (
        <Empty
          description={
            keyword || status
              ? "没有符合条件的记录"
              : "还没有进度记录。投递台投出的岗位会自动出现在这里，也可以点「从通知导入」把邮箱里的进展整理进来。"
          }
        />
      )}

      <div className="tracker-list">
        {items.map((track) => (
          <TrackCard
            key={track.id}
            track={track}
            onEdit={() => {
              setEditing(track);
              setFormOpen(true);
            }}
            onDelete={() => void remove(track)}
          />
        ))}
      </div>

      <TrackFormModal
        open={formOpen}
        track={editing}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSaved={() => void reload()}
      />
      <TrackImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={() => void reload()}
      />
    </div>
  );
}
