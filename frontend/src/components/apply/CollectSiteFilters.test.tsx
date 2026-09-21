/**
 * 站点侧筛选项：清单渲染、来源标注、选中值进入表单、读不到时降级。
 *
 * 这一块最容易出的错是**静默失效**——用户选了一个条件、界面看着也选了，实际没生效。
 * 所以用例的重点不在"能不能渲染"，而在"选中的编码是否真的进了表单值"与"来源是否如实标注"。
 */
import { App as AntdApp, Button, Form } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CollectFilterOptions } from "../../types";
import CollectSiteFilters from "./CollectSiteFilters";

const apiMocks = vi.hoisted(() => ({ getCollectFilterOptions: vi.fn() }));

vi.mock("../../api/apply", () => ({
  getCollectFilterOptions: apiMocks.getCollectFilterOptions,
}));

function options(sessionRead: boolean): CollectFilterOptions {
  return {
    site_key: "boss",
    display_name: "BOSS直聘",
    session_read: sessionRead,
    groups: [
      {
        key: "jobType",
        param: "jobType",
        label: "求职类型",
        source: sessionRead ? "session" : "public",
        note: "",
        options: [
          { code: "0", label: "不限", group: "" },
          { code: "1901", label: "全职", group: "" },
          { code: "1902", label: "实习", group: "" },
        ],
      },
      {
        key: "industry",
        param: "industry",
        label: "公司行业",
        source: "public",
        note: "",
        options: [
          { code: "100020", label: "互联网", group: "互联网/AI" },
          { code: "100028", label: "人工智能", group: "互联网/AI" },
          { code: "101405", label: "半导体/芯片", group: "电子/通信/半导体" },
        ],
      },
    ],
  };
}

/** 组件是给 Form.Item 用的，必须放在 Form 里；这里顺便把表单值读出来断言。 */
function renderFilters(onValues: (values: Record<string, unknown>) => void = () => {}) {
  return render(
    <AntdApp>
      <Form
        onFinish={onValues}
        initialValues={{ filters: {} }}
        onValuesChange={(_, all) => onValues(all as Record<string, unknown>)}
      >
        <CollectSiteFilters disabled={false} />
        <Button htmlType="submit">提交</Button>
      </Form>
    </AntdApp>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getCollectFilterOptions.mockResolvedValue(options(true));
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("CollectSiteFilters", () => {
  it("按后端给的清单渲染下拉框，标题就是站点筛选栏的叫法", async () => {
    renderFilters();
    expect(await screen.findByText("求职类型")).toBeInTheDocument();
    expect(screen.getByText("公司行业")).toBeInTheDocument();
  });

  it("选中的编码进入表单的 filters，键就是分组 key", async () => {
    const onValues = vi.fn();
    renderFilters(onValues);

    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "站点筛选-求职类型" }), {
      button: 0,
    });
    const option = await screen.findByText(
      (content, element) => content === "实习" && !!element?.closest(".ant-select-item-option"),
    );
    fireEvent.click(option);

    await waitFor(() => expect(onValues).toHaveBeenCalledWith({ filters: { jobType: "1902" } }));
  });

  it("读到登录态清单时标「读取自你的登录会话」，且不提示去启动浏览器", async () => {
    renderFilters();
    expect(await screen.findByText("读取自你的登录会话")).toBeInTheDocument();
    expect(screen.queryByText(/请先启动投递专用浏览器/)).not.toBeInTheDocument();
  });

  it("只有公共清单时如实标注，并说明启动浏览器能拿到账号可见的完整选项", async () => {
    apiMocks.getCollectFilterOptions.mockResolvedValue(options(false));
    renderFilters();
    expect(await screen.findByText("全网通用清单")).toBeInTheDocument();
    // 「实习」是否可见因人而异，这句话是用户唯一的解释来源。
    expect(screen.getByText(/请先启动投递专用浏览器/)).toBeInTheDocument();
  });

  it("行业选项按一级分组展示，不铺成一长条", async () => {
    renderFilters();
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "站点筛选-公司行业" }), {
      button: 0,
    });
    const groupLabel = await screen.findByText(
      (content, element) => content === "互联网/AI" && !!element?.closest(".ant-select-item-group"),
    );
    expect(groupLabel).toBeInTheDocument();
  });

  it("接口失败时降级成一条提示，不把整个采集表单挡住", async () => {
    apiMocks.getCollectFilterOptions.mockRejectedValue(new Error("接口挂了"));
    renderFilters();
    expect(await screen.findByText("没能读到招聘网站的筛选条件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重新读取/ })).toBeInTheDocument();
  });

  it("清单为空（该站点没有站点侧筛选）时不渲染任何东西", async () => {
    apiMocks.getCollectFilterOptions.mockResolvedValue({ groups: [] });
    const { container } = renderFilters();
    await waitFor(() => expect(apiMocks.getCollectFilterOptions).toHaveBeenCalled());
    expect(container.querySelector(".apply-collect-site-filters")).toBeNull();
  });
});
