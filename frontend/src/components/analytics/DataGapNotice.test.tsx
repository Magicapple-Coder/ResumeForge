/** 数据缺口提示：整页唯一的"这张图为什么是空的"实现。 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DataGapNotice from "./DataGapNotice";

describe("DataGapNotice", () => {
  it("有缺口时说明缺了多少、为什么，并给出可用的条数", () => {
    render(<DataGapNotice missing={3} available={9} label="投递未填「投递日期」" />);

    expect(screen.getByText(/有 3 条投递未填「投递日期」/)).toBeInTheDocument();
    // 把话说全：9 条计入、3 条没计入，比单说"缺 3 条"更不容易被误读。
    expect(screen.getByText(/共 12 条/)).toBeInTheDocument();
  });

  it("没有缺口时什么都不渲染，不留空占位", () => {
    const { container } = render(
      <DataGapNotice missing={0} available={5} label="投递未填「投递日期」" />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("渲染传入的补充入口", () => {
    render(
      <DataGapNotice missing={1} label="投递没有关联简历" action={<a href="/tracker">去补充</a>} />,
    );

    expect(screen.getByRole("link", { name: "去补充" })).toBeInTheDocument();
  });
});
