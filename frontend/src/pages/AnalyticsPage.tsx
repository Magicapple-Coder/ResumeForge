/** 求职数据看板（R-14）：概览指标 + 四个主题区块。
 *
 * 数据全部来自后端 `/api/analytics/dashboard`，前端只做展示。图表用自绘 SVG
 * （`FunnelChart` / `BarChart` / `HorizontalBarChart`），不引 echarts / antv / plots。
 * 每个指标的口径见 `backend/app/services/analytics.py` 的模块 docstring——那里也写明了
 * 因数据模型不支持而**刻意不提供**的指标，别再提。
 *
 * 两条贯穿全页的约束：
 *
 * 1. **不许画会撒谎的零**。趋势图与周内分布只统计填了「投递日期」的记录；若一条都没有，
 *    画一排零轴会被读成"这几个月真的一份没投"。所以：有缺口就显示 `DataGapNotice` 说明
 *    原因，整张图没有输入就显示空态而不是零轴。
 * 2. **每张图的 `aria-label` 必须互不相同**，否则读屏软件与测试都分不清是哪张图。
 */
import { Col, Empty, Row, Segmented, Skeleton, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import { getAnalyticsDashboard } from "../api/analytics";
import BarChart from "../components/analytics/BarChart";
import ChartBlock from "../components/analytics/ChartBlock";
import DataGapNotice from "../components/analytics/DataGapNotice";
import FunnelChart from "../components/analytics/FunnelChart";
import HorizontalBarChart from "../components/analytics/HorizontalBarChart";
import SectionCard from "../components/analytics/SectionCard";
import StatCard from "../components/analytics/StatCard";
import { useApi } from "../hooks/useApi";
import { FUNNEL_STATUSES, REFERRAL_STATUS_LABELS } from "../types";
import type { AnalyticsDashboard, FunnelStage, ReferralStatus } from "../types";
import { formatRate } from "../utils/format";

/** 提醒四档的展示名。紧急度的判定在后端 `reminder_urgency`（唯一实现），
 *  这里只是给四档取短名。 */
const REMINDER_BUCKETS: { key: keyof ReminderBucketKeys; label: string }[] = [
  { key: "overdue", label: "已逾期" },
  { key: "soon", label: "24 小时内" },
  { key: "upcoming", label: "3 天内" },
  { key: "later", label: "更远" },
];

type ReminderBucketKeys = {
  overdue: number;
  soon: number;
  upcoming: number;
  later: number;
};

/** 后端把明显非公司名的记录（纯数字 ID、单字垃圾、空）归并到这个中性占位。 */
const UNKNOWN_COMPANY_LABEL = "未填写公司";

/** 「投递最多的公司」：展示清洗后的真实公司前 5 名。
 *
 * 明显非公司名已被后端归并到「未填写公司」并从榜单剔除——这里只画真公司，缺口用
 * `DataGapNotice` 诚实交代，绝不把垃圾当公司名展示（宁可少显示也不要假数据）。
 */
function TopCompaniesBlock({ data }: { data: AnalyticsDashboard }) {
  const realGroups = data.top_companies.filter((item) => item.label !== UNKNOWN_COMPANY_LABEL);
  const displayed = realGroups.slice(0, 5);
  // 前 5 之外（含后端折进 other 的长尾）如实并入"另有 N 家"，不让榜单总数对不上。
  const otherCount = Math.max(0, realGroups.length + data.other_company_count - displayed.length);
  const unknownCount = data.top_companies
    .filter((item) => item.label === UNKNOWN_COMPANY_LABEL)
    .reduce((sum, item) => sum + item.count, 0);

  if (data.total_applications === 0) {
    return <Empty description="还没有投递记录" />;
  }
  if (realGroups.length === 0) {
    // 有记录但全都没填公司名：诚实说明缺口，而不是画一张空榜或展示垃圾。
    return (
      <DataGapNotice
        missing={unknownCount}
        label="投递未填写公司名"
        action={<Link to="/tracker">去补充</Link>}
      />
    );
  }
  return (
    <>
      <HorizontalBarChart
        ariaLabel="投递最多的公司"
        align="start"
        items={displayed.map((item) => ({
          key: item.key,
          label: item.label,
          count: item.count,
        }))}
      />
      {otherCount > 0 ? (
        <Typography.Text type="secondary">另有 {otherCount} 家公司未在前 5 列出</Typography.Text>
      ) : null}
      {unknownCount > 0 ? (
        <DataGapNotice
          missing={unknownCount}
          label="投递未填写公司名，未计入排行"
          action={<Link to="/tracker">去补充</Link>}
        />
      ) : null}
    </>
  );
}

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
            投递转化与卡点、时间节奏、渠道去向、简历健康度，全部本地聚合、离线可用。
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
        <AnalyticsBody
          data={data}
          mainFunnel={mainFunnel}
          trendMonths={trendMonths}
          onTrendMonthsChange={setTrendMonths}
        />
      )}
    </div>
  );
}

interface BodyProps {
  data: AnalyticsDashboard;
  mainFunnel: FunnelStage[];
  trendMonths: number;
  onTrendMonthsChange: (value: number) => void;
}

function AnalyticsBody({ data, mainFunnel, trendMonths, onTrendMonthsChange }: BodyProps) {
  const gap = data.applied_date_gap;
  // 趋势图与周内分布都吃 applied_at：一条带日期的都没有时，它们只能画零轴。
  const hasAppliedDates = gap.dated > 0;
  const reminders = data.reminder_counts as ReminderBucketKeys & { total: number };
  const unlinkedApplications = data.total_applications - data.track_resume_linked_count;

  return (
    <>
      <Row gutter={[16, 16]} className="analytics-metric-row">
        <Col xs={24} sm={12} xl={6}>
          <StatCard
            framed
            title="投递总量"
            value={data.total_applications}
            hint={`有效投递 ${data.valid_applications}`}
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <StatCard
            framed
            title="面试率"
            value={formatRate(data.interview_rate)}
            hint={`面试 ${data.interview_count} / 有效投递 ${data.valid_applications}`}
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <StatCard
            framed
            title="笔试通过率"
            value={formatRate(data.assessment_pass_rate)}
            hint={`进面试 ${data.assessment_to_interview_count} / 测评笔试 ${data.assessment_count}`}
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <StatCard
            framed
            title="Offer 数"
            value={data.offer_count}
            valueStyle={{ color: "#389e0d" }}
            hint={`Offer 率 ${formatRate(data.offer_rate)}`}
          />
        </Col>
      </Row>

      <SectionCard
        title="转化与卡点"
        description="转化率的分母都是「有效投递」（扣除尚未核实的「待确认」）。「超过 7 天没有更新」指进行中、且 7 天内没有任何改动——改一条备注也算更新，所以它不等于「面试卡住」。"
      >
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={14}>
            <ChartBlock title="求职漏斗" hint="每个阶段的人数，分母是有效投递">
              <FunnelChart stages={mainFunnel} />
            </ChartBlock>
          </Col>
          <Col xs={24} xl={10}>
            <Row gutter={[16, 16]}>
              <Col span={8}>
                <StatCard title="进行中" value={data.active_count} hint="未走到终态" />
              </Col>
              <Col span={8}>
                <StatCard
                  title="超过 7 天没更新"
                  value={data.stalled_count}
                  hint="进行中且久未改动"
                />
              </Col>
              <Col span={8}>
                <StatCard
                  title="没有下一步"
                  value={data.no_next_action_count}
                  hint="进行中且未填"
                />
              </Col>
            </Row>
            <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
              <Link to="/tracker">去「求职进度」补下一步或推进状态</Link>
            </Typography.Paragraph>
          </Col>
        </Row>
      </SectionCard>

      <SectionCard
        title="时间与节奏"
        description="趋势与周内分布按「投递日期」统计；「最近 N 天新增」按记录创建时间算，用的是滚动窗口，与所在时区无关。"
        extra={
          <Segmented
            size="small"
            value={trendMonths}
            onChange={(value) => onTrendMonthsChange(Number(value))}
            options={[
              { label: "近1月", value: 1 },
              { label: "近3月", value: 3 },
              { label: "近6月", value: 6 },
              { label: "近1年", value: 12 },
            ]}
          />
        }
      >
        <DataGapNotice
          missing={gap.undated}
          available={gap.dated}
          label="投递未填「投递日期」"
          action={<Link to="/tracker">去补充</Link>}
        />
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={12}>
            <ChartBlock title="投递趋势" hint="按投递日期">
              {hasAppliedDates ? (
                <BarChart points={data.trend} ariaLabel="投递趋势" />
              ) : (
                <Empty description="还没有填过投递日期的记录" />
              )}
            </ChartBlock>
          </Col>
          <Col xs={24} xl={12}>
            <ChartBlock title="周内投递分布" hint="按投递日期">
              {hasAppliedDates ? (
                <BarChart points={data.weekday} ariaLabel="周内投递分布" />
              ) : (
                <Empty description="还没有填过投递日期的记录" />
              )}
            </ChartBlock>
          </Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={12} sm={6}>
            <StatCard title="最近 7 天新增" value={data.recent_7d_count} hint="按创建时间" />
          </Col>
          <Col xs={12} sm={6}>
            <StatCard title="最近 30 天新增" value={data.recent_30d_count} hint="按创建时间" />
          </Col>
          {REMINDER_BUCKETS.map((bucket) => (
            <Col xs={12} sm={3} key={bucket.key}>
              <StatCard
                title={`提醒·${bucket.label}`}
                value={reminders[bucket.key]}
                valueStyle={
                  bucket.key === "overdue" && reminders.overdue > 0
                    ? { color: "#cf1322" }
                    : undefined
                }
              />
            </Col>
          ))}
        </Row>
      </SectionCard>

      <SectionCard
        title="渠道与去向"
        description="内推转化由关联的投递记录派生——那条记录走到「面试」及以上才算转化。「记录来源」是这一行**怎么进系统的**，不是投递渠道（本库没有渠道字段）。"
      >
        {/* 顶部三张卡：两个核心指标 + 一条口径提示，把描述里的长句收敛成可扫读的提示 tile。 */}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={8}>
            <StatCard
              title="内推转化率"
              value={formatRate(data.referral.rate)}
              hint={`已转化 ${data.referral.converted} / 有效内推 ${data.referral.total}`}
            />
          </Col>
          <Col xs={24} sm={8}>
            <StatCard
              title="内推总数"
              value={data.referral_status.reduce((sum, item) => sum + item.count, 0)}
              hint="含已关闭与无效"
            />
          </Col>
          <Col xs={24} sm={8}>
            <div className="analytics-hint-tile">
              <Typography.Text strong>口径提示</Typography.Text>
              <Typography.Text type="secondary">
                「记录来源」是录入方式，不是投递渠道；内推转化按关联投递走到面试及以上算。
              </Typography.Text>
            </div>
          </Col>
        </Row>

        {/* 中部左右两栏：左内推状态分布，右投递最多的公司（前 5，缺口诚实说明）。 */}
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} xl={12}>
            <ChartBlock title="内推状态分布" hint="按当前内推状态">
              {data.referral_status.some((item) => item.count > 0) ? (
                <HorizontalBarChart
                  ariaLabel="内推状态分布"
                  align="start"
                  items={data.referral_status.map((item) => ({
                    key: item.key,
                    label: REFERRAL_STATUS_LABELS[item.key as ReferralStatus] ?? item.key,
                    count: item.count,
                  }))}
                />
              ) : (
                <Empty description="还没有内推记录" />
              )}
            </ChartBlock>
          </Col>
          <Col xs={24} xl={12}>
            <ChartBlock title="投递最多的公司" hint="前 5 名">
              <TopCompaniesBlock data={data} />
            </ChartBlock>
          </Col>
        </Row>

        {/* 底部：三种记录来源的迷你 tile。 */}
        <div style={{ marginTop: 16 }}>
          <ChartBlock title="记录来源" hint="录入方式，不是投递渠道">
            <Row gutter={[16, 16]}>
              {data.record_sources.map((item) => (
                <Col xs={8} key={item.key}>
                  <div className="analytics-source-tile">
                    <StatCard title={item.label} value={item.count} />
                  </div>
                </Col>
              ))}
            </Row>
          </ChartBlock>
        </div>
      </SectionCard>

      <SectionCard
        title="简历与健康度"
        description="「带一致性提醒」与「带【待补】」来自生成时留下的记录与正文里的未完成标记；「待确认主张」是事实台账里还没核实、但引用时会受影响的条目。"
      >
        <Row gutter={[16, 16]}>
          <Col xs={12} sm={6}>
            <StatCard
              title="简历"
              value={data.resume_count}
              hint={
                data.resume_scanned_count < data.resume_count
                  ? `待补只统计最近 ${data.resume_scanned_count} 份`
                  : "全部已纳入统计"
              }
            />
          </Col>
          <Col xs={12} sm={6}>
            <StatCard title="带一致性提醒" value={data.resume_with_warnings_count} />
          </Col>
          <Col xs={12} sm={6}>
            <StatCard title="带【待补】" value={data.resume_with_placeholders_count} />
          </Col>
          <Col xs={12} sm={6}>
            <StatCard title="待确认主张" value={data.unverified_claim_count} />
          </Col>
        </Row>
        <DataGapNotice
          missing={unlinkedApplications}
          available={data.track_resume_linked_count}
          label="投递没有关联简历"
          action={
            <Typography.Text type="secondary">
              关联后才能按简历看效果；录入界面暂未提供关联入口。
            </Typography.Text>
          }
        />
      </SectionCard>
    </>
  );
}
