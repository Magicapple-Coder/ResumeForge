/**
 * 助手技能卡片：重点是"拖进来也能导入"。
 *
 * 拖拽容器是后加的，容易只挂上去却没接到导入路径上——点按钮能导入、拖文件没反应，
 * 而两条路各自看代码都没问题。所以这里对拖拽单独断言一次。
 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SkillsCard from "./SkillsCard";

function renderCard(overrides: Partial<Parameters<typeof SkillsCard>[0]> = {}) {
  const props = {
    skills: [],
    loading: false,
    importing: false,
    togglingId: null,
    deletingId: null,
    onImport: vi.fn(),
    onToggle: vi.fn(),
    onDelete: vi.fn(),
    onOpen: vi.fn(),
    ...overrides,
  };
  render(
    <AntdApp>
      <SkillsCard {...props} />
    </AntdApp>,
  );
  return props;
}

afterEach(cleanup);

describe("SkillsCard", () => {
  it("imports a skill pack dropped onto the button", () => {
    const props = renderCard();

    const dropped = new File(["---\nname: 面试\n---\n要求"], "面试.md", { type: "text/markdown" });
    const zone = screen.getByRole("button", { name: /导入技能/ }).parentElement?.parentElement;
    fireEvent.drop(zone as HTMLElement, { dataTransfer: { files: [dropped], types: ["Files"] } });

    expect(props.onImport).toHaveBeenCalledWith(dropped);
  });

  it("refuses a file type the importer cannot read", () => {
    const props = renderCard();

    const zone = screen.getByRole("button", { name: /导入技能/ }).parentElement?.parentElement;
    fireEvent.drop(zone as HTMLElement, {
      dataTransfer: {
        files: [new File(["x"], "简历.pdf", { type: "application/pdf" })],
        types: ["Files"],
      },
    });

    expect(props.onImport).not.toHaveBeenCalled();
    expect(screen.getByText("技能只支持 .md 或 .zip")).toBeInTheDocument();
  });

  it("ignores drops while an import is already running", () => {
    const props = renderCard({ importing: true });

    const zone = screen.getByRole("button", { name: /导入技能/ }).parentElement?.parentElement;
    fireEvent.drop(zone as HTMLElement, {
      dataTransfer: { files: [new File(["x"], "面试.md")], types: ["Files"] },
    });

    expect(props.onImport).not.toHaveBeenCalled();
  });
});
