/**
 * 联网搜索设置卡片。
 *
 * 重点在"改得动、改得对"：这几个参数此前只有后端接口、没有任何界面入口，
 * 「抓取正文的条数」永远是默认的 0。所以这里断言的是保存出去的那份 payload，
 * 而不是界面上显示了什么。
 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SearchCard from "./SearchCard";

const apiMocks = vi.hoisted(() => ({
  getSearchConfig: vi.fn(),
  saveSearchConfig: vi.fn(),
}));

vi.mock("../../api/settings", () => apiMocks);

const stored = {
  sources: ["bing", "duckduckgo"],
  searxng_url: "",
  fetch_pages: 0,
  max_results: 8,
};

function renderCard() {
  return render(
    <AntdApp>
      <SearchCard />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.getSearchConfig.mockResolvedValue(stored);
  apiMocks.saveSearchConfig.mockImplementation(async (config) => config);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SearchCard", () => {
  it("loads the saved setting instead of showing defaults", async () => {
    apiMocks.getSearchConfig.mockResolvedValue({
      ...stored,
      sources: ["bing", "searxng"],
      searxng_url: "http://localhost:8080",
      fetch_pages: 2,
      max_results: 12,
    });

    renderCard();

    await waitFor(() => expect(apiMocks.getSearchConfig).toHaveBeenCalledOnce());
    // 抓取正文那组是单选，要看勾中的那一项是不是服务端存的那一项。
    expect(await screen.findByRole("checkbox", { name: "抓前 2 条正文" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "只取摘要（最快）" })).not.toBeChecked();
    expect(screen.getByPlaceholderText("http://localhost:8080")).toHaveValue(
      "http://localhost:8080",
    );
  });

  it("saves the page-fetch count the user picked", async () => {
    renderCard();
    await waitFor(() => expect(apiMocks.getSearchConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("checkbox", { name: "抓前 2 条正文" }));
    fireEvent.click(screen.getByRole("button", { name: /保存搜索设置/ }));

    // 这是本次修复的核心：抓取正文的条数以前没有任何界面能改，永远是 0。
    await waitFor(() =>
      expect(apiMocks.saveSearchConfig).toHaveBeenCalledWith(
        expect.objectContaining({ fetch_pages: 2 }),
      ),
    );
  });

  it("keeps the source list the user checked", async () => {
    renderCard();
    await waitFor(() => expect(apiMocks.getSearchConfig).toHaveBeenCalledOnce());

    // 取消 DuckDuckGo，只留 Bing。
    fireEvent.click(screen.getByRole("checkbox", { name: "DuckDuckGo" }));
    fireEvent.click(screen.getByRole("button", { name: /保存搜索设置/ }));

    await waitFor(() =>
      expect(apiMocks.saveSearchConfig).toHaveBeenCalledWith(
        expect.objectContaining({ sources: ["bing"] }),
      ),
    );
  });

  it("refuses to save an empty source list", async () => {
    renderCard();
    await waitFor(() => expect(apiMocks.getSearchConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("checkbox", { name: "Bing" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "DuckDuckGo" }));
    fireEvent.click(screen.getByRole("button", { name: /保存搜索设置/ }));

    // 后端 sources 要求至少一项，前端先拦下来，别让用户收到一个 422。
    expect(await screen.findByText("至少要选一个搜索来源")).toBeInTheDocument();
    expect(apiMocks.saveSearchConfig).not.toHaveBeenCalled();
  });

  it("refuses a SearXNG address without a scheme", async () => {
    renderCard();
    await waitFor(() => expect(apiMocks.getSearchConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("checkbox", { name: /SearXNG/ }));
    fireEvent.change(screen.getByPlaceholderText("http://localhost:8080"), {
      target: { value: "localhost:8080" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存搜索设置/ }));

    expect(
      await screen.findByText("SearXNG 地址要以 http:// 或 https:// 开头"),
    ).toBeInTheDocument();
    expect(apiMocks.saveSearchConfig).not.toHaveBeenCalled();
  });

  it("trims the SearXNG address before saving", async () => {
    renderCard();
    await waitFor(() => expect(apiMocks.getSearchConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("checkbox", { name: /SearXNG/ }));
    fireEvent.change(screen.getByPlaceholderText("http://localhost:8080"), {
      target: { value: "  http://localhost:8888  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存搜索设置/ }));

    await waitFor(() =>
      expect(apiMocks.saveSearchConfig).toHaveBeenCalledWith(
        expect.objectContaining({ searxng_url: "http://localhost:8888" }),
      ),
    );
  });

  it("keeps the save button disabled until something changes", async () => {
    renderCard();
    await waitFor(() => expect(apiMocks.getSearchConfig).toHaveBeenCalledOnce());

    const saveButton = screen.getByRole("button", { name: /保存搜索设置/ });
    expect(saveButton).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: "抓前 1 条正文" }));
    expect(saveButton).toBeEnabled();
    expect(screen.getByText("有未保存的改动")).toBeInTheDocument();
  });

  it("tells the user when the saved setting could not be read", async () => {
    apiMocks.getSearchConfig.mockRejectedValue(new Error("后端没有响应"));

    renderCard();

    // 取不到就退回默认值可以，但不能让人以为屏幕上这份就是自己存过的设置。
    expect(await screen.findByText("没能读取已保存的设置")).toBeInTheDocument();
    expect(screen.getByText(/后端没有响应/)).toBeInTheDocument();
  });
});
