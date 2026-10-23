import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { Pager, SearchBox, useDebounced } from "@/components/Pager";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const t = (k) => ({ "vp.results": "results", "vp.prev": "Previous", "vp.next": "Next", "vp.page": "Page" }[k] || k);

function mount(node) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(node));
  return { el, root };
}
const byId = (el, id) => el.querySelector(`[data-testid="${id}"]`);

test("shows page x / y, total, and enables only the valid direction", () => {
  const onPage = jest.fn();
  const { el } = mount(<Pager page={2} pages={3} total={41} onPage={onPage} t={t} testid="p" />);
  expect(el.textContent).toContain("Page 2 / 3");
  expect(el.textContent).toContain("41 results");
  act(() => byId(el, "p-next").click());
  act(() => byId(el, "p-prev").click());
  expect(onPage.mock.calls).toEqual([[3], [1]]);
});

test("first page disables Previous, last page disables Next, and clicks do nothing when disabled", () => {
  const onPage = jest.fn();
  const first = mount(<Pager page={1} pages={3} total={30} onPage={onPage} t={t} testid="a" />).el;
  expect(byId(first, "a-prev").disabled).toBe(true);
  expect(byId(first, "a-next").disabled).toBe(false);
  const last = mount(<Pager page={3} pages={3} total={30} onPage={onPage} t={t} testid="b" />).el;
  expect(byId(last, "b-next").disabled).toBe(true);
  act(() => byId(last, "b-next").click());
  expect(onPage).not.toHaveBeenCalled();
});

test("a single page shows only the result count; no results shows nothing", () => {
  const one = mount(<Pager page={1} pages={1} total={2} onPage={() => {}} t={t} testid="c" />).el;
  expect(one.textContent).toBe("2 results");
  expect(one.querySelector("button")).toBeNull();
  expect(mount(<Pager page={1} pages={1} total={0} onPage={() => {}} t={t} />).el.textContent).toBe("");
});

test("search box reports typing, is labelled, and limits length to 80", () => {
  const onChange = jest.fn();
  const { el } = mount(<SearchBox value="" onChange={onChange} placeholder="Search order no." testid="s" />);
  const input = byId(el, "s");
  expect(input.getAttribute("aria-label")).toBe("Search order no.");
  expect(input.maxLength).toBe(80);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  act(() => { setter.call(input, "saree"); input.dispatchEvent(new Event("input", { bubbles: true })); });
  expect(onChange).toHaveBeenCalledWith("saree");
});

test("useDebounced waits for typing to pause before updating", () => {
  jest.useFakeTimers();
  const seen = [];
  function Probe({ v }) { seen.push(useDebounced(v, 300)); return null; }
  const el = document.createElement("div");
  const root = createRoot(el);
  act(() => root.render(<Probe v="a" />));
  act(() => root.render(<Probe v="ab" />));
  act(() => { jest.advanceTimersByTime(299); });
  expect(seen[seen.length - 1]).toBe("a");        // still the old value: user is still typing
  act(() => { jest.advanceTimersByTime(2); });
  expect(seen[seen.length - 1]).toBe("ab");
  jest.useRealTimers();
});
