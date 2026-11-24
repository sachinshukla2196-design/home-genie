/*
 * Programme 02 / W8: lets eslint-plugin-import resolve the app's "@/..." import alias (webpack alias + jsconfig "paths": "@/*" ->
 * "./src/*"), so `import/no-unresolved`, `import/named` and `import/default` check those imports too. Every other import is
 * resolved exactly like Node / webpack would (the stock node resolver that ships with eslint-plugin-import). No new dependency.
 */
const path = require("path");
const nodeResolver = require("eslint-import-resolver-node");

const SRC = path.resolve(__dirname, "..", "src");

exports.interfaceVersion = 2;
exports.resolve = (source, file, config) => {
  const target = source.startsWith("@/") ? path.join(SRC, source.slice(2)) : source;
  const res = nodeResolver.resolve(target, file, { extensions: [".js", ".jsx", ".json"], ...(config || {}) });
  if (res.found || target.startsWith(".") || path.isAbsolute(target)) return res;
  // A package that only declares an "exports" map (no "main", e.g. react-resizable-panels 3) is invisible to the stock node
  // resolver; ask Node itself, which applies the "exports" map the same way the bundler does.
  try {
    return { found: true, path: require.resolve(target, { paths: [path.dirname(file)] }) };
  } catch (e) {
    return { found: false };
  }
};
