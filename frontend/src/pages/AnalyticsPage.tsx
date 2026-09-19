/** 求职数据看板（R-14）：指标卡 + 漏斗 + 趋势。
 *
 * 数据全部来自后端 ``/api/analytics/dashboard``，前端只做展示。图表用自绘 SVG
 * （``FunnelChart`` / ``BarChart``），不引 echarts / antv / plots。
 */
import { Card, Col, Empty, Row, Segmented, Skeleton, Statistic, Typography } from "antd";
import { useState } from "react";
import { getAnalyticsDashboard } from "../api/analytics";
import BarChart from "../components/analytics/BarChart";
import FunnelChart from "../components/analytics/FunnelChart";
import { useApi } from "../hooks/useApi";
import { FUNNEL_STATUSES } from "../types";

export default function AnalyticsPage() {
  const [trendMonths, setTrendMonths] = useState(6);
  const { data, loading, error } = useApi(() => getAnalyticsDashboard(trendMonths), [trendMonths]);

  // 漏斗主线：只画推进主线（已投递→筛选中→测评/笔试→面试→Offer），
  // 「已结束」「待确认」属于分支，不在主线漏斗里，但后端仍会下发其计数。
  const mainFunnel = (data?.funnel ?? []).filter((stage) =>
    (FUNNEL_STATUSES as readonly string[]).includes(stage.status),
  );

  return (
    <div className="analytics-page">
      <div className="profile-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            求职统计
          </Typography.Title>
          <Typography.Text type="secondary">
            投递总量、面试率、笔试通过率、Offer 数与六阶段漏斗，全部本地聚合、离线可用。
          </Typography.Text>
        </div>
      </div>

      {loading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : error ? (
        <Typography.Text type="danger">{error}</Typography.Text>
      ) : !data ? (
        <Empty description="暂无看板数据" />
      ) : (
        <>
          <Row gutter={16}>
            <Col span={6}>
              <Card>
                <Statistic title="投递总量" value={data.total_applications} />
                <Typography.Text type="secondary">有效投递 {data.valid_applications}</Typography.Text>
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="面试率" value={Math.round(data.interview_rate * 100)} suffix="%" />
                <Typography.Text type="secondary">
                  面试 {data.interview_count} / 有效投递 {data.valid_applications}
                </Typography.Text>
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="笔试通过率"
                  value={Math.round(data.assessment_pass_rate * 100)}
                  suffix="%"
                />
                <Typography.Text type="secondary">
                  进面试 {data.assessment_to_interview_count} / 测评笔试 {data.assessment_count}
                </Typography.Text>
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="Offer 数"
                  value={data.offer_count}
                  valueStyle={{ color: "#389e0d" }}
                />
              </Card>
            </Col>
          </Row>

          <Card title="六阶段漏斗" style={{ marginTop: 16 }}>
            <FunnelChart stages={mainFunnel} />
          </Card>

          <Card
            title={`近 ${trendMonths} 个月投递趋势`}
            extra={
              <Segmented
                size="small"
                value={trendMonths}
                onChange={(value) => setTrendMonths(Number(value))}
                options={[
                  { label: "近1月", value: 1 },
                  { label: "近3月", value: 3 },
                  { label: "近6月", value: 6 },
                  { label: "近1年", value: 12 },
                ]}
              />
            }
            style={{ marginTop: 16 }}
          >
            <BarChart points={data.trend} />
          </Card>
        </>
      )}
    </div>
  );
}
