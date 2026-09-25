import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CandidateJobDetail, Job } from "../types";
import JobsPage from "./JobsPage";

const mocks = vi.hoisted(() => ({
  reload: vi.fn(),
  startBackfill: vi.fn(),
  jobs: [] as Job[],
}));

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: { items: mocks.jobs, total: mocks.jobs.length },
    loading: false,
    reload: mocks.reload,
    error: null,
  }),
}));

// 只替换要断言的 `startBackfill`，其余导出（addToQueue / QueueConflictError）保持真实，
// 免得漏掉某个导出让 `import` 变成 undefined。
vi.mock("../api/apply", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/apply")>();
  return { ...actual, startBackfill: mocks.startBackfill };
});

const BASE_JOB: Job = {
  id: 1,
  title: "护士",
  company: "示例医院",
  location: "杭州市余杭区",
  salary: "",
  job_type: "社招",
  description: "负责病区护理工作。",
  requirements: "持有护士执业资格证。",
  additional_info: "提供岗位培训。",
  keywords: [],
  source: "手动添加",
  source_url: "",
  posted_at: "2026年8月20日",
  status: "开放中",
  note: "",
  note_images: [],
  recognition_source: "",
  favorite: false,
  created_at: "2026-08-19T08:00:00",
  updated_at: "2026-08-21T09:30:00",
};

function makeJob(overrides: Partial<Job> = {}): Job {
  return { ...BASE_JOB, ...overrides };
}

function renderPage(initialEntries: string[] = ["/jobs"]) {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={initialEntries}>
        <JobsPage />
      </MemoryRouter>
    </AntdApp>,
  );
}

// 备选岗位抽屉与「导入到岗位」都会调它；不挡掉的话 jsdom 里会真发 fetch。
const candidateMocks = vi.hoisted(() => ({
  listCandidateJobs: vi.fn(),
  getCandidateJob: vi.fn(),
  createCandidateJob: vi.fn(),
  updateCandidateJob: vi.fn(),
  deleteCandidateJob: vi.fn(),
  importCandidateJobs: vi.fn(),
  markCandidateJobImported: vi.fn(),
}));

vi.mock("../api/candidateJob", () => candidateMocks);

function makeCandidate(overrides: Partial<CandidateJobDetail> = {}): CandidateJobDetail {
  return {
    id: 1,
    title: "后端开发工程师",
    company: "示例公司",
    location: "",
    salary: "",
    raw_text: "",
    images: [],
    note: "",
    source: "官网采集",
    source_url: "",
    collect_task_id: null,
    status: "pending",
    imported_job_id: null,
    created_at: "2026-09-23T10:00:00",
    updated_at: "2026-09-23T10:00:00",
    description: "",
    requirements: "",
    job_type: "",
    additional_info: "",
    ...overrides,
  };
}

const makeCandidateDetail = makeCandidate;

describe("JobsPage", () => {
  // 本仓库没有全局 auto-cleanup（见 ApplyPage.test.tsx），必须显式清理，
  // 否则前一个用例渲染出的 DOM 会留在 document 里，让后面的 getByRole 命中多个元素。
  afterEach(cleanup);

  beforeEach(() => {
    mocks.jobs = [makeJob()];
    mocks.startBackfill.mockReset();
    mocks.startBackfill.mockResolvedValue({} as never);
    for (const mock of Object.values(candidateMocks)) mock.mockReset();
  });

  it("shows the recruitment posted date instead of the local update timestamp", () => {
    renderPage();

    expect(screen.getAllByText("发布时间").length).toBeGreaterThan(0);
    expect(screen.getByText("2026年8月20日")).toBeInTheDocument();
    expect(screen.queryByText("更新时间")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-08-21 17:30")).not.toBeInTheDocument();
  });

  it("有 JD 为空的岗位时显示「补齐详情」按钮", () => {
    mocks.jobs = [makeJob({ id: 7, title: "后端开发", description: "" })];
    renderPage();

    expect(screen.getByRole("button", { name: "补齐详情" })).toBeInTheDocument();
  });

  it("所有岗位都有职位描述时不显示「补齐详情」按钮", () => {
    mocks.jobs = [makeJob({ description: "有正文的岗位描述" })];
    renderPage();

    expect(screen.queryByRole("button", { name: "补齐详情" })).not.toBeInTheDocument();
  });

  it("选择模式下有勾选时只补勾选的岗位，而不是本页所有空 JD", async () => {
    mocks.jobs = [
      makeJob({ id: 1, title: "空A", description: "" }),
      makeJob({ id: 2, title: "空B", description: "" }),
    ];
    renderPage();

    fireEvent.click(screen.getByText("选择"));
    // 第 0 个复选框是全选表头，第 1 个才是第一行；只勾第一行。
    fireEvent.click(screen.getAllByRole("checkbox")[1]);

    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() => expect(mocks.startBackfill).toHaveBeenCalledTimes(1));
    // 勾选了就只补勾选的：不能把本页所有空 JD 也一起送出去。
    expect(mocks.startBackfill).toHaveBeenCalledWith([1]);
  });

  it("选择模式下没有勾选时退回补本页所有空 JD", async () => {
    mocks.jobs = [makeJob({ id: 1, description: "" }), makeJob({ id: 2, description: "" })];
    renderPage();

    fireEvent.click(screen.getByText("选择"));
    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() => expect(mocks.startBackfill).toHaveBeenCalledTimes(1));
    expect(mocks.startBackfill).toHaveBeenCalledWith([1, 2]);
  });

  it("本页没有空 JD 时不出现按钮（即使进了选择模式），因而不存在提交空数组的路径", () => {
    // 空数组会被后端 400 拒绝。若按钮常驻，用户就会看到一个"点得动、点了报错"的按钮。
    // 这里证明了那条路径不存在：没有空 JD → 按钮不渲染 → 连点击入口都没有。
    mocks.jobs = [makeJob({ id: 1, description: "有正文" })];
    renderPage();

    fireEvent.click(screen.getByText("选择"));

    expect(screen.queryByRole("button", { name: "补齐详情" })).not.toBeInTheDocument();
    expect(mocks.startBackfill).not.toHaveBeenCalled();
  });

  it("点「补齐详情」只把这页 JD 为空的岗位 id 交给后端", async () => {
    mocks.jobs = [
      makeJob({ id: 1, title: "有正文的岗位", description: "正文" }),
      makeJob({ id: 2, title: "空的岗位", description: "" }),
      makeJob({ id: 3, title: "只有空白的岗位", description: "   " }),
    ];
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() => expect(mocks.startBackfill).toHaveBeenCalledTimes(1));
    // 只送"描述为空"的两条；有正文的那条不该被带上。
    expect(mocks.startBackfill).toHaveBeenCalledWith([2, 3]);
  });

  it("后端拒绝时提示错误而不是谎报成功", async () => {
    mocks.jobs = [makeJob({ id: 5, description: "" })];
    mocks.startBackfill.mockRejectedValueOnce(new Error("一次最多补齐 200 个岗位的详情"));
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() =>
      expect(screen.getByText(/一次最多补齐 200 个岗位的详情/)).toBeInTheDocument(),
    );
  });

  it("后端因来源不支持拒收时只给提示，不给「仍然加入」的按钮", async () => {
    // 这是**兜底**分支：正常情况下按钮对这类岗位已经禁用了；万一前端数据里没有
    // apply_supported（旧缓存 / 旧版本），后端仍会拦下，界面必须说清楚而不能弹"确认继续"。
    const applyApi = await import("../api/apply");
    const spy = vi.spyOn(applyApi, "addToQueue").mockRejectedValue(
      new applyApi.QueueConflictError({
        message: "「护士」的来源不是投递台支持的招聘网站（当前支持：BOSS直聘），无法自动投递。",
        site_unsupported: true,
      }),
    );
    mocks.jobs = [makeJob({ id: 6, source: "手动添加", source_url: "" })];
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "护士" }));
    fireEvent.click(await screen.findByRole("button", { name: /加入投递台/ }));

    // antd 的确认弹窗把 title 同时渲染在弹窗头和内容区（本项目其它 modal.confirm 也是这个形状），
    // 所以这里按"至少出现一次"断言，真正的判据是内容里带上了后端那句话。
    expect((await screen.findAllByText("这个岗位不能自动投递")).length).toBeGreaterThan(0);
    expect(screen.getByText(/来源不是投递台支持的招聘网站/)).toBeInTheDocument();
    // 这一类确认也没用，所以不能出现"仍然加入"。
    expect(screen.queryByRole("button", { name: /仍然加入/ })).not.toBeInTheDocument();
    spy.mockRestore();
  });
});

describe("从备选岗位导入", () => {
  afterEach(cleanup);

  it("用详情那份预填表单，而不是列表那一行", async () => {
    // **这条守的是一个已经发生过的缺陷**：候选有两条来路，字段分布正好相反——手工粘贴的只有
    // raw_text，而采集来的内容全在 description/requirements 里、raw_text 是空的。
    // 而「导入到岗位」原先只预填 raw_text，于是采集来的候选打开的是一个**全空的表单**，
    // 用户看到的就是"导入进来什么都没有"——数据其实一直都在。
    //
    // 列表接口也刻意不带 JD（最多 300 条 × 单条上限几万字符），所以要取详情那一条。
    candidateMocks.listCandidateJobs.mockResolvedValue([
      makeCandidate({ id: 9, title: "后端开发工程师", raw_text: "" }),
    ]);
    candidateMocks.getCandidateJob.mockResolvedValue(
      makeCandidateDetail({
        id: 9,
        title: "后端开发工程师",
        description: "负责服务端开发与维护，参与架构演进。",
        requirements: "三年以上后端经验。",
      }),
    );
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /备选岗位/ }));
    fireEvent.click(await screen.findByRole("button", { name: "导入到岗位" }));

    await waitFor(() => expect(candidateMocks.getCandidateJob).toHaveBeenCalledWith(9));
    // 表单里职位描述那一栏要有内容——这才叫"导入进来了"。
    const description = await screen.findByLabelText("职位描述（JD）");
    await waitFor(() => expect(description).toHaveValue("负责服务端开发与维护，参与架构演进。"));
    expect(screen.getByLabelText("职位名称")).toHaveValue("后端开发工程师");
  });

  it("从采集记录跳转时只加载对应批次，并自动打开备选岗位", async () => {
    candidateMocks.listCandidateJobs.mockResolvedValue([
      makeCandidate({ id: 12, title: "官网后端工程师", collect_task_id: 8 }),
    ]);
    renderPage(["/jobs?collect_task_ids=8,9"]);

    await waitFor(() =>
      expect(candidateMocks.listCandidateJobs).toHaveBeenCalledWith({ collectTaskIds: [8, 9] }),
    );
    expect(await screen.findByText(/这里只显示选中采集记录的岗位/)).toBeInTheDocument();
    expect(screen.getByText("官网后端工程师")).toBeInTheDocument();
  });

  it("点击备选岗位卡片会读取并展示完整详情", async () => {
    const candidate = makeCandidate({ id: 21, title: "数据分析师" });
    candidateMocks.listCandidateJobs.mockResolvedValue([candidate]);
    candidateMocks.getCandidateJob.mockResolvedValue(
      makeCandidateDetail({
        id: 21,
        title: "数据分析师",
        description: "负责业务数据分析。",
        requirements: "熟悉 SQL。",
      }),
    );
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /备选岗位/ }));
    fireEvent.click(await screen.findByText("数据分析师"));

    await waitFor(() => expect(candidateMocks.getCandidateJob).toHaveBeenCalledWith(21));
    expect(await screen.findByText("负责业务数据分析。")).toBeInTheDocument();
    expect(screen.getByText("熟悉 SQL。")).toBeInTheDocument();
  });

  it("可以批量导入选中的备选岗位", async () => {
    candidateMocks.listCandidateJobs.mockResolvedValue([
      makeCandidate({ id: 31, title: "岗位一" }),
      makeCandidate({ id: 32, title: "岗位二" }),
    ]);
    candidateMocks.importCandidateJobs.mockResolvedValue({
      imported: 2,
      duplicate: 0,
      trashed: 0,
      invalid: 0,
      missing: 0,
      results: [],
    });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /备选岗位/ }));
    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    fireEvent.click(checkboxes[2]);
    fireEvent.click(screen.getByRole("button", { name: "批量导入" }));

    await waitFor(() => expect(candidateMocks.importCandidateJobs).toHaveBeenCalledWith([31, 32]));
  });
});
