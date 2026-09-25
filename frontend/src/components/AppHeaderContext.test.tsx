/** 页头上下文：当前数据集名 + 头像（取自「我的资料」当前启用的照片）。 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import AppHeaderContext from "./AppHeaderContext";

const listDatasets = vi.fn();
const getProfile = vi.fn();

vi.mock("../api/settings", () => ({
  listDatasets: () => listDatasets(),
}));
vi.mock("../api/profile", () => ({
  getProfile: () => getProfile(),
}));

function renderHeader() {
  return render(
    <MemoryRouter>
      <AppHeaderContext />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listDatasets.mockReset();
  getProfile.mockReset();
});

describe("AppHeaderContext", () => {
  it("显示当前数据集的名字，而不是列表里的第一个", async () => {
    listDatasets.mockResolvedValue([
      { id: "a", name: "工作数据", is_active: false },
      { id: "b", name: "个人数据", is_active: true },
    ]);
    getProfile.mockResolvedValue({ name: "张示例", photo: "" });

    renderHeader();

    await waitFor(() => expect(screen.getByText("个人数据")).toBeInTheDocument());
    expect(screen.queryByText("工作数据")).not.toBeInTheDocument();
  });

  it("头像用资料里当前启用的那张照片", async () => {
    listDatasets.mockResolvedValue([{ id: "a", name: "默认", is_active: true }]);
    getProfile.mockResolvedValue({ name: "张示例", photo: "data:image/png;base64,AAAA" });

    const { container } = renderHeader();

    await waitFor(() => {
      expect(container.querySelector(".app-user-avatar img")).not.toBeNull();
    });
    expect(container.querySelector(".app-user-avatar img")).toHaveAttribute(
      "src",
      "data:image/png;base64,AAAA",
    );
  });

  it("没有照片时退化成姓名首字，而不是空白圆圈", async () => {
    listDatasets.mockResolvedValue([{ id: "a", name: "默认", is_active: true }]);
    getProfile.mockResolvedValue({ name: "张示例", photo: "" });

    renderHeader();

    await waitFor(() => expect(screen.getByText("张")).toBeInTheDocument());
  });

  it("接口读不到时安静退化：页头少一块，应用不报错", async () => {
    listDatasets.mockRejectedValue(new Error("boom"));
    getProfile.mockRejectedValue(new Error("boom"));

    const { container } = renderHeader();

    await waitFor(() => expect(container.querySelector(".ant-skeleton")).toBeNull());
    expect(container.querySelector(".app-dataset-chip")).toBeNull();
  });
});
