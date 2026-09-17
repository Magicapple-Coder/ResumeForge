/**
 * 事实台账页面：列表渲染、占位符高亮、快捷确认、空态与错误态。
 *
 * 重点覆盖"界面会不会把还没核实的内容显示得像已经确认过"——这是这个功能唯一
 * 会造成真实后果的失误（用户照着它投出带【待补】的简历）。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Claim, ClaimList } from "../types";
import ClaimsPage from "./ClaimsPage";

const apiMocks = vi.hoisted(() => ({
  listClaims: vi.fn(),
  getClaim: vi.fn(),
  createClaim: vi.fn(),
  updateClaim: vi.fn(),
  deleteClaim: vi.fn(),
  getClaimBaseline: vi.fn(),
  draftClaims: vi.fn(),
}));

vi.mock("../api/claims", () => apiMocks);

function makeClaim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: 1,
    title: "检索接口",
    category: "项目经历",
    subject: "校园知识检索平台",
    source_fact: "负责检索接口的实现与联调。",
    candidate_wording: "实现检索接口并联调上线",
    sources: [],
    responsibility_level: "参与",
    verification_status: "待确认",
    allowed_uses: [],
    interview_details: { decisions: [], difficulties: [], verification: [], result: null },
    boundary: "",
    risk_notes: [],
    last_verified: "",
    created_at: "2026-09-18T00:00:00",
    updated_at: "2026-09-18T00:00:00",
    warnings: [],
    ...overrides,
  };
}

function makeList(items: Claim[]): ClaimList {
  return {
    items,
    total: items.length,
    confirmed_count: items.filter((item) => item.verification_status === "已确认").length,
    pending_count: items.filter((item) => item.verification_status === "待确认").length,
    category_counts: {},
  };
}

const EMPTY_BASELINE = {
  confirmed_count: 0,
  baseline_text: "",
  blocked_wording: [],
  warnings: [],
};

function renderPage() {
  // 页面里有指向「拿去深挖」的跳转，所以要给它一个 Router 上下文。
  return render(
    <MemoryRouter>
      <AntdApp>
        <ClaimsPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.getClaimBaseline.mockResolvedValue(EMPTY_BASELINE);
});

afterEach(() => {
  cleanup();
});

describe("ClaimsPage", () => {
  it("renders entries with the original fact and the resume wording", async () => {
    apiMocks.listClaims.mockResolvedValue(makeList([makeClaim()]));
    renderPage();

    expect(await screen.findByText("检索接口")).toBeInTheDocument();
    expect(screen.getByText("负责检索接口的实现与联调。")).toBeInTheDocument();
    expect(screen.getByText("实现检索接口并联调上线")).toBeInTheDocument();
  });

  it("highlights placeholders so an unverified wording never looks finished", async () => {
    apiMocks.listClaims.mockResolvedValue(
      makeList([
        makeClaim({
          candidate_wording: "优化了检索速度【待补：具体倍数】",
        }),
      ]),
    );
    const { container } = renderPage();

    await screen.findByText("检索接口");
    const marks = container.querySelectorAll("mark.claim-placeholder");
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent).toBe("【待补：具体倍数】");
  });

  it("shows server-side warnings instead of judging in the browser", async () => {
    apiMocks.listClaims.mockResolvedValue(
      makeList([makeClaim({ warnings: ["待确认的表述没有加【待补】占位符；导出终稿时…"] })]),
    );
    renderPage();

    expect(await screen.findByText(/待确认的表述没有加/)).toBeInTheDocument();
  });

  it("confirms an entry through the API and reloads the baseline", async () => {
    apiMocks.listClaims.mockResolvedValue(makeList([makeClaim()]));
    apiMocks.updateClaim.mockResolvedValue(
      makeClaim({ verification_status: "已确认", warnings: [] }),
    );

    renderPage();
    await screen.findByText("检索接口");
    fireEvent.click(screen.getByRole("button", { name: /标记已确认/ }));

    await waitFor(() => {
      expect(apiMocks.updateClaim).toHaveBeenCalledTimes(1);
    });
    const [, payload] = apiMocks.updateClaim.mock.calls[0];
    expect(payload.verification_status).toBe("已确认");
    // 其余字段必须原样带上，不能因为"只改状态"就把内容清空。
    expect(payload.source_fact).toBe("负责检索接口的实现与联调。");
    await waitFor(() => {
      expect(apiMocks.getClaimBaseline.mock.calls.length).toBeGreaterThan(1);
    });
  });

  it("surfaces the backend rejection when a confirmed entry still has a placeholder", async () => {
    apiMocks.listClaims.mockResolvedValue(makeList([makeClaim()]));
    apiMocks.updateClaim.mockRejectedValue(
      new Error("简历表述里还有「【待补」这样的未完成标记，不能标记为「已确认」"),
    );

    renderPage();
    await screen.findByText("检索接口");
    fireEvent.click(screen.getByRole("button", { name: /标记已确认/ }));

    expect(await screen.findByText(/不能标记为「已确认」/)).toBeInTheDocument();
  });

  it("offers a way in when the ledger is empty", async () => {
    apiMocks.listClaims.mockResolvedValue(makeList([]));
    renderPage();

    expect(await screen.findByText(/台账还是空的/)).toBeInTheDocument();
  });

  it("shows the error state rather than an empty list when loading fails", async () => {
    apiMocks.listClaims.mockRejectedValue(new Error("接口不可用"));
    renderPage();

    expect(await screen.findByText("接口不可用")).toBeInTheDocument();
    // 加载失败时不能再显示"台账还是空的"，否则用户会以为自己没建过条目。
    expect(screen.queryByText(/台账还是空的/)).not.toBeInTheDocument();
  });

  it("offers a way into the drill from the ledger", async () => {
    // 深挖的输入就是台账条目，所以入口必须在这里——否则用户找不到它。
    apiMocks.listClaims.mockResolvedValue(makeList([makeClaim()]));
    renderPage();

    expect(await screen.findByRole("button", { name: /拿去深挖/ })).toBeInTheDocument();
  });

  it("passes the chosen filters to the API", async () => {
    apiMocks.listClaims.mockResolvedValue(makeList([]));
    renderPage();
    await waitFor(() => {
      expect(apiMocks.listClaims).toHaveBeenCalledWith({ category: "", status: "", keyword: "" });
    });
  });
});
