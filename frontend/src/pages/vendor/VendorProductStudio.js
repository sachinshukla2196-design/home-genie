import React, { useEffect, useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Loader2 } from "lucide-react";
import { API, apiError } from "@/lib/api";
import { ProductStudio } from "@/components/catalogue/ProductStudio";

/** /vendor/products/new, /vendor/products/:productId/edit (open a draft for it) and /vendor/products/studio/:draftId. */
export default function VendorProductStudio() {
  const { draftId, productId } = useParams();
  const navigate = useNavigate();
  const started = useRef(false);

  useEffect(() => {
    if (draftId || started.current) return;
    started.current = true;
    API.post("/vendor/pim/drafts", productId ? { product_id: productId } : {})
      .then(({ data }) => navigate(`/vendor/products/studio/${data.id}`, { replace: true }))
      .catch((e) => { toast.error(apiError(e)); navigate("/vendor/products", { replace: true }); });
  }, [draftId, productId, navigate]);

  if (!draftId) return <div className="flex items-center gap-2 p-8 text-muted2"><Loader2 className="animate-spin" size={18} /> Opening the product…</div>;
  return (
    <ProductStudio base="/vendor/pim" draftId={draftId} onDone={() => navigate("/vendor/products")}
      header={<Link to="/vendor/products" className="mb-1 inline-flex items-center gap-1 text-xs text-muted2 hover:text-ink"><ArrowLeft size={13} /> Products</Link>} />
  );
}
