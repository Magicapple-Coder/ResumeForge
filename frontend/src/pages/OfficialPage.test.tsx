/**
 * 官网采集页：列表、三态结论、报告抽屉，以及"被阻断 ≠ 未识别"这条区分。
 *
 * 后者是本页最要紧的一条：把"探测被阻断"显示成"没识别出系统"，用户会去删掉一个其实能用的源。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OfficialProbeResult, OfficialRun, OfficialRunDetail, OfficialSite } from "../types";
import OfficialPage from "./OfficialPage";

const apiMocks = vi.hoisted(() => ({
  listOfficialSites: vi.fn(),
  createOfficialSite: vi.fn(),
  reprobeOfficialSite: vi.fn(),
  deleteOfficialSite: vi.fn(),
  collectOfficialSite: vi.fn(),
  listOfficialRuns: vi.fn(),
  getOfficialRun: vi.fn(),
  verifyOfficialRun: vi.fn(),
  stopOfficialRun: vi.fn(),
  updateOfficialSite: vi.fn(),
}));

vi.mock("../api/official", () => apiMocks);

// 浏览器状态条（渲染升级的启动入口）也渲染在这一页上，它的接口要一并挡掉。
const browserMocks = vi.hoisted(() => ({
  getBrowserStatus: vi.fn(),
  startBrowser: vi.fn(),
}));

vi.mock("../api/apply", () => browserMocks);

function makeSite(overrides: Partial<OfficialSite> = {}): OfficialSite {
  return {
    id: 1,
    company: "示例科技有限公司",
    homepage_url: "",
    careers_url: "https://boards.greenhouse.io/acme",
    source_kind: "greenhouse",
    source_label: "Greenhouse",
    endpoint: "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
    confidence: "high",
    confidence_label: "来自用户提供的招聘页地址",
    probe_evidence: "你提供的招聘页地址指向该系统的 acme 职位板",
    robots_allowed: true,
    robots_detail: "站点允许采集",
    crawl_delay_seconds: null,
    min_interval_seconds: 10,
    enabled: true,
    last_probed_at: "2026-09-23T10:00:00",
    created_at: "2026-09-23T09:00:00",
    latest_verdict: "complete",
    latest_verdict_label: "已确认为全量",
    latest_headline: "站点声明的 12 条岗位全部抓到",
    latest_run_id: 7,
    latest_status: "done",
    latest_status_label: "已完成",
    can_collect: true,
    ...overrides,
  };
}

function makeRunDetail(overrides: Partial<OfficialRunDetail> = {}): OfficialRunDetail {
  return {
    id: 7,
    site_id: 1,
    site_company: "示例科技有限公司",
    status: "done",
    status_label: "已完成",
    pages: 1,
    collected: 12,
    stored: 9,
    skipped: 3,
    detail_missing: 0,
    total_hint: 12,
    verdict: "complete",
    verdict_label: "已确认为全量",
    evidence: "total",
    headline: "站点声明的 12 条岗位全部抓到",
    missing: 0,
    blocks: [""],
    block_labels: ["正常"],
    started_at: "2026-09-23T10:00:00",
    finished_at: "2026-09-23T10:00:05",
    error: "",
    llm_calls: 0,
    extraction: { methods: [], llm_calls: 0, recipes_learned: 0, deep_links_skipped: 0 },
    reconcile_detail: {
      basis: "站点接口给出的总数",
      layers: [{ layer: "total", label: "总量对账", detail: "站点声明 12 条，实际抓到 12 条" }],
      termination: { state: "exhausted", detail: "已翻到列表最后一页" },
    },
    trend: {
      state: "stable",
      label: "与近期持平",
      detail: "这次抓到 12 条，与近 3 次的中位数 12 条相当",
      baseline: 12,
      latest: 12,
    },
    ...overrides,
  };
}

/**
 * 列表形状的运行记录——**接口 `POST /official/sites/{id}/collect` 真实返回的就是这个**，
 * 它没有 `extraction` 与 `reconcile_detail`（那两项属于详情接口）。
 *
 * 这个 helper 存在的理由是一个已经发生过的 bug：`collectOfficialSite` 的 mock 从前来者不拒地
 * 返回完整的 `OfficialRunDetail`，比接口**宽松**。于是"点采集 → 抽屉立刻打开"这条路径拿到的
 * 永远是带全字段的假数据，而线上拿到的是列表形状——`report.extraction.methods` 读到
 * `undefined`，整页白屏，测试却全绿。**mock 给的形状必须和接口一样，宽一点都不行。**
 */
function makeRun(overrides: Partial<OfficialRun> = {}): OfficialRun {
  return {
    id: 7,
    site_id: 1,
    site_company: "示例科技有限公司",
    status: "running",
    status_label: "采集中",
    pages: 1,
    collected: 0,
    stored: 0,
    skipped: 0,
    detail_missing: 0,
    total_hint: null,
    verdict: "unknown",
    verdict_label: "无法确认",
    evidence: "",
    headline: "",
    missing: 0,
    blocks: [""],
    block_labels: ["正常"],
    started_at: "2026-09-23T10:00:00",
    finished_at: null,
    error: "",
    llm_calls: 0,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <OfficialPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

async function openSiteMoreMenu() {
  fireEvent.click(await screen.findByRole("button", { name: "更多操作" }));
}

async function clickSiteCollect() {
  const company = await screen.findByText("示例科技有限公司");
  const row = company.closest("tr");
  if (!row) throw new Error("找不到示例公司的表格行");
  fireEvent.click(within(row).getByRole("button", { name: /采集/ }));
}

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.listOfficialSites.mockResolvedValue([makeSite()]);
  apiMocks.getOfficialRun.mockResolvedValue(makeRunDetail());
  // 采集记录与站点列表**在同一屏上**，所以它也要有默认返回：不给的话 `Promise.all` 里那一路
  // 解析成 undefined，表格拿到的是一个非法值（渲染成空表），用例看不出任何异常。
  apiMocks.listOfficialRuns.mockResolvedValue([]);
  // **给采集一个默认返回，且形状必须是接口真实返回的那种（列表形状）**：不设的话它解析成
  // undefined，而 handleCollect 会去读 run.status 抛异常、被 catch 吞掉——表现成"抽屉没打开"，
  // 而报错信息只说找不到元素。给成 detail 形状则会让"抽屉立刻打开"这条路拿到比线上更全的
  // 假数据，从而放过整类崩溃（见 makeRun 的说明）。
  apiMocks.collectOfficialSite.mockResolvedValue(makeRun());
  apiMocks.updateOfficialSite.mockResolvedValue({
    state: "hit",
    state_label: "已识别招聘系统",
    site: makeSite(),
    job_count: 12,
    evidence: "更新后的招聘页已识别",
    attempts: [],
  });
  browserMocks.getBrowserStatus.mockResolvedValue({ state: "stopped" });
});

afterEach(cleanup);

describe("OfficialPage", () => {
  it("renders the recognised system and the latest verdict", async () => {
    renderPage();

    expect(await screen.findByText("示例科技有限公司")).toBeInTheDocument();
    expect(screen.getByText("Greenhouse")).toBeInTheDocument();
    expect(screen.getByText("已确认为全量")).toBeInTheDocument();
    expect(screen.getByText("站点声明的 12 条岗位全部抓到")).toBeInTheDocument();
  });

  it("shows an empty state when nothing has been added", async () => {
    apiMocks.listOfficialSites.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText("还没有添加公司")).toBeInTheDocument();
  });

  it("disables collecting when the system was never recognised", async () => {
    apiMocks.listOfficialSites.mockResolvedValue([
      makeSite({ source_kind: "", source_label: "", can_collect: false }),
    ]);
    renderPage();

    expect(await screen.findByRole("button", { name: /采集/ })).toBeDisabled();
    expect(screen.getByText("未识别")).toBeInTheDocument();
  });

  it("disables collecting when robots forbids it", async () => {
    apiMocks.listOfficialSites.mockResolvedValue([
      makeSite({ robots_allowed: false, robots_detail: "站点不允许采集", can_collect: false }),
    ]);
    renderPage();

    expect(await screen.findByRole("button", { name: /采集/ })).toBeDisabled();
    expect(screen.getByText("不允许")).toBeInTheDocument();
  });

  it("opens the report drawer with the reconcile evidence after collecting", async () => {
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    renderPage();

    await clickSiteCollect();

    // 第二个参数是「本次最多抓多少条」：没填时是 undefined（后端按"不设上限"处理）。
    await waitFor(() => expect(apiMocks.collectOfficialSite).toHaveBeenCalledWith(1, undefined));
    // 依据要逐层展示——结论没有依据就等于没有结论。
    expect(await screen.findByText("总量对账")).toBeInTheDocument();
    expect(screen.getByText("站点声明 12 条，实际抓到 12 条")).toBeInTheDocument();
    expect(screen.getByText("已翻到列表最后一页")).toBeInTheDocument();
  });

  it("lists the unverified candidates and says what they are", async () => {
    // 抽屉里的内容来自 getOfficialRun，不是 collect 的返回值——两个都要给。
    const withCandidates = makeRunDetail({
      verdict: "unknown",
      verdict_label: "无法确认",
      headline: "无法确认：站点地图里有 2 个岗位页没抓到，需要核实它们是漏抓还是已经下架",
      reconcile_detail: {
        layers: [],
        candidates: [
          "https://boards.greenhouse.io/acme/jobs/2",
          "https://boards.greenhouse.io/acme/jobs/3",
        ],
      },
    });
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(withCandidates);
    renderPage();

    await clickSiteCollect();

    expect(await screen.findByText(/待核实（2 个岗位页）/)).toBeInTheDocument();
    expect(screen.getByText("https://boards.greenhouse.io/acme/jobs/2")).toBeInTheDocument();
    // **必须说清那不是漏抓清单**：里面既有真漏的，也有早就招满、链接还留在地图里的。
    // 不说明的话，用户会以为按图索骥点一遍就补齐了。
    expect(screen.getByText(/也有早就招满/)).toBeInTheDocument();
  });

  it("verifies the candidates and shows the upgraded verdict", async () => {
    const withCandidates = makeRunDetail({
      verdict: "unknown",
      verdict_label: "无法确认",
      headline: "无法确认：站点地图里有 1 个岗位页没抓到，需要核实它们是漏抓还是已经下架",
      reconcile_detail: {
        layers: [],
        candidates: ["https://boards.greenhouse.io/acme/jobs/2"],
      },
    });
    const afterVerify = makeRunDetail({
      verdict: "incomplete",
      verdict_label: "已确认不全",
      headline: "已确认不全：核实到 1 个岗位页仍在招聘，但这次没有抓到",
      missing: 1,
      reconcile_detail: {
        layers: [],
        candidates: [],
        verifications: [
          {
            url: "https://boards.greenhouse.io/acme/jobs/2",
            state: "live",
            label: "仍在招聘",
            detail: "大模型应用开发工程师",
          },
        ],
      },
    });
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(withCandidates);
    apiMocks.verifyOfficialRun.mockResolvedValue(afterVerify);
    renderPage();

    await clickSiteCollect();
    fireEvent.click(await screen.findByRole("button", { name: /核实这些地址/ }));

    await waitFor(() => expect(apiMocks.verifyOfficialRun).toHaveBeenCalledWith(7));
    // 结论与逐条核实结果都要刷出来。
    expect(await screen.findByText("已确认不全")).toBeInTheDocument();
    expect(screen.getByText("仍在招聘")).toBeInTheDocument();
    expect(screen.getByText(/大模型应用开发工程师/)).toBeInTheDocument();
  });

  it("surfaces a trend drop without calling it a miss", async () => {
    // **它是对账之外的独立提醒**：条数下降既可能是我们漏抓，也可能是公司真的关掉了岗位。
    // 报告里必须让用户看到这句话，否则他会直接以为工具坏了。
    const dropped = makeRunDetail({
      trend: {
        state: "dropped",
        label: "明显少于近期",
        detail:
          "这次抓到 3 条，而近 5 次的中位数是 40 条。**这不一定是漏抓**——也可能是这家公司真的关掉了那些岗位",
        baseline: 40,
        latest: 3,
      },
    });
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(dropped);
    renderPage();

    await clickSiteCollect();

    expect(await screen.findByText(/与近期对比：明显少于近期/)).toBeInTheDocument();
    expect(screen.getByText(/不一定是漏抓/)).toBeInTheDocument();
  });

  it("keeps a stable trend quiet", async () => {
    renderPage();
    await clickSiteCollect();

    // 持平时也要说一句（否则用户不知道有这项检查），但**不报警**——
    // 误报会让用户对这个提示脱敏，等到真的掉量时反而看不见。
    expect(await screen.findByText(/与近期对比：与近期持平/)).toBeInTheDocument();
  });

  it("sends the per-run job limit the user typed", async () => {
    // 岗位上万条的站点一次翻不完，填了这个数就不用干等十几分钟再手动停。
    // 界面填了、请求里没有 = 静默失效，而结果（抓了满满一屏）看起来完全正常。
    renderPage();

    const input = await screen.findByLabelText("本次最多抓多少条");
    fireEvent.change(input, { target: { value: "20" } });
    await clickSiteCollect();

    await waitFor(() => expect(apiMocks.collectOfficialSite).toHaveBeenCalledWith(1, 20));
  });

  it("sends no limit when the box is left empty", async () => {
    // 留空 = 不设上限（也就是这之前的行为），不能因为界面上有个空输入框就发一个 0 或 null 过去。
    renderPage();

    await clickSiteCollect();

    await waitFor(() => expect(apiMocks.collectOfficialSite).toHaveBeenCalledWith(1, undefined));
  });

  it("shows progress and a stop button while a collection is running", async () => {
    // 采集现在是后台跑的：接口立刻返回"采集中"，界面必须显示进展而不是一个空结论——
    // 结论还没算出来，此时展示"无法确认"之类的空标签会误导人。
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "running", status_label: "采集中", verdict: "", verdict_label: "" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(
      makeRunDetail({ status: "running", status_label: "采集中", pages: 3, collected: 27 }),
    );
    apiMocks.stopOfficialRun.mockResolvedValue(makeRunDetail({ status: "running" }));
    renderPage();

    await clickSiteCollect();

    expect(await screen.findByText(/采集中……/)).toBeInTheDocument();
    // 用正则而不是字面量：antd 会给**两个汉字**的按钮标签自动插一个空格（排版约定），
    // 所以无障碍名字是「停 止」。写成字面量会找不到，而报错信息只会说"找不到按钮"。
    const stopButton = await screen.findByRole("button", { name: /停\s*止/ });
    expect(screen.getByText(/可以关掉这个窗口/)).toBeInTheDocument();

    fireEvent.click(stopButton);
    await waitFor(() => expect(apiMocks.stopOfficialRun).toHaveBeenCalledWith(7));
  });

  it("marks the row as collecting and disables the button while running", async () => {
    apiMocks.listOfficialSites.mockResolvedValue([
      makeSite({ latest_status: "running", latest_verdict: "", latest_verdict_label: "" }),
    ]);
    renderPage();

    // 只看结论是不够的：采集进行中时结论还是空的，界面会显示成"还没采过"。
    expect(await screen.findByText("采集中")).toBeInTheDocument();
    const company = screen.getByText("示例科技有限公司");
    const row = company.closest("tr");
    if (!row) throw new Error("找不到示例公司的表格行");
    expect(within(row).getByRole("button", { name: /采集/ })).toBeDisabled();
  });

  it("distinguishes a blocked probe from an unrecognised one", async () => {
    const blocked: OfficialProbeResult = {
      state: "blocked",
      state_label: "探测被阻断，没能得出结论",
      site: makeSite({ source_kind: "", source_label: "", can_collect: false }),
      job_count: 0,
      evidence: "试过的地址都返回了限流响应",
      attempts: [
        {
          feed_key: "greenhouse",
          endpoint: "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
          block: "rate_limit",
          block_label: "站点限流",
          job_count: 0,
          detail: "站点限流（HTTP 429）",
        },
      ],
    };
    apiMocks.listOfficialSites.mockResolvedValue([
      makeSite({ source_kind: "", source_label: "", can_collect: false }),
    ]);
    apiMocks.reprobeOfficialSite.mockResolvedValue(blocked);
    renderPage();

    await openSiteMoreMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /重新探测/ }));

    expect(await screen.findByText("探测被阻断，没能得出结论")).toBeInTheDocument();
    expect(screen.getByText("试过的地址都返回了限流响应")).toBeInTheDocument();
    // 试过哪些端点要摆出来——这是用户唯一能拿去反馈的东西。
    expect(screen.getByText(/站点限流/)).toBeInTheDocument();
    // 被阻断时**不能**说成"没识别出系统"：那会让用户去删一个其实能用的源。
    expect(screen.queryByText("没有识别出已知的招聘系统")).not.toBeInTheDocument();
  });

  it("sends the three fields when adding a company", async () => {
    apiMocks.createOfficialSite.mockResolvedValue({
      state: "hit",
      state_label: "已识别招聘系统",
      site: makeSite(),
      job_count: 12,
      evidence: "你提供的招聘页地址指向该系统的 acme 职位板",
      attempts: [],
    } as OfficialProbeResult);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /添加公司/ }));
    fireEvent.change(await screen.findByLabelText("公司名称"), {
      target: { value: "另一家公司" },
    });
    fireEvent.change(screen.getByLabelText("招聘页地址"), {
      target: { value: "https://boards.greenhouse.io/other" },
    });
    fireEvent.click(screen.getByRole("button", { name: "添加并识别" }));

    await waitFor(() =>
      expect(apiMocks.createOfficialSite).toHaveBeenCalledWith(
        expect.objectContaining({
          company: "另一家公司",
          careers_url: "https://boards.greenhouse.io/other",
        }),
      ),
    );
  });

  it("edits company information from the site list", async () => {
    renderPage();

    await openSiteMoreMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /编辑/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("编辑公司信息");
    fireEvent.change(screen.getByLabelText("公司名称"), {
      target: { value: "腾讯科技有限公司" },
    });
    fireEvent.change(screen.getByLabelText("招聘页地址"), {
      target: { value: "https://join.qq.com/post.html" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并重新识别" }));

    await waitFor(() =>
      expect(apiMocks.updateOfficialSite).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          company: "腾讯科技有限公司",
          careers_url: "https://join.qq.com/post.html",
        }),
      ),
    );
  });
});

describe("模型花销与读取方式", () => {
  it("shows the model call count in the accounting card", async () => {
    // **用户自付 key，这一项必须显眼**：不说的话，他只能去翻服务商的账单。
    const withCalls = makeRunDetail({
      llm_calls: 3,
      extraction: { methods: [], llm_calls: 3, recipes_learned: 0, deep_links_skipped: 0 },
    });
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(withCalls);
    renderPage();

    await clickSiteCollect();

    expect(await screen.findByText(/调用大模型 3 次/)).toBeInTheDocument();
  });

  it("keeps the model cost out of the evidence card", async () => {
    // **不混进「依据」**：用了模型与"抓全了没有"毫无关系，放在一起会让用户以为它们是一回事。
    const withCalls = makeRunDetail({
      llm_calls: 1,
      extraction: { methods: [], llm_calls: 1, recipes_learned: 0, deep_links_skipped: 0 },
    });
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(withCalls);
    renderPage();

    await clickSiteCollect();

    const evidence = await screen.findByText("依据");
    expect(evidence.closest(".ant-card")).not.toHaveTextContent("大模型");
  });

  it("lists how each page was read", async () => {
    const withMethods = makeRunDetail({
      llm_calls: 1,
      extraction: {
        methods: [
          "https://careers.example.com/jobs：通用规则（链接文字即岗位名）",
          "https://careers.example.com/other：模型抽取（已归纳出这一站的页面结构并存下）",
        ],
        llm_calls: 1,
        recipes_learned: 1,
        deep_links_skipped: 0,
      },
    });
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(withMethods);
    renderPage();

    await clickSiteCollect();

    expect(await screen.findByText("读取方式")).toBeInTheDocument();
    expect(screen.getByText(/通用规则（链接文字即岗位名）/)).toBeInTheDocument();
    // 归纳成功要让用户知道——那是"下次不再花钱"的凭据。
    expect(screen.getByText(/之后的采集不再需要调用模型/)).toBeInTheDocument();
  });

  it("hides the reading-method card when the adapter read everything", async () => {
    renderPage();
    await clickSiteCollect();

    await screen.findByText("账目");
    expect(screen.queryByText("读取方式")).not.toBeInTheDocument();
  });
});

describe("深链跳过", () => {
  it("says how many deeper addresses were skipped", async () => {
    // 让用户知道"只翻了这么几页"不是卡住了，是我们主动没跟更深的那一层。
    const withDeep = makeRunDetail({
      extraction: { methods: [], llm_calls: 0, recipes_learned: 0, deep_links_skipped: 3 },
    });
    apiMocks.collectOfficialSite.mockResolvedValue(
      makeRun({ status: "done", status_label: "已完成" }),
    );
    apiMocks.getOfficialRun.mockResolvedValue(withDeep);
    renderPage();

    await clickSiteCollect();

    expect(await screen.findByText(/3 个更深层的地址没有跟进/)).toBeInTheDocument();
    expect(screen.getByText(/次级导航/)).toBeInTheDocument();
  });
});

describe("探测没试完", () => {
  it("says the conclusion does not count when the attempt limit was hit", async () => {
    // **"试到上限就停了"与"这家公司不用这套系统"是两件事**，而它们会落到同一个状态上。
    // 不说这一句，用户看到的就是一句我们并不知道真假的结论。
    apiMocks.listOfficialSites.mockResolvedValue([
      makeSite({ source_kind: "", source_label: "", can_collect: false }),
    ]);
    apiMocks.reprobeOfficialSite.mockResolvedValue({
      state: "not_found",
      state_label: "未识别出已知的招聘系统",
      site: makeSite({ source_kind: "", source_label: "", can_collect: false }),
      job_count: 0,
      evidence: "没有识别出已知的招聘系统；还有 3 个候选地址没来得及试（达到本次尝试上限）",
      attempts: [],
    } as OfficialProbeResult);
    renderPage();

    await openSiteMoreMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /重新探测/ }));

    // 那句话由后端写进 evidence，界面原样展示——**同一句只该有一处**。
    expect(await screen.findByText(/还有 3 个候选地址没来得及试/)).toBeInTheDocument();
  });

  it("stays quiet when everything was tried", async () => {
    apiMocks.listOfficialSites.mockResolvedValue([
      makeSite({ source_kind: "", source_label: "", can_collect: false }),
    ]);
    apiMocks.reprobeOfficialSite.mockResolvedValue({
      state: "not_found",
      state_label: "未识别出已知的招聘系统",
      site: makeSite({ source_kind: "", source_label: "", can_collect: false }),
      job_count: 0,
      evidence: "没有识别出已知的招聘系统",
      attempts: [],
    } as OfficialProbeResult);
    renderPage();

    await openSiteMoreMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /重新探测/ }));

    await screen.findByText("未识别出已知的招聘系统");
    expect(screen.queryByText(/没来得及试/)).not.toBeInTheDocument();
  });
});

describe("采集记录", () => {
  it("lists what was collected, newest first, across companies", async () => {
    // **采集是个"跑完就看不见过程"的动作**：没有这一栏，第二天就不知道上次采的是哪家、
    // 采到什么程度、为什么停下来。
    apiMocks.listOfficialRuns.mockResolvedValue([
      makeRun({
        id: 9,
        site_company: "示例科技有限公司",
        status: "done",
        status_label: "已完成",
        verdict: "incomplete",
        verdict_label: "已确认不全",
        headline: "已确认不全：站点声明的 20 条里还差 5 条",
        pages: 4,
        collected: 15,
        stored: 12,
        detail_missing: 3,
        llm_calls: 2,
      }),
    ]);
    renderPage();

    // **限定在采集记录那张卡里**：公司名在上面那张站点表里也有（两张表本来就都该有），
    // 不限定范围的话断言会同时命中两处，报"找到多个元素"。
    const card = (await screen.findByText("采集记录")).closest(".ant-card") as HTMLElement;
    expect(within(card).getByText("示例科技有限公司")).toBeInTheDocument();
    expect(within(card).getByText("已确认不全")).toBeInTheDocument();
    // 账目要能一眼看出这次花了多少、缺了多少——它们是"要不要再来一次"的依据。
    expect(within(card).getByText(/翻页 4 次，抓到 15 条/)).toBeInTheDocument();
    expect(within(card).getByText(/缺正文 3 条/)).toBeInTheDocument();
    expect(within(card).getByText(/模型 2 次/)).toBeInTheDocument();
  });

  it("opens the report of an old run", async () => {
    // 记录的价值在于能回看**当时**的结论：只列一行摘要、点不开的话，用户还是得靠记忆。
    apiMocks.listOfficialRuns.mockResolvedValue([
      makeRun({ id: 42, status: "done", status_label: "已完成" }),
    ]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /看报告/ }));

    await waitFor(() => expect(apiMocks.getOfficialRun).toHaveBeenCalledWith(42));
  });

  it("says what to do when there is no history yet", async () => {
    renderPage();

    expect(await screen.findByText(/还没有采集记录/)).toBeInTheDocument();
  });

  it("does not show a verdict for a run that is still going", async () => {
    // 还在跑时结论还没算出来。显示一个空的结论标签会让用户以为这次什么都没抓到。
    apiMocks.listOfficialRuns.mockResolvedValue([
      makeRun({ status: "running", status_label: "采集中", headline: "" }),
    ]);
    renderPage();

    expect(await screen.findByText("采集中……")).toBeInTheDocument();
  });
});
