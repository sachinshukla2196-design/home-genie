import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Heart } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

/** Batch 13, Phase 7B: save / unsave a product on the server-side wishlist. Saving never reserves stock or price. */
export function WishButton({ productId, variantSku = "", className = "" }) {
  const { user } = useAuth();
  const { t } = useI18n();
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!user) return;
    API.get("/wishlist/ids").then(({ data }) => setOn((data.items || []).some((i) => i.product_id === productId && (i.variant_sku || "") === (variantSku || "").toUpperCase())))
      .catch(() => {});
  }, [user, productId, variantSku]);
  if (!user) return null;
  const toggle = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (on) await API.delete(`/wishlist/${productId}`, { params: { variant_sku: variantSku || "" } });
      else await API.post("/wishlist", { product_id: productId, variant_sku: variantSku || "" });
      setOn(!on);
      toast.success(on ? t("wish.removed") : t("wish.added"));
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  return (
    <button type="button" onClick={toggle} aria-pressed={on} aria-label={on ? t("wish.remove") : t("wish.save")} data-testid="wish-toggle"
      className={`inline-flex h-11 items-center justify-center gap-2 rounded-full px-4 text-sm font-semibold ring-1 ring-brand-100 hover:bg-brand-50 ${className}`}>
      <Heart size={18} className={on ? "fill-danger text-danger" : "text-ink"} /> {on ? t("wish.saved") : t("wish.save")}
    </button>
  );
}
