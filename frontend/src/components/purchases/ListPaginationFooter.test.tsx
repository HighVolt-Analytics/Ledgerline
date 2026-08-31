/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";
import {
  paginationItems,
  TableCirclePagination,
} from "@/components/purchases/ListPaginationFooter";

afterEach(() => {
  cleanup();
});

describe("paginationItems", () => {
  it("returns a single page", () => {
    expect(paginationItems(1, 1)).toEqual([1]);
  });

  it("lists every page when there are five or fewer", () => {
    expect(paginationItems(2, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it("keeps first and last with an ellipsis in the gap", () => {
    expect(paginationItems(2, 8)).toEqual([1, 2, 3, "ellipsis", 8]);
    expect(paginationItems(7, 8)).toEqual([1, "ellipsis", 6, 7, 8]);
    expect(paginationItems(4, 10)).toEqual([1, "ellipsis", 3, 4, 5, "ellipsis", 10]);
  });
});

describe("TableCirclePagination", () => {
  it("shows total and circled page numbers without a page-size control", () => {
    render(
      <TableCirclePagination page={2} totalPages={5} total={47} onPageChange={vi.fn()} />
    );

    expect(screen.getByText("Total")).toBeTruthy();
    expect(screen.getByText("47")).toBeTruthy();
    expect(screen.queryByText(/lines per page/i)).toBeNull();
    expect(screen.queryByText(/per page/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Page 2" }).getAttribute("aria-current")).toBe(
      "page"
    );
    expect(screen.getByRole("button", { name: "Previous page" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Next page" })).toBeTruthy();
  });
});
