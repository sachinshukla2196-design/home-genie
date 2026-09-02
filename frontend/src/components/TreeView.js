import React from "react";

function flatten(node, depth, out) {
  if (!node) return;
  out.push({ ...node, depth });
  (node.children || []).forEach((c) => flatten(c, depth + 1, out));
}

export function TreeView({ tree, testid }) {
  if (!tree) return <p className="text-sm text-muted2">No network yet.</p>;
  const rows = [];
  flatten(tree, 0, rows);
  return (
    <div data-testid={testid} className="overflow-x-auto">
      {rows.map((n) => {
        const green = n.status === "green";
        return (
          <div key={n.distributor_id} style={{ marginLeft: n.depth * 18 }} className="flex items-center gap-2 border-l border-brand-50 py-1 pl-3">
            <span className="font-mono text-sm font-semibold text-forest">{n.distributor_id}</span>
            {n.name ? <span className="text-xs text-muted2">{n.name}</span> : null}
            {n.status ? <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${green ? "bg-brand-50 text-brand" : "bg-danger/10 text-danger"}`}>{n.status.toUpperCase()}</span> : null}
          </div>
        );
      })}
    </div>
  );
}
