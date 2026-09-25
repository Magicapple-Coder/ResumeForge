import { SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Drawer, Space, Spin, Tag, Typography } from "antd";
import type { OfficialRunDetail } from "../../types";
import { VERDICT_COLORS } from "../../types";
import { formatDateTime } from "../../utils/format";

const { Text, Paragraph } = Typography;
const MAX_VISIBLE_CANDIDATES = 20;

const TREND_ALERT_TYPES: Record<string, "warning" | "info"> = {
  dropped: "warning",
  jumped: "warning",
  stable: "info",
  insufficient: "info",
  unmeasured: "info",
};

const VERIFY_COLORS: Record<string, string> = {
  live: "error",
  gone: "success",
  unknown: "default",
};

interface Props {
  report: OfficialRunDetail | null;
  reportLoading: boolean;
  stopping: boolean;
  verifying: boolean;
  onClose: () => void;
  onStop: () => Promise<void>;
  onVerify: () => Promise<void>;
  onOpenCandidates: (runId: number) => void;
}

/** 采集报告抽屉；只消费页面层传入的状态和动作，不负责请求编排。 */
export default function OfficialRunReportDrawer({
  report,
  reportLoading,
  stopping,
  verifying,
  onClose,
  onStop,
  onVerify,
  onOpenCandidates,
}: Props) {
  const candidates = report?.reconcile_detail.candidates ?? [];
  const verifications = report?.reconcile_detail.verifications ?? [];
  const collectedJobs = report?.reconcile_detail.collected_jobs ?? [];
  const jobFilter = report?.reconcile_detail.job_filter ?? "";

  return (
    <Drawer
      title="采集报告"
      width={640}
      open={report !== null || reportLoading}
      onClose={onClose}
      extra={
        <Space>
          {report?.status === "running" ? (
            <>
              <Button danger size="small" loading={stopping} onClick={() => void onStop()}>
                停止
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                采集中
              </Text>
            </>
          ) : (
            report && <Tag>{report.status_label}</Tag>
          )}
        </Space>
      }
    >
      <Spin spinning={reportLoading}>
        {report && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            {report.status === "running" ? (
              <Card size="small">
                <Space direction="vertical" size={2}>
                  <Text>
                    采集中……已翻 {report.pages} 次，抓到 {report.collected} 条
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    多页站点要跑几分钟。可以关掉这个窗口，采集会继续。
                  </Text>
                </Space>
              </Card>
            ) : (
              <Space direction="vertical" size={4}>
                <Tag color={VERDICT_COLORS[report.verdict]} style={{ fontSize: 14 }}>
                  {report.verdict_label}
                </Tag>
                <Paragraph strong style={{ marginBottom: 0 }}>
                  {report.headline}
                </Paragraph>
                {report.error && <Text type="secondary">{report.error}</Text>}
              </Space>
            )}

            {report.trend && (
              <Alert
                type={TREND_ALERT_TYPES[report.trend.state] ?? "info"}
                showIcon
                message={`与近期对比：${report.trend.label}`}
                description={report.trend.detail}
              />
            )}

            <Card size="small" title="账目">
              <Space direction="vertical" size={2}>
                <Text>
                  翻页 {report.pages} 次，抓到 {report.collected} 条，新入库 {report.stored} 条
                </Text>
                {report.skipped > 0 && <Text type="secondary">已存在跳过 {report.skipped} 条</Text>}
                {report.detail_missing > 0 && (
                  <Text type="warning">其中 {report.detail_missing} 条没有正文</Text>
                )}
                <Text type="secondary">
                  {report.total_hint === null
                    ? "站点没有给出岗位总数"
                    : jobFilter
                      ? `站点全站声明总数为 ${report.total_hint} 条（本次按关键词筛选，不能直接比较）`
                      : `站点声明总数为 ${report.total_hint} 条`}
                </Text>
                {report.llm_calls > 0 && (
                  <Text type="secondary">
                    调用大模型 {report.llm_calls} 次（用你自己配置的模型）
                  </Text>
                )}
              </Space>
            </Card>

            {jobFilter && (
              <Alert
                type="info"
                showIcon
                message={`本次岗位筛选：${jobFilter}`}
                description="采集器仍会继续翻页寻找匹配岗位，但筛选后的数量不能证明全站岗位已经抓全。"
              />
            )}

            {collectedJobs.length > 0 && (
              <Card
                size="small"
                title={`本次采集到的岗位（${collectedJobs.length}）`}
                extra={
                  <Button size="small" onClick={() => report && onOpenCandidates(report.id)}>
                    查看备选岗位
                  </Button>
                }
              >
                <Space direction="vertical" size={5} style={{ width: "100%" }}>
                  {collectedJobs.slice(0, 50).map((job, index) => (
                    <Space key={`${job.candidate_id ?? "job"}-${job.source_url}-${index}`}>
                      <Text strong style={{ fontSize: 12 }}>
                        {job.title || "（未识别岗位名）"}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {[job.company, job.location].filter(Boolean).join(" · ")}
                      </Text>
                      {job.source_url && (
                        <Typography.Link
                          href={job.source_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          style={{ fontSize: 12 }}
                        >
                          原页面
                        </Typography.Link>
                      )}
                    </Space>
                  ))}
                  {collectedJobs.length > 50 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      还有 {collectedJobs.length - 50} 条，点击「查看备选岗位」查看完整列表。
                    </Text>
                  )}
                </Space>
              </Card>
            )}

            {(report.extraction.methods.length > 0 || report.extraction.deep_links_skipped > 0) && (
              <Card size="small" title="读取方式">
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  {report.extraction.methods.map((note) => (
                    <Text key={note} style={{ fontSize: 12, wordBreak: "break-all" }}>
                      {note}
                    </Text>
                  ))}
                  {report.extraction.recipes_learned > 0 && (
                    <Text type="success" style={{ fontSize: 12 }}>
                      已归纳出这一站的页面结构并存下，之后的采集不再需要调用模型
                    </Text>
                  )}
                  {report.extraction.deep_links_skipped > 0 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      另有 {report.extraction.deep_links_skipped} 个更深层的地址没有跟进
                      （那是站点的次级导航，不是岗位列表）
                    </Text>
                  )}
                </Space>
              </Card>
            )}

            <Card size="small" title="依据">
              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                {(report.reconcile_detail.layers ?? [])
                  .filter((layer) => layer.layer !== "termination")
                  .map((layer) => (
                    <div key={layer.layer}>
                      <Text strong style={{ fontSize: 13 }}>
                        {layer.label}
                      </Text>
                      <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                        {layer.detail}
                      </Paragraph>
                    </div>
                  ))}
                {report.reconcile_detail.termination && (
                  <div>
                    <Text strong style={{ fontSize: 13 }}>
                      翻页终止
                    </Text>
                    <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                      {report.reconcile_detail.termination.detail}
                    </Paragraph>
                  </div>
                )}
              </Space>
            </Card>

            {candidates.length > 0 && (
              <Card
                size="small"
                title={`待核实（${candidates.length} 个岗位页）`}
                extra={
                  <Button
                    size="small"
                    icon={<SafetyCertificateOutlined />}
                    loading={verifying}
                    onClick={() => void onVerify()}
                  >
                    核实这些地址
                  </Button>
                }
              >
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    这些地址在站点地图里，但这次没抓到。
                    <Text strong style={{ fontSize: 12 }}>
                      其中既有漏抓的，也有早就招满、链接还留在地图里的
                    </Text>
                    ——点开看一眼，或点右上角让应用逐个核实一遍（一次最多 20 个），结论会据此重算。
                  </Text>
                  {candidates.slice(0, MAX_VISIBLE_CANDIDATES).map((url) => (
                    <Typography.Link
                      key={url}
                      href={url}
                      target="_blank"
                      rel="noreferrer noopener"
                      style={{ fontSize: 12, wordBreak: "break-all" }}
                    >
                      {url}
                    </Typography.Link>
                  ))}
                  {candidates.length > MAX_VISIBLE_CANDIDATES && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      还有 {candidates.length - MAX_VISIBLE_CANDIDATES} 个未列出
                    </Text>
                  )}
                </Space>
              </Card>
            )}

            {verifications.length > 0 && (
              <Card size="small" title={`已核实（${verifications.length} 个）`}>
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  {verifications.map((entry) => (
                    <Space key={entry.url} size={6} align="start">
                      <Tag color={VERIFY_COLORS[entry.state]}>{entry.label}</Tag>
                      <Text style={{ fontSize: 12, wordBreak: "break-all" }}>
                        {entry.url}
                        {entry.detail ? ` · ${entry.detail}` : ""}
                      </Text>
                    </Space>
                  ))}
                </Space>
              </Card>
            )}

            <Text type="secondary" style={{ fontSize: 12 }}>
              开始于 {formatDateTime(report.started_at)}
              {report.finished_at ? `，结束于 ${formatDateTime(report.finished_at)}` : ""}
            </Text>
          </Space>
        )}
      </Spin>
    </Drawer>
  );
}
