# HOME GENIE Marketing Studio — Architecture (design only)

Status: **design proposal, nothing built.** Based on inspection of `main @ d31cb74`. Companion document:
`docs/HOME_GENIES_INTEGRATION_REGISTER.md`.

The Marketing Studio helps an active HomeGenie promote **approved HOME GENIES products** and see which of their shares led
to **genuine, paid orders**. It is a sales tool, not a messaging robot: every message is sent by a person from their own
app unless and until HOME GENIES runs an officially approved WhatsApp Business Platform number (Phase 3).

---

## 0. Non-negotiable business rules (enforced by design)

| Rule | How the design enforces it |
|---|---|
| Marketing tied to genuine product sales only | Links point only at products/shop pages. Earnings stay in the existing commission engine (`commission.py`), which pays only on PAID orders. Clicks, enquiries, shares and posters never earn anything. |
| No recruitment-based earnings | The studio never generates `/register?ref=` (sponsor) links. Templates are reviewed for income/recruitment claims; a banned-phrase check blocks "earn ₹…", "join my team", "passive income". |
| No unauthorised bulk messaging / no spam automation | MVP sends nothing itself. Sharing opens the member's own WhatsApp/app via `wa.me`, the Web Share API, or copy. No scheduling that auto-sends, no contact upload, no batch send. Phase 3 WhatsApp API sends only from a HOME GENIES-owned number to customers with recorded opt-in. |
| No scraping | No Contact Picker API, no phone-book import, no reading of social followers/groups. No unofficial/private APIs or browser automation of WhatsApp/Instagram. |
| No fabricated analytics | Only first-party facts: link clicks recorded by our redirect, orders/payments/returns from `orders`, money from `commissions`. No "reach", "views", "impressions" or forwards (we cannot measure them). Estimates are labelled as such (e.g. "unique visitors, approximate"). |
| Only approved products with current pricing | Link creation and landing both apply the shop visibility rule (`shop_routes.SHOP_VISIBLE`: approved, active, not archived). Captions/posters resolve price at render time from `products.selling_price` (or variant price) and stamp the date; a price change marks saved creatives stale. |
| Link must preserve correct attribution | Section 2. The existing rule is kept exactly; the new link only adds a server-verified link id and channel. |
| Reuse the HOME GENIES design system | Cream/chocolate/gold Tailwind tokens (`tailwind.config.js` `cream`, `choco`, `gold`, `hg-*`), `hg-card`, `hg-tile`, `hg-btn`, `PageHeader`, `StatCard`, `EmptyState`, `Pager`, `motion` helpers, shadcn `components/ui/*` (tabs, dialog, sheet, select, calendar, textarea, table), `sonner` toasts, i18n via `I18nContext` (English + Hindi). |

Additional legal guard-rails (owner to confirm with counsel): the operating entity shown in email branding is an
Ayurveda business — captions and posters must not make disease-cure or guaranteed-result claims (Drugs and Magic
Remedies (Objectionable Advertisements) Act, 1954 and AYUSH advertising rules); multi-level commission
(direct/referral/team in `commission.py`) brings the Consumer Protection (Direct Selling) Rules, 2021 into scope, which
prohibit misleading earnings representations.

---

## 1. What exists today (inspected)

| Piece | Location | Behaviour |
|---|---|---|
| Product share link | `frontend/src/lib/sellerRef.js` `productShareLink(id, distributorId)` | `https://<origin>/app/products/<id>?ref=HG000123` — the raw member ID in the URL, unsigned, no link id, no channel. |
| Ref capture | `sellerRef.captureSellerRef` called from `index.js` (first load, before any login redirect) and `App.js` `SellerRefCapture` (every route change) | Accepts only `^HG\d{4,10}$`; ignores any path starting `/register` (sponsor codes are never seller codes); writes `localStorage.hg_seller_ref = {ref, at}`. |
| Ref use | `pages/Checkout.js` (COD, UPI, Razorpay/Stripe paths) | Sends `seller_ref: getSellerRef()` in `POST /api/orders`, then `clearSellerRef()`. Logout (`AuthContext`) also clears it. |
| Share button | `pages/ProductDetail.js` | Visible only to `role=distributor`, `status=green`, with a `distributor_id`. Web Share API (`navigator.share({title,url})`), else clipboard copy. No WhatsApp-specific button, no text, no image. |
| Referral page | `pages/Referral.js` (MemberOnly) | `/register?ref=<id>` sponsor link + QR (`qrcode` lib, chocolate `#3B2417`) + `wa.me/?text=`, `mailto:`, `sms:`. **Copy reads "Shop with me on HOME GENIES"** although the link is a registration/sponsor link — misleading and recruitment-flavoured; fix in MVP (relabel as an invitation, or point "shop with me" at a product/shop link instead). |
| Server attribution | `backend/shop_routes.py` `create_order` | `seller_ref` upper-cased; accepted only if a user with that `distributor_id` has `role=distributor`, `status=green`, and is not the buyer; stores `orders.seller_user_id`, `orders.seller_distributor_id`. Otherwise the order is unattributed (silently). Indexed `orders_seller_created`. |
| Commission | `backend/commission.py` | Base = pre-GST subtotal; direct 30 % to the seller, 10 % referral, 5 % team (one level each), only for PAID orders, only to green distributors, never for own purchases; PENDING then released after the return window. |
| Metrics | `backend/homegenie_metrics.py` `GET /api/homegenie/metrics`, `/api/homegenie/orders`; UI `components/HomeGeniePerformance.js` on `Dashboard.js` | Attributed orders by `orders.seller_user_id`, IST date ranges (`ist_range`), states (`order_state`), goods value in paise, commission from `commissions`. Defined in `docs/HOMEGENIE_DASHBOARD_METRICS.md`. |
| Product page access | `App.js` | `/app/products/:id` is inside `ProtectedRoute` → an anonymous recipient must log in/register first. The ref survives because `index.js` captures it on first load. |
| Link previews | `frontend/public/index.html` | No Open Graph tags; every shared link previews as the generic site ("HOME GENIES — Establish Yourself."), no product image. |
| Image tools available | `package.json` | `html-to-image`, `qrcode` already installed; no LLM code (Integration Register #19). |

### 1.1 The existing attribution rule (must be preserved)
1. **Last click wins.** Every valid `?ref=` on any non-`/register` page overwrites the stored code.
2. **30-day window**, measured from the most recent capture (a re-click refreshes it). Stored only in the browser.
3. **Order-level, not product-level.** The stored code attributes the next order whatever products it contains.
4. **One order only.** Cleared immediately after `POST /orders` returns (even if that online payment later fails) and on logout.
5. **Server decides eligibility at order time** (distributor + green + not the buyer); commission re-checks eligibility when paid.
6. An ineligible newer code still overwrites an eligible older one (the order is then unattributed). Kept as-is; listed
   as owner decision OD-M6.

---

## 2. End-to-end attribution design (link → click → session → order)

```
member taps Share ─▶ POST /api/marketing/links  (server: member green? product shop-visible?)
                       └─ returns https://<shop>/s/K7f3QpX2aB  (opaque code, no member ID)
recipient opens ─▶ GET /s/<code>  (frontend vercel.json rewrite → API /api/s/<code>)
                       ├─ looks up link: active, not expired/revoked, product still visible
                       ├─ records click (privacy-preserving, bots and owner self-clicks flagged)
                       ├─ serves small HTML with Open Graph tags (product name, image, current price)
                       └─ redirects to /app/products/<id>?hl=<code>
SPA load ─▶ captureSellerRef extended: accepts ?hl=<code> (format ^[A-Za-z0-9]{10}$) into the SAME
            localStorage slot {kind:"link", code, at} — same last-click overwrite, same 30-day TTL,
            same /register exclusion; legacy ?ref=HG… still accepted as {kind:"ref"}
Checkout ─▶ POST /api/orders { …, seller_ref | share_link_code }
            server resolves code → link.owner → SAME eligibility checks as today → seller_user_id
            and writes an immutable snapshot orders.marketing = {link_code, channel, campaign_id,
            product_id, link_created_at}; clearSellerRef() as today
Payment ─▶ unchanged: _process_paid_order → commission.distribute_sale_commissions
Reports ─▶ joins orders.marketing.link_code ↔ marketing_links; clicks from marketing_click_events
```

- **Signing:** the code is a server-generated random 10-character base62 id (~59 bits) looked up server-side, so it cannot
  be forged or altered into another member's link; no HMAC is needed. Legacy `?ref=HG…` links cannot be signed and stay
  valid for backward compatibility (owner decision OD-M2 on sunsetting them; they also expose the member ID, which is a
  login identifier — `providers.send_account_id_sms` says "Keep it safe to log in").
- **Expiry:** product links default to no expiry (unlisting already stops them); campaign links expire at campaign end +
  30 days; revoked/expired codes still land on the shop but set no attribution and show a short notice.
- **Server never trusts channel/campaign from the client at order time** — it reads them from the link record.
- **Disallowed by design:** first-click override, cross-device server-side stickiness, cookie syncing — any of these
  would change the existing rule and need owner approval (OD-M6).
- Known, accepted limitation: anyone can share their own link for a product; attribution follows the link the customer
  last used. Clicks never pay, so click inflation has no money effect.

---

## 3. Module inventory (17 modules)

Legend — **No-integration**: works with links/browser features only. **Official API**: needs a platform account and approval.

### M1. Product sharing & attribution links
- No-integration: everything (server link service, `/s/<code>` redirect, copy link, QR from existing `qrcode`).
- Official API: none.
- Data: `marketing_links`; `orders.marketing` snapshot.
- Permissions: create = distributor + green (same as `ProductDetail.canShare` and `commission.is_commission_eligible`);
  other members may share an **unattributed** link. Admin can list/revoke.
- **MVP.**

### M2. WhatsApp product sharing (one-to-one, member's own WhatsApp)
- No-integration: `https://wa.me/?text=<urlencoded caption + link>` (WhatsApp "click to chat", user picks the chat and
  presses Send), or Web Share API Level 2 with the poster file (`navigator.canShare({files})`) on mobile.
- Official API: none. Rich preview needs the Open Graph page in M1.
- Consent: the member chooses each recipient manually; the platform receives no contact data.
- **MVP.**

### M3. WhatsApp campaign tools (member-side)
- No-integration: a "campaign kit" = approved text + poster + link for one product/festival, shared via M2. Guidance that
  WhatsApp Broadcast Lists (in the member's own app) only reach contacts who saved the member's number; no automation.
- Official API: not used — HOME GENIES cannot send to a member's contacts because the platform holds no opt-in from them.
- Platform restrictions: WhatsApp Business Policy requires opt-in from the recipient and bans unsolicited bulk messaging.
- **Phase 2** (after templates + calendar exist).

### M4. Instagram & Facebook sharing
- No-integration: Facebook `https://www.facebook.com/sharer/sharer.php?u=<link>`; Instagram has no web share intent —
  use Web Share API with the poster file on mobile (user picks Instagram), or download poster + copy caption.
  Instagram does not make caption links clickable: put the link in the member's bio / Story link sticker (manual).
- Official API (Phase 3, M17): Instagram Graph API content publishing; Facebook Pages API.
- **MVP** for share intents/download; publishing **Phase 3**.

### M5. Other social channels
- No-integration: X `https://twitter.com/intent/tweet?text=&url=`, Telegram `https://t.me/share/url?url=&text=`,
  LinkedIn `https://www.linkedin.com/sharing/share-offsite/?url=`, Pinterest pin-create URL, `sms:`, `mailto:`, QR print.
- Each button creates (or reuses) a link with its `channel` value so source attribution is per channel.
- **MVP** (WhatsApp, Facebook, X, Telegram, SMS, email, QR, copy); Pinterest/LinkedIn Phase 2.

### M6. AI-assisted captions / descriptions
- No-integration (MVP): deterministic caption builder from approved product data (name, name_hi, key benefits/PIM
  description, current price, link) through admin-approved templates. No model call.
- With AI (Phase 2): requires an LLM provider choice and account (owner decision OD-M4; env names e.g.
  `MARKETING_AI_PROVIDER`, `MARKETING_AI_API_KEY`). Send **only product data**, never customer or member personal data.
  Output passes the claims filter (cure/guarantee/earnings/recruitment terms, competitor names), is editable, and must be
  confirmed by the member. Per-member daily quota via existing `core.rate_limit`.
- Data: `marketing_ai_requests` (prompt kind, product id, output, accepted flag), retention 90 days.

### M7. Hashtag suggestions
- No-integration: admin-curated hashtag sets per category and festival (English/Hindi), max 5–10 per post.
- Official API: Instagram hashtag search exists only for connected professional accounts and is capped (30 unique
  hashtags per 7 days per account) — not worth it. No scraping of "trending" lists.
- **MVP** (curated).

### M8. Promotional creatives / posters
- No-integration: client-side render with existing `html-to-image` into a branded frame (cream background, chocolate type,
  gold accents, HOME GENIES logo from `public/brand`), product image, current price with "price on <date>", QR to the
  member's link. Formats: 1080×1080 (feed), 1080×1920 (status/story).
- Prerequisite: images must be CORS-readable for canvas: `/api/files/*` (API origin ≠ shop origin) needs
  `Access-Control-Allow-Origin` for the shop origin on image responses; Cloudinary images need `crossOrigin="anonymous"`.
- Data: none in MVP (rendered on device). Phase 2 optional `marketing_creatives` (saved poster metadata + price stamp;
  marked stale when `products.price_history` changes).
- **MVP** (templated posters); AI image generation **not planned** (misrepresentation risk for real products).

### M9. Festival / seasonal campaigns
- No-integration: admin-managed `marketing_festivals` (Diwali, Holi, Raksha Bandhan, Pongal/Sankranti, Onam, Eid,
  Christmas, regional), each with approved template pack, poster frames, suggested categories/products.
- Any discount shown must be a real, current HOME GENIES price (no fake strike-through MRP: use only stored `mrp`).
- **Phase 2.**

### M10. Personal campaign calendar
- No-integration: member's plan entries (date, product/festival, channel, note); reminders as in-app notifications
  through existing `core.create_notification`, generated by a daily cron. No auto-posting, no push (none integrated).
- **Phase 2.**

### M11. Saved templates
- Platform templates (admin-authored, versioned, approved) and personal templates (member-private, pass the claims
  filter on save). Placeholders: `{product_name}`, `{price}`, `{link}`, `{member_first_name}`; `{price}` and `{link}` are
  always resolved server-side at share time.
- **MVP** for platform templates (read-only to members); personal templates **Phase 2**.

### M12. Click & conversion tracking
- No-integration: our redirect records the click; conversion = order whose `orders.marketing.link_code` matches.
  Funnel stages reuse `homegenie_metrics.order_state`: placed → paid → delivered → returned; unpaid/cancelled never count
  as conversions.
- Click record: no raw IP, no full user agent. `visitor_hash = HMAC(daily_salt, ip|ua_family)`, salt rotated daily and
  discarded (unique-per-day only, labelled approximate). Bot user agents and logged-in owner self-clicks flagged and
  excluded. Messenger link-preview fetchers (WhatsApp/Facebook crawlers) are bots → not clicks.
- **MVP.**

### M13. Marketing-source attribution
- Source = the `channel` of the link (whatsapp, facebook, instagram, x, telegram, sms, email, qr, copy, other) plus
  optional `campaign_id`. Shown as "shared via", not as a verified traffic source (a copied link can be pasted anywhere).
  Optional `utm_*` parameters appended for any future first-party analytics; not required.
- **MVP.**

### M14. Customer enquiries & lead tracking
- No-integration: a logged-in customer on a product reached via a member's link can tap "Ask <member first name>"; the
  question is stored in-app and shown in the member's studio; the member replies in-app. The customer's phone/e-mail is
  shared with the member **only** if the customer ticks a separate, unticked-by-default consent ("Share my mobile with
  this HomeGenie so they can contact me about this product"), with a notice per DPDP.
- Not allowed: members uploading or typing third-party contacts as "leads"; exporting customer lists.
- Data: `marketing_enquiries`, `marketing_consents`; retention 180 days after closure, then delete or anonymise.
- **Phase 2.**

### M15. Marketing performance dashboard
- Extends `HomeGeniePerformance` / `GET /api/homegenie/metrics` (same IST ranges, paise money, `commissions` as the only
  source of earnings). Breakdowns by link, product, channel, campaign; clicks, unique visitors (approx.), orders placed,
  paid, delivered, returned, goods value, commission pending/released. Empty states explain what is not measured.
- **MVP** (by link/product/channel); campaign view Phase 2.

### M16. Future: official WhatsApp Business API (Cloud API)
- Scope: HOME GENIES-owned business number only. Use cases in order: (1) utility templates — order confirmed/shipped/
  delivered to the buyer; (2) customer-service replies inside the 24-hour window; (3) marketing templates only to
  customers who opted in to WhatsApp marketing on HOME GENIES, with dynamic URL buttons carrying a link code so
  attribution flows through M1 (to the platform or to the member whose link the customer used — owner decision OD-M5).
- Requirements: Meta Business Manager account with **business verification**, WhatsApp Business Account, dedicated phone
  number, approved display name, every template submitted and approved, webhook endpoint with signature verification,
  system-user access token. Env names (proposed): `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`,
  `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`.
- Platform rules: opt-in naming the business is mandatory; outside the 24-hour customer-service window only approved
  templates may be sent; Meta can pause/reject templates; per-user marketing-template limits and messaging-limit tiers
  and quality ratings apply; per-message pricing. No unofficial libraries (e.g. WhatsApp Web automation).
- Data: `wa_templates`, `wa_messages` (status from webhooks), `wa_webhook_events` (unique event id, as
  `payment_events.py` does), opt-ins in `marketing_consents` (purpose `whatsapp_marketing` / `whatsapp_utility`).
- **Phase 3.**

### M17. Future: social platform integrations (Meta Graph API)
- Instagram content publishing for a member's **own** professional (Business/Creator) account via Instagram Business
  Login (`instagram_business_basic`, `instagram_business_content_publish`) or Facebook Login for Business
  (`instagram_basic`, `instagram_content_publish`, `pages_read_engagement`); Facebook Page posts via `pages_manage_posts`.
  Needs a Meta app, **App Review** for advanced access, business verification, public JPEG URLs for media, and per-account
  publishing caps (Meta documents 50–100 API posts per 24 h; check `content_publishing_limit`).
- Stores per-member OAuth tokens (encrypted at rest, scoped, revocable) → higher security and DPDP burden.
- Posting must remain member-initiated (a scheduled post the member explicitly created is acceptable; no auto-generated
  posting).
- **Phase 3, only if MVP data shows demand.**

---

## 4. Proposed collections

| Collection | Key fields | Indexes | Retention |
|---|---|---|---|
| `marketing_links` | `id`, `code` (unique), `owner_user_id`, `owner_distributor_id`, `target` (`product`/`shop`), `product_id`, `channel`, `campaign_id`, `template_id`, `status` (`active`/`revoked`/`expired`), `expires_at`, `created_at`, `revoked_at`, `revoked_by`, `clicks_total` (denormalised) | `code` unique; `(owner_user_id, created_at)`; `(owner_user_id, product_id, channel, campaign_id)` unique for active links (reuse instead of minting duplicates) | Life of account; anonymise owner on account erasure |
| `marketing_click_events` | `link_code`, `owner_user_id`, `product_id`, `channel`, `at`, `ist_day`, `visitor_hash`, `ua_class` (mobile/desktop), `is_bot`, `is_self` | `(link_code, at)`; TTL on `at` | 90 days (TTL index, pattern in `db_indexes.py`) |
| `marketing_daily_stats` | `owner_user_id`, `ist_day`, `link_code`, `product_id`, `channel`, `campaign_id`, `clicks`, `unique_visitors_approx` | unique `(owner_user_id, ist_day, link_code)` | 24 months |
| `orders.marketing` (new sub-document) | `link_code`, `channel`, `campaign_id`, `product_id`, `link_created_at` | `(marketing.link_code)` sparse | Order retention |
| `marketing_templates` | `id`, `scope` (`platform`/`personal`), `owner_user_id`, `kind` (`caption`/`whatsapp_text`/`poster_frame`), `lang` (`en`/`hi`), `body`, `festival_id`, `category`, `version`, `status` (`draft`/`approved`/`retired`), `approved_by`, `approved_at` | `(scope, status, kind, lang)` | Keep versions (audit) |
| `marketing_hashtag_sets` | `category`/`festival_id`, `lang`, `tags[]`, `status` | `(category, lang)` | — |
| `marketing_festivals` | `id`, `name`, `name_hi`, `date_from`, `date_to`, `regions[]`, `template_ids[]`, `suggested_categories[]`, `status` | `(date_from)` | — |
| `marketing_campaigns` | `id`, `owner_user_id` (null = platform), `name`, `festival_id`, `product_ids[]`, `start`, `end`, `status` | `(owner_user_id, start)` | 24 months |
| `marketing_calendar_entries` | `id`, `owner_user_id`, `date`, `campaign_id`, `product_id`, `channel`, `note`, `remind`, `reminded_at` | `(owner_user_id, date)` | 12 months after date |
| `marketing_enquiries` | `id`, `owner_user_id`, `customer_user_id`, `product_id`, `link_code`, `messages[]`, `contact_shared` (bool), `consent_id`, `status`, `closed_at` | `(owner_user_id, status, created_at)` | 180 days after close |
| `marketing_consents` | `id`, `subject_user_id` or `mobile_hash`, `purpose`, `notice_version`, `granted_at`, `source`, `withdrawn_at` | `(subject_user_id, purpose)` | Life of consent + 3 years evidence (legal to confirm) |
| `marketing_ai_requests` (Ph 2) | `owner_user_id`, `product_id`, `kind`, `output`, `accepted`, `provider`, `at` | TTL | 90 days |
| `wa_templates`, `wa_messages`, `wa_webhook_events` (Ph 3) | per M16 | unique `event_id` | messages 12 months |
| `social_accounts` (Ph 3) | `owner_user_id`, `platform`, `account_id`, `token_enc`, `scopes`, `expires_at`, `revoked_at` | `(owner_user_id, platform)` | Delete on disconnect |

All writes of admin actions go to the existing `audit_logs` via `core.log_audit`.

## 5. Proposed APIs (FastAPI, new router `marketing_routes.py`, prefix `/api`)

Member (`get_current_user`; creation gated to distributor + green):
- `GET  /marketing/products` — shareable products (SHOP_VISIBLE, current price, primary image).
- `POST /marketing/links` `{target, product_id?, channel, campaign_id?}` → `{code, url, wa_url, share_text}`; idempotent per (owner, product, channel, campaign).
- `GET  /marketing/links` · `POST /marketing/links/{code}/revoke`
- `GET  /marketing/templates?kind&lang&festival` · `POST /marketing/templates/render` `{template_id, product_id, code}` (server resolves price and link)
- `GET  /marketing/hashtags?product_id|festival_id`
- `GET  /marketing/performance?frm&to&group=link|product|channel|campaign` (reuses `homegenie_metrics.ist_range`)
- Phase 2: `/marketing/calendar` (CRUD), `/marketing/festivals`, `/marketing/campaigns`, `/marketing/templates` (personal CRUD), `/marketing/captions/suggest`, `/marketing/enquiries` (member list/reply), customer `POST /products/{id}/enquiries`.

Public:
- `GET /api/s/{code}` — click record + Open Graph HTML + redirect (rate-limited with `core.rate_limit`; `X-Robots-Tag: noindex`). Frontend `vercel.json` gains a rewrite `/s/:code` → API origin (rule must precede the SPA catch-all).

Admin (`require_admin`; authoring by `admin`/`super_admin` — no new platform role, owner decision D-16 blocks new roles):
- `/admin/marketing/templates` (draft → approve, two-person rule: author ≠ approver, as products), `/admin/marketing/hashtags`, `/admin/marketing/festivals`, `/admin/marketing/links?owner&status` (+ revoke), `/admin/marketing/overview`.
- Phase 3: `/webhook/whatsapp` (signature-verified), `/admin/whatsapp/templates`.

Order creation change (small, backward compatible): `CreateOrder.share_link_code: Optional[str]`; resolve → same
eligibility code path → set `orders.marketing`. `seller_ref` keeps working.

## 6. Screens (existing design system)

- **Member:** `/app/studio` (MemberOnly; locked card like `Referral.js` for non-green) with tabs: *Share* (product picker
  → channel buttons → caption preview → poster preview), *My links*, *Performance*; Phase 2 tabs *Calendar*, *Templates*,
  *Enquiries*. `ProductDetail` share button opens the same share sheet (shadcn `Sheet` on mobile, `Dialog` on desktop).
- **Customer:** unchanged product page; Phase 2 "Ask <member>" on products reached via a link.
- **Admin:** `/admin/marketing` (templates approval queue, hashtag sets, festivals, link oversight).
- Copy in English and Hindi via `i18n/translations.js`. Tokens: cream surfaces, chocolate text, gold accents; posters
  use the same palette and the logo in `public/brand`.

## 7. Background jobs (existing Vercel Cron + `cron_routes.py` bearer pattern)

| Job | Schedule | Phase |
|---|---|---|
| Aggregate `marketing_click_events` → `marketing_daily_stats`; join attributed orders by link | daily | MVP |
| Expire campaign links past `expires_at`; deactivate links whose product left the shop | daily | MVP |
| Click-event TTL | Mongo TTL index (no job) | MVP |
| Calendar reminders → `create_notification` | daily | 2 |
| Mark saved creatives stale after a price change | daily | 2 |
| Purge closed enquiries / AI logs past retention | daily | 2 |
| WhatsApp template status sync; webhook retry (as `payment_events`) | hourly | 3 |

Note: `backend/vercel.json` already has 2 crons; Vercel plan limits on cron count/frequency must be checked (hourly jobs may need a paid plan).

## 8. Dependencies on existing modules

`shop_routes` (SHOP_VISIBLE, `create_order`), `commission.py` (unchanged; eligibility helper reused), `homegenie_metrics.py`
(ranges, order states), `core` (`rate_limit`, `log_audit`, `create_notification`, `client_ip`), `db_indexes.py`,
`cron_routes.py`, `pim.py` (price history, descriptions), `storage.py` (image serving; needs CORS for canvas),
`sellerRef.js`, `Checkout.js`, `ProductDetail.js`, `Referral.js`, `HomeGeniePerformance.js`, `i18n`.

## 9. Consent & privacy (DPDP Act 2023 and DPDP Rules 2025)

- HOME GENIES is the Data Fiduciary for click, enquiry and consent data. The DPDP Rules were notified in November 2025
  with staggered commencement (Nov 2025, Nov 2026, May 2027; the notice-and-consent obligations in the final stage) —
  build to the final standard now.
- Data minimisation: clicks store no IP or contact data; no tracking cookies; no third-party pixels (so no cookie banner
  is introduced by this module).
- Enquiries: itemised notice (what is shared, with whom, why, how to withdraw), separate optional consent for sharing a
  contact with a member, withdrawal in one tap, erasure on request, retention limits in section 4.
- WhatsApp marketing (Phase 3): explicit, separate opt-in naming HOME GENIES, recorded in `marketing_consents` with notice
  version; opt-out keyword honoured; utility and marketing opt-ins kept separate.
- Members are told in the studio that they must only message people who know them and agreed to hear from them.

## 10. Risks

1. **Attribution is browser-only** (localStorage): lost on device/browser switch or cleared storage; recipients forced to
   log in first (`ProtectedRoute`) may drop off. Owner decision OD-M1 on public product pages.
2. **Member ID in legacy links** is also a login identifier — exposure aids targeted login attempts.
3. **Claims risk** — Ayurveda/health claims and earnings claims in member-written or AI text (legal exposure); mitigated
   by approved templates, claims filter, and review.
4. **Spam reputation** — members mass-forwarding can get numbers banned by WhatsApp and harm the brand; mitigated by
   no automation, guidance, and per-member link-creation rate limits.
5. **Price drift** in posters already shared (cannot be recalled); mitigated by date stamp and the link always showing the
   current price.
6. **Canvas/CORS** on product images (API origin differs from shop origin) blocks poster rendering until headers are added.
7. **Misleading Referral page copy** ("Shop with me" on a sponsor link) — conflicts with "no recruitment-based earnings" messaging.
8. **Phase 3 approvals** (Meta business verification, App Review, template approval) take weeks and can be refused;
   costs are per message.
9. **Vercel limits**: the redirect adds an API call per click (cold starts, 60 s limit irrelevant but latency matters);
   cron count limits.
10. **Commission perception** — dashboards must show pending vs released exactly as the finance engine records them;
    never project earnings from clicks.

## 11. Owner decisions needed

- **OD-M1** Make `/app/products/:id` (and shop) viewable without login for link recipients?
- **OD-M2** Sunset legacy `?ref=HG…` links after a transition period?
- **OD-M3** Show prices on posters (with date stamp) or "see price at link" only?
- **OD-M4** AI caption provider and budget (or no AI).
- **OD-M5** For Phase 3 platform WhatsApp marketing, who is credited — the platform or the member whose link was used?
- **OD-M6** Keep pure last-click including "ineligible newer code overwrites eligible older code", or ignore ineligible codes client-side?
- **OD-M7** May vendors use the studio for their own products (traffic only, no commission)?
- **OD-M8** Who approves templates (admin + super_admin two-person rule proposed) and the claims policy text.

## 12. Phased plan

**MVP (no external integration, no new secrets)**
- M1 links service + `/s/<code>` redirect + Open Graph landing; `share_link_code` on orders; `orders.marketing` snapshot.
- Share sheet: WhatsApp (`wa.me`), Web Share API (with poster file), copy, Facebook sharer, X, Telegram, SMS, email, QR (M2, M4, M5).
- Platform-approved caption templates (en/hi) with server-resolved price/link (M6 template-only, M11 platform), curated hashtags (M7).
- Client-side posters with QR (M8).
- Click and conversion tracking, channel attribution, studio performance tab (M12, M13, M15).
- Admin: templates (two-person approval), hashtag sets, link oversight/revoke.
- Fix `Referral.js` copy.
- **Prerequisites:** OD-M1, OD-M3, OD-M6, OD-M8 decided; CORS header for `/api/files/*` images; frontend `vercel.json`
  rewrite for `/s/*`; `marketing_*` indexes in `db_indexes.py`; tests for attribution parity (legacy `?ref` and new code
  give identical `seller_user_id` under the same eligibility cases, self-referral, ineligible owner, revoked/expired link,
  unlisted product); privacy notice update for click recording.

**Phase 2**
- Festival/seasonal packs (M9), campaign kits (M3), personal calendar with in-app reminders (M10), personal templates
  (M11), enquiries with consent (M14), campaign view in dashboard, AI caption assist if OD-M4 approved (M6), Pinterest/LinkedIn.

**Phase 3**
- WhatsApp Business Platform Cloud API on a HOME GENIES number: utility order updates first, then opted-in marketing
  templates with link-code URL buttons (M16).
- Instagram/Facebook publishing for members' own accounts via Meta Graph API, if demand is proven (M17).

## 13. Sources (public platform rules)
- WhatsApp Business Policy (opt-in, no unsolicited messaging): https://business.whatsapp.com/policy
- WhatsApp Cloud API — sending messages and the 24-hour customer service window: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages
- WhatsApp pricing (template vs service messages): https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- Per-user marketing template limits: https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/marketing-templates/per-user-limits/
- Instagram content publishing (permissions, limits): https://developers.facebook.com/documentation/instagram-platform/content-publishing and https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit
- DPDP Rules 2025 (PIB notification document): https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf ; summary: https://www.azbpartners.com/bank/update-indias-digital-personal-data-protection-framework-comes-into-effect/
