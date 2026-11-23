import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { API } from "@/lib/api";

const money = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

/** Batch 13, Phase 10: the shop home's live merchandising sections from GET /api/merch/home (published, inside their dates,
 *  only products on sale and in stock). Nothing here is hardcoded; with no live sections nothing is rendered. */
export function MerchSections({ onLoaded }) {
  const [secs, setSecs] = useState([]);
  const navigate = useNavigate();
  useEffect(() => {
    API.get("/merch/home").then(({ data }) => { setSecs(data.sections || []); onLoaded && onLoaded(data.sections || []); }).catch(() => {});
  }, [onLoaded]);
  if (!secs.length) return null;
  return (
    <div className="space-y-5" data-testid="merch-sections">
      {secs.map((s) => {
        if (s.kind === "banner") {
          const img = (
            <picture>
              {s.image_mobile && <source media="(max-width: 640px)" srcSet={s.image_mobile} />}
              <img src={s.image_desktop} alt={s.alt} className="h-40 w-full rounded-3xl object-cover sm:h-56" loading="lazy" />
            </picture>
          );
          return (
            <section key={s.id} aria-label={s.title} className="relative overflow-hidden rounded-3xl" data-testid="merch-banner">
              {s.link ? <Link to={s.link}>{img}</Link> : img}
              {(s.title || s.subtitle) && <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/55 to-transparent p-4 text-white">
                <div className="font-display text-lg font-semibold sm:text-2xl">{s.title}</div>{s.subtitle && <div className="text-sm text-white/85">{s.subtitle}</div>}</div>}
            </section>
          );
        }
        if (s.kind === "featured_categories") {
          return (
            <section key={s.id} aria-label={s.title}>
              <h2 className="mb-2 font-display text-lg font-semibold text-ink">{s.title}</h2>
              <div className="flex flex-wrap gap-2">{s.categories.map((c) => <Link key={c} to={`/app/products?category=${encodeURIComponent(c)}`} className="hg-chip-off rounded-full px-4 py-2 text-sm font-medium">{c}</Link>)}</div>
            </section>
          );
        }
        return (
          <section key={s.id} aria-label={s.title} data-testid="merch-products">
            <div className="mb-2 flex items-baseline justify-between gap-2"><h2 className="font-display text-lg font-semibold text-ink">{s.title}</h2>
              {s.link && <Link to={s.link} className="text-sm font-medium text-hg-violet">See all</Link>}</div>
            {s.subtitle && <p className="-mt-1 mb-2 text-sm text-muted2">{s.subtitle}</p>}
            <div className="no-scrollbar -mx-4 flex gap-3 overflow-x-auto px-4 pb-1">
              {s.products.map((p) => (
                <button key={p.id} onClick={() => navigate(`/app/products/${p.id}`)} className="hg-card w-40 shrink-0 overflow-hidden text-left sm:w-48">
                  {p.images?.[0] ? <img src={p.images[0]} alt={p.name} className="aspect-square w-full object-cover" loading="lazy" /> : <div className="aspect-square w-full bg-brand-50" />}
                  <div className="p-2.5"><div className="line-clamp-2 text-sm font-medium text-ink">{p.name}</div><div className="mt-1 font-display font-semibold">{money(p.selling_price)}</div></div>
                </button>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
