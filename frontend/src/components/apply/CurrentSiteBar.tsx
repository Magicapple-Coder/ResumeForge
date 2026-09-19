/**
 * 当前招聘网站提示条。
 *
 * 用户原先不知道投递台到底对接的是哪个招聘网站。这里把"当前站点"如实标出来，并说明
 * 目前只支持这一个、以后会陆续增加。
 *
 * **重要**：站点名与站点清单**完全来自后端接口**（`GET /api/apply/sites`），前端一行都不写死。
 * 这样以后后端注册表里新增一个招聘网站，这个组件会自动显示新站点，前端无需改动。
 *
 * 站点健康度（`GET /api/collect/site-health`）：招聘网站改版后，采集会"悄悄抓不到东西"——
 * 任务显示完成，用户却拿不到有用的岗位。后端把这种漂移判定成 `degraded`，这里**只在 degraded
 * 时**显示醒目、可操作的标记。判据完全在后端，前端只展示 `reasons`，绝不在此再判一次。
 */
import { GlobalOutlined, WarningFilled } from "@ant-design/icons";
import { Space, Tag, Typography } from "antd";
import { getSiteHealth, listSites } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { type SiteHealthList, type SiteList, siteDisplayName, siteHealthFor } from "../../types";

export default function CurrentSiteBar() {
  const { data } = useApi<SiteList>(listSites, []);
  // 健康度单独取：它随每次采集变化，而站点清单基本不变，合在一起反而会互相牵制。
  const { data: health } = useApi<SiteHealthList>(getSiteHealth, []);

  // 读取失败或没有站点时不渲染，绝不挡住页面其它功能。
  if (!data || !data.current) return null;

  const current = siteDisplayName(data, data.current);
  const currentOption = data.sites.find((site) => site.key === data.current);
  const onlyOne = data.sites.length <= 1;
  const capabilities = currentOption
    ? [currentOption.supports_collect ? "采集" : "", currentOption.supports_apply ? "投递" : ""]
        .filter(Boolean)
        .join(" / ")
    : "";

  // 只认后端结论：前端不自行判断，避免两处判据漂移。
  const currentHealth = siteHealthFor(health, data.current);
  const degraded = currentHealth?.status === "degraded";
  const healthText = degraded
    ? currentHealth.reasons.filter(Boolean).join(" ") ||
      "最近采集异常，站点可能已改版——先重试一次；如果一直这样，请到项目仓库反馈。"
    : "";

  return (
    <div className="apply-site-bar">
      <Space wrap align="center" size={8}>
        <GlobalOutlined />
        <Typography.Text>
          当前招聘网站：<Typography.Text strong>{current}</Typography.Text>
        </Typography.Text>
        {capabilities && <Tag color="blue">{capabilities}</Tag>}
        <Typography.Text type="secondary">
          {onlyOne
            ? "目前仅支持这一个招聘网站，后续会陆续增加。"
            : "可在「投递设置」里切换要使用的招聘网站。"}
        </Typography.Text>
      </Space>
      {degraded && (
        // 醒目标记：只在 degraded 时出现，不给健康站点加装饰。aria-label 用后端原因文本，
        // 既让辅助技术可读，也给测试一个稳定的查询条件（antd 会给两字中文按钮自动插空格，
        // 用中文文本做查询条件会找不到）。
        <div
          className="apply-site-bar-health"
          role="alert"
          aria-label={`站点健康度告警：${healthText}`}
          style={{ marginTop: 6 }}
        >
          <Space wrap align="center" size={8}>
            <Tag color="error" icon={<WarningFilled />}>
              站点可能已改版
            </Tag>
            <Typography.Text type="danger">{healthText}</Typography.Text>
          </Space>
        </div>
      )}
    </div>
  );
}
