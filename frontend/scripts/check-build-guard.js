#!/usr/bin/env node
/*
 * Programme 02 / W8: `npm run build:check` — proves the build's static checks still CATCH the defect classes they exist for.
 * Each fixture below is linted IN MEMORY (ESLint `lintText`, nothing is written to src/) with the same ESLint engine and the same
 * .eslintrc.js the production build uses, and must produce the expected rule as an ERROR (errors fail `npm run build`).
 * It also checks that craco.config.js still hands linting to .eslintrc.js (eslint.mode = "file").
 * Exit 0 = every guard holds; exit 1 = a check stopped catching its defect (someone weakened the configuration).
 */
const path = require("path");
const { ESLint } = require(require.resolve("eslint", { paths: [path.dirname(require.resolve("react-scripts/package.json"))] }));

const ROOT = path.resolve(__dirname, "..");
const SRC = path.join(ROOT, "src");

const FIXTURES = [
  { name: "undefined variable in a handler", rule: "no-undef",
    code: 'export default function C() { return <button onClick={() => handleMissing()}>x</button>; }' },
  { name: "misspelled reference", rule: "no-undef",
    code: 'import { useState } from "react";\nexport function C() { const [v] = useState(0); return <p>{valeu}</p>; }' },
  { name: "Product Studio regression: prop used outside its component scope (Programme 01 Images / Documents steps)", rule: "no-undef",
    code: 'import { ImageInput } from "@/components/vendor/ImageInput";\n' +
          'export function ProductStudio({ base }) { return <Media />; }\n' +
          'function Media({ data }) { return <ImageInput admin={base === "/admin/pim"} value={[]} onChange={() => {}} />; }' },
  { name: "undefined JSX component (missing import)", rule: "react/jsx-no-undef",
    code: 'export default function C() { return <MissingWidget />; }' },
  { name: "unresolved '@/' alias import", rule: "import/no-unresolved",
    code: 'import x from "@/lib/does-not-exist";\nexport default x;' },
  { name: "broken relative import", rule: "import/no-unresolved",
    code: 'import x from "./definitely-missing-module";\nexport default x;' },
  { name: "unresolved package", rule: "import/no-unresolved",
    code: 'import x from "not-a-real-package-w8";\nexport default x;' },
  { name: "invalid named import", rule: "import/named",
    code: 'import { NoSuchExportW8 } from "@/lib/api";\nexport default NoSuchExportW8;' },
  { name: "duplicate object key", rule: "no-dupe-keys",
    code: 'export const o = { a: 1, a: 2 };' },
  { name: "conditional hook call", rule: "react-hooks/rules-of-hooks",
    code: 'import { useState } from "react";\nexport function C({ on }) { if (on) { useState(0); } return null; }' },
  { name: "redeclared binding", rule: "no-redeclare",
    code: 'var a = 1;\nvar a = 2;\nexport default a;' },
  { name: "unreachable code", rule: "no-unreachable",
    code: 'export function f() { return 1;\n  console.log("never"); }' },
];

(async () => {
  let failed = 0;
  const craco = require(path.join(ROOT, "craco.config.js"));
  if (!craco.eslint || craco.eslint.mode !== "file") {
    console.error('✖ craco.config.js no longer sets eslint.mode = "file": the build would not lint with .eslintrc.js');
    failed++;
  } else {
    console.log('✓ craco.config.js: the build lints with .eslintrc.js (eslint.mode = "file")');
  }
  // import/no-cycle needs the linted file to exist on disk; these fixtures are virtual and do not test cycles, so only here it is off
  // (the build and `npm run lint` keep it).
  const eslint = new ESLint({ cwd: ROOT, useEslintrc: true, cache: false, overrideConfig: { rules: { "import/no-cycle": "off" } } });
  for (const [i, f] of FIXTURES.entries()) {
    const filePath = path.join(SRC, `__w8_guard_fixture_${i}__.js`);      // virtual file: never written to disk
    const [res] = await eslint.lintText(f.code, { filePath });
    const hit = res.messages.find((m) => m.ruleId === f.rule && m.severity === 2);
    if (hit) {
      console.log(`✓ ${f.name}: ${f.rule} error — "${hit.message}"`);
    } else {
      failed++;
      console.error(`✖ ${f.name}: expected an ERROR from ${f.rule}; got ${JSON.stringify(res.messages.map((m) => [m.ruleId, m.severity]))}`);
    }
  }
  console.log(failed ? `\n${failed} guard(s) FAILED` : `\nAll ${FIXTURES.length + 1} build guards hold.`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
