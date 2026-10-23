import fs from "fs";
import path from "path";
import { vendorPanel } from "@/i18n/vendorPanel";
import { translations } from "@/i18n/translations";

const ph = (s) => (s.match(/\{[a-z]+\}/gi) || []).sort().join(",");
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => {
  const p = path.join(d, e.name);
  return e.isDirectory() ? walk(p) : /\.js$/.test(e.name) && !/\.test\.js$/.test(e.name) && !/i18n/.test(p) ? [p] : [];
});

test("vendor panel EN and HI define the same keys, none empty, same placeholders", () => {
  const en = vendorPanel.en, hi = vendorPanel.hi;
  expect(Object.keys(hi).sort()).toEqual(Object.keys(en).sort());
  for (const k of Object.keys(en)) {
    expect(en[k].trim()).not.toBe("");
    expect(hi[k].trim()).not.toBe("");
    expect([k, ph(hi[k])]).toEqual([k, ph(en[k])]);
  }
});

test("every statically referenced vx./vp. key exists in both languages", () => {
  const src = walk(path.join(__dirname, ".."));
  const keys = new Set();
  for (const f of src) for (const m of fs.readFileSync(f, "utf8").matchAll(/\bt\(\s*"((?:vx|vp)\.[A-Za-z0-9_.]+)"/g)) keys.add(m[1]);
  expect(keys.size).toBeGreaterThan(100);
  const missing = [...keys].filter((k) => !translations.en[k] || !translations.hi[k]);
  expect(missing).toEqual([]);
});
