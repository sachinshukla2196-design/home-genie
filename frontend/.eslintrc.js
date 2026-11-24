/*
 * Programme 02 / W8 — the ONE ESLint configuration for this app. It is used by:
 *   - the production build (CRA's webpack ESLint plugin; craco.config.js `eslint.mode = "file"`): any ERROR below fails `npm run build`;
 *   - `npm run lint` (scripts/lint.js, same ESLint engine as the build) over every file in src/, including files not yet imported.
 *
 * Why this file exists: CRA 5 lints the build with only `eslint-config-react-app/base` (parser + environments, no correctness rules)
 * and expects the project to extend "react-app" itself. This project never did — craco.config.js only merged the react-hooks rules —
 * so undefined names compiled (Batch 13 dashboard crash; Programme 01 product-studio Images / Documents step crash).
 *
 * Errors are reserved for defects that break or corrupt behaviour; conventions stay warnings so the build is not flooded.
 */
const path = require("path");

module.exports = {
  root: true,
  extends: ["react-app"],          // CRA's full rule set: no-undef, react/jsx-no-undef, react-hooks, restricted globals, …
  env: { es2020: true },           // standard ES2020 globals (e.g. globalThis); CRA's base declares only ES6
  settings: {
    "import/resolver": { [path.resolve(__dirname, "scripts/eslint-alias-resolver.js")]: {} },
    "import/extensions": [".js", ".jsx"],
  },
  rules: {
    // A. undefined identifiers (functions, variables, components, handlers, accidental globals)
    "no-undef": "error",
    "react/jsx-no-undef": ["error", { allowGlobals: false }],
    // B. import and module integrity (the "@/" alias included)
    "import/no-unresolved": ["error", { commonjs: true, caseSensitive: true }],
    "import/named": "error",
    "import/default": "error",
    "import/no-duplicates": "warn",
    "import/no-cycle": ["warn", { maxDepth: 4, ignoreExternal: true }],
    // C. React correctness
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",
    "react/jsx-no-duplicate-props": "error",
    "react/jsx-key": ["warn", { checkFragmentShorthand: true }],
    // D. general correctness (duplicates, conflicting declarations, assignments to constants / imports, unreachable code)
    "no-dupe-keys": "error",
    "no-dupe-class-members": "error",
    "no-redeclare": "error",
    "no-const-assign": "error",
    "no-func-assign": "error",
    "no-import-assign": "error",
    "no-unreachable": "error",
    "no-unused-vars": ["warn", { args: "none", ignoreRestSiblings: true }],
  },
};
