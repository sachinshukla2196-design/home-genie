import React from "react";
import { motion } from "framer-motion";
import { Mail, Phone, MapPin, LifeBuoy } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { IdCard } from "@/components/IdCard";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";

export default function Profile() {
  const { t } = useI18n();
  const { user, logout } = useAuth();

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.profile")}</h1>
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-forest font-display text-xl font-semibold text-white">{(user?.full_name || "U").slice(0, 2).toUpperCase()}</div>
          <div>
            <div className="font-display text-xl font-semibold text-ink">{user?.full_name}</div>
            <div className="mt-1 flex items-center gap-2 text-sm"><span className="font-semibold text-forest" data-testid="profile-distributor-id">{user?.distributor_id}</span><StatusBadge status={user?.status} size="sm" /></div>
          </div>
        </div>
        <div className="mt-6 space-y-3 text-sm">
          <Row icon={Mail} value={user?.email} />
          <Row icon={Phone} value={user?.mobile} />
          <Row icon={MapPin} value={[user?.address, user?.city, user?.state, user?.pincode].filter(Boolean).join(", ") || "—"} />
        </div>
        {user?.sponsor_id && <div className="mt-4 rounded-lg bg-brand-50 px-4 py-2.5 text-sm text-forest">Sponsor: <b>{user.sponsor_id}</b></div>}
      </motion.div>

      <IdCard user={user} />

      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <div className="flex items-center gap-2 font-medium text-ink"><LifeBuoy size={18} className="text-brand" /> {t("nav.support")}</div>
        <p className="mt-1 text-sm text-muted2">Need help? Reach our support team.</p>
        <a href="mailto:care@anjaliherballife.in" className="mt-3 inline-block text-sm font-medium text-brand hover:underline" data-testid="support-email">care@anjaliherballife.in</a>
      </div>

      <Button onClick={logout} variant="outline" className="w-full rounded-full border-danger/30 text-danger hover:bg-danger/10" data-testid="profile-logout">{t("nav.logout")}</Button>
    </div>
  );
}

function Row({ icon: Icon, value }) {
  return <div className="flex items-center gap-3 text-muted2"><Icon size={16} className="text-brand" /> <span className="text-ink">{value}</span></div>;
}
