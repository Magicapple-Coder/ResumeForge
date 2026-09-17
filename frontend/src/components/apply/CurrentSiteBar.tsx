/**
 * 当前招聘网站提示条。
 *
 * 用户原先不知道投递台到底对接的是哪个招聘网站。这里把"当前站点"如实标出来，并说明
 * 目前只支持这一个、以后会陆续增加。
 *
 * **重要**：站点名与站点清单**完全来自后端接口**（`GET /api/apply/sites`），前端一行都不写死。
 * 这样以后后端注册表里新增一个招聘网站，这个组件会自动显示新站点，前端无需改动。
 */
import { GlobalOutlined } from "@ant-design/icons";
import { Space, Tag, Typography } from "antd";
import { listSites } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { type SiteList, siteDisplayName } from "../../types";

export default function CurrentSiteBar() {
  const { data } = useApi<SiteList>(listSites, []);

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
    </div>
  );
}
