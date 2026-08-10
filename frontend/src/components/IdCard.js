import React, { useEffect, useRef, useState } from "react";
import { toPng } from "html-to-image";
import QRCode from "qrcode";
import { toast } from "sonner";
import { Download, Printer, Share2, Leaf } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";

export function IdCard({ user }) {
  const { t } = useI18n();
  const cardRef = useRef(null);
  const [qr, setQr] = useState("");
  const green = user?.status === "green";
  const refLink = `${window.location.origin}/register?ref=${user?.distributor_id}`;
  const since = (user?.created_at || "").slice(0, 10) || "—";

  useEffect(() => {
    QRCode.toDataURL(refLink, { margin: 1, width: 240, color: { dark: "#0B4D2E", light: "#ffffff" } })
      .then(setQr).catch(() => {});
  }, [refLink]);

  const render = async () => {
    return toPng(cardRef.current, { pixelRatio: 3, cacheBust: true, skipFonts: true, backgroundColor: "#ffffff" });
  };

  const download = async () => {
    try {
      const url = await render();
      const a = document.createElement("a");
      a.href = url; a.download = `${user?.distributor_id}-anjali-id-card.png`; a.click();
      toast.success("ID card downloaded");
    } catch (e) { console.error(e); toast.error("Could not generate the card. Please try again."); }
  };

  const share = async () => {
    try {
      const url = await render();
      const blob = await (await fetch(url)).blob();
      const file = new File([blob], `${user?.distributor_id}-id-card.png`, { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: "My Anjali Herbal Life ID", text: `Distributor ${user?.distributor_id}` });
      } else if (navigator.share) {
        await navigator.share({ title: "My Anjali Herbal Life ID", text: `Distributor ${user?.distributor_id}`, url: refLink });
      } else {
        await download();
      }
    } catch (e) { if (e?.name !== "AbortError") { console.error(e); toast.error("Sharing not supported on this device."); } }
  };

  const print = async () => {
    try {
      const url = await render();
      const w = window.open("", "_blank");
      w.document.write(`<html><head><title>ID Card</title></head><body style="margin:0;display:flex;justify-content:center;align-items:center;height:100vh;background:#F7F9F7"><img src="${url}" style="width:520px;max-width:92vw"/></body></html>`);
      w.document.close();
      setTimeout(() => { w.focus(); w.print(); }, 400);
    } catch (e) { console.error(e); toast.error("Could not open print view."); }
  };

  return (
    <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="id-card-section">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-display text-lg font-medium text-ink">Distributor ID Card</h3>
      </div>

      {/* The card */}
      <div ref={cardRef} className="relative mx-auto w-full max-w-[420px] overflow-hidden rounded-2xl text-white"
        style={{ aspectRatio: "1.6 / 1", background: "linear-gradient(135deg,#0B4D2E 0%,#176B43 60%,#0B4D2E 100%)" }}
        data-testid="id-card">
        <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full" style={{ background: "rgba(201,162,39,0.18)" }} />
        <div className="absolute inset-0 flex flex-col justify-between p-5">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-full" style={{ background: "linear-gradient(145deg,#176B43,#0B4D2E)", boxShadow: "0 0 0 2px #C9A227" }}>
                <Leaf size={18} color="#F6EFD5" />
              </div>
              <div className="leading-tight">
                <div className="text-[13px] font-semibold">Anjali <span style={{ color: "#C9A227" }}>Herbal Life</span></div>
                <div className="text-[8px] tracking-[0.18em] text-white/60">AYURVEDA INDIA LLP</div>
              </div>
            </div>
            <span className="rounded-full px-2.5 py-1 text-[10px] font-bold"
              style={{ background: green ? "rgba(255,255,255,0.16)" : "rgba(198,40,40,0.9)", color: green ? "#C9A227" : "#fff" }}>
              {green ? "GREEN ID" : "RED ID"}
            </span>
          </div>

          <div className="flex items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[9px] uppercase tracking-wider text-white/50">Distributor ID</div>
              <div className="font-display text-2xl font-bold" style={{ color: "#F6EFD5" }}>{user?.distributor_id}</div>
              <div className="mt-2 text-[9px] uppercase tracking-wider text-white/50">Name</div>
              <div className="truncate text-sm font-semibold">{user?.full_name}</div>
              <div className="mt-2 text-[10px] text-white/60">Member since {since}</div>
            </div>
            {qr && (
              <div className="rounded-lg bg-white p-1.5">
                <img src={qr} alt="QR" className="h-[70px] w-[70px]" crossOrigin="anonymous" />
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <Button onClick={download} className="rounded-full bg-forest hover:bg-brand" data-testid="idcard-download"><Download size={15} className="mr-1.5" /> Download</Button>
        <Button onClick={share} variant="outline" className="rounded-full border-forest/20 text-forest hover:bg-brand-50" data-testid="idcard-share"><Share2 size={15} className="mr-1.5" /> Share</Button>
        <Button onClick={print} variant="outline" className="rounded-full border-forest/20 text-forest hover:bg-brand-50" data-testid="idcard-print"><Printer size={15} className="mr-1.5" /> Print</Button>
      </div>
    </div>
  );
}
