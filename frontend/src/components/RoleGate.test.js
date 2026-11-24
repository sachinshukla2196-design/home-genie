import React, { act } from "react";
import { createRoot } from "react-dom/client";

// Programme 02 / W7: RoleGate renders the page only for the roles the server allows, and otherwise shows a note WITHOUT mounting
// the page (so the page cannot fire a request the server would refuse).
let mockUser = null;
jest.mock("@/context/AuthContext", () => ({ useAuth: () => ({ user: mockUser }) }));
const { RoleGate } = require("@/components/RoleGate");
const { can, rolesText, ROLE_SETS } = require("@/lib/roles");

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function mount(node) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(node));
  return { el, unmount: () => act(() => root.unmount()) };
}

function Probe({ onMount }) {
  React.useEffect(() => { onMount(); }, [onMount]);
  return <p>secret page</p>;
}

test("an allowed role gets the page", () => {
  mockUser = { role: "accounts_admin" };
  const mounted = jest.fn();
  const { el, unmount } = mount(<RoleGate set="finance" what="Payment events"><Probe onMount={mounted} /></RoleGate>);
  expect(el.textContent).toContain("secret page");
  expect(mounted).toHaveBeenCalledTimes(1);
  unmount();
});

test("a refused role gets the note and the page is never mounted", () => {
  mockUser = { role: "support_admin" };
  const mounted = jest.fn();
  const { el, unmount } = mount(<RoleGate set="finance" what="Payment events"><Probe onMount={mounted} /></RoleGate>);
  expect(el.textContent).not.toContain("secret page");
  expect(el.textContent).toContain("Payment events is available to the super admin and accounts admin only");
  expect(mounted).not.toHaveBeenCalled();
  unmount();
});

test("no signed-in user is never allowed", () => {
  expect(can(null, "finance")).toBe(false);
  expect(can({ role: "super_admin" }, "unknown-set")).toBe(false);
});

test("role sets read as plain words", () => {
  expect(rolesText("superAdmin")).toBe("super admin");
  expect(rolesText("vendorApplications")).toBe("super admin, admin and support admin");
  expect(Object.keys(ROLE_SETS)).toEqual(expect.arrayContaining(["finance", "codConfirm", "contentEditor"]));
});
