import React from "react";
import { Link, useParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, FileText } from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { useI18n } from "@/context/I18nContext";

const DOC = {
  terms: {
    title: { en: "Terms & Conditions", hi: "नियम व शर्तें" },
    body: {
      en: [
        "These terms govern your use of the HOME GENIES platform, including shopping as a customer and selling as a HomeGenie.",
        "Eligibility: you must be able to form a legally binding contract and provide accurate registration details. Accounts with false information may be suspended.",
        "Customer and HomeGenie roles: every registered account can shop. The HomeGenie selling role is enabled only after review and approval by our team.",
        "Selling: HomeGenies may share product links with customers. Purchasing inventory is not mandatory and depends on the fulfilment model of each product.",
        "Earnings: commission is payable only on qualifying product sales under the approved HOME GENIES commission rules. Registering or introducing another person, by itself, never generates commission. The commission rules and rates are pending final configuration and are not active.",
        "Pricing and availability: prices, GST and availability are shown at checkout and are calculated by our servers at the time of order.",
        "Prohibited conduct: misrepresenting the platform, promising guaranteed income, or making unapproved product or earnings claims is not permitted and may result in removal.",
        "Changes: we may update these terms. Material changes will be notified in the app.",
      ],
      hi: [
        "ये शर्तें होम जीनीज़ मंच के उपयोग पर लागू होती हैं, जिसमें ग्राहक के रूप में खरीदारी और होम जीनी के रूप में बिक्री शामिल है।",
        "पात्रता: आपको कानूनी रूप से अनुबंध करने योग्य होना चाहिए और सही पंजीकरण विवरण देना होगा। गलत जानकारी वाले खाते निलंबित किए जा सकते हैं।",
        "ग्राहक और होम जीनी भूमिका: हर पंजीकृत खाता खरीदारी कर सकता है। सेलिंग भूमिका केवल हमारी टीम की समीक्षा और स्वीकृति के बाद सक्रिय होती है।",
        "बिक्री: होम जीनीज़ ग्राहकों के साथ उत्पाद लिंक शेयर कर सकती हैं। स्टॉक खरीदना अनिवार्य नहीं है और यह हर उत्पाद के फ़ुलफ़िलमेंट मॉडल पर निर्भर करता है।",
        "कमाई: कमीशन केवल स्वीकृत होम जीनीज़ नियमों के तहत योग्य उत्पाद बिक्री पर देय है। केवल किसी को जोड़ने से कभी कमीशन नहीं मिलता। कमीशन नियम और दरें अभी अंतिम रूप से कॉन्फ़िगर नहीं हुई हैं और सक्रिय नहीं हैं।",
        "मूल्य और उपलब्धता: कीमतें, जीएसटी और उपलब्धता चेकआउट पर दिखाई जाती हैं और ऑर्डर के समय हमारे सर्वर द्वारा गणना की जाती हैं।",
        "निषिद्ध आचरण: मंच को गलत तरीके से प्रस्तुत करना, गारंटीड आय का वादा करना, या अस्वीकृत उत्पाद/कमाई दावे करना वर्जित है और खाता हटाया जा सकता है।",
        "परिवर्तन: हम इन शर्तों को अपडेट कर सकते हैं। महत्वपूर्ण बदलाव ऐप में सूचित किए जाएंगे।",
      ],
    },
  },
  privacy: {
    title: { en: "Privacy Policy", hi: "गोपनीयता नीति" },
    body: {
      en: [
        "We collect only the information needed to run your account: name, mobile number, email, delivery address and your order history.",
        "Payment details are handled by our payment provider. We do not store card numbers or UPI credentials on our servers.",
        "We use your information to process orders, provide support, send service notifications and — for HomeGenies — to record eligible sales activity.",
        "We do not sell your personal information. Information is shared only with service providers who help us deliver orders and operate the platform.",
        "Your data is retained while your account is active and for as long as required by law or for dispute resolution.",
        "You may request access to, correction of, or deletion of your personal information by contacting support.",
      ],
      hi: [
        "हम केवल वही जानकारी एकत्र करते हैं जो आपका खाता चलाने के लिए आवश्यक है: नाम, मोबाइल नंबर, ईमेल, डिलीवरी पता और आपका ऑर्डर इतिहास।",
        "भुगतान विवरण हमारे पेमेंट प्रोवाइडर द्वारा संभाले जाते हैं। हम कार्ड नंबर या यूपीआई क्रेडेंशियल अपने सर्वर पर संग्रहीत नहीं करते।",
        "हम आपकी जानकारी का उपयोग ऑर्डर प्रोसेस करने, सहायता देने, सेवा सूचनाएँ भेजने और होम जीनीज़ हेतु योग्य बिक्री गतिविधि दर्ज करने के लिए करते हैं।",
        "हम आपकी व्यक्तिगत जानकारी नहीं बेचते। जानकारी केवल उन सेवा प्रदाताओं के साथ साझा की जाती है जो ऑर्डर पहुँचाने और मंच संचालित करने में सहायता करते हैं।",
        "आपका डेटा तब तक रखा जाता है जब तक आपका खाता सक्रिय है, या जब तक कानून/विवाद समाधान हेतु आवश्यक हो।",
        "आप सहायता से संपर्क कर अपनी व्यक्तिगत जानकारी देखने, सुधारने या हटाने का अनुरोध कर सकती हैं।",
      ],
    },
  },
  returns: {
    title: { en: "Returns Policy", hi: "वापसी नीति" },
    body: {
      en: [
        "Returns are accepted for items that are damaged, defective, or materially different from what was ordered.",
        "Raise a return request from your order page. Please keep the original packaging and any tags intact.",
        "Hygiene-sensitive items such as opened makeup, skincare and personal-care products cannot be returned once the seal is broken, unless the item is damaged or defective.",
        "The return window, pickup availability and any applicable charges are confirmed on your order page when you raise the request. We do not promise timelines we cannot meet.",
        "Once a return is received and checked, the refund follows our Refunds Policy.",
      ],
      hi: [
        "क्षतिग्रस्त, दोषपूर्ण या ऑर्डर से काफ़ी भिन्न वस्तुओं पर वापसी स्वीकार की जाती है।",
        "अपने ऑर्डर पेज से वापसी अनुरोध करें। कृपया मूल पैकेजिंग और टैग सुरक्षित रखें।",
        "खुले हुए मेकअप, स्किनकेयर और व्यक्तिगत देखभाल जैसे स्वच्छता-संवेदनशील उत्पाद सील टूटने के बाद वापस नहीं किए जा सकते, जब तक वस्तु क्षतिग्रस्त या दोषपूर्ण न हो।",
        "वापसी अवधि, पिकअप उपलब्धता और लागू शुल्क अनुरोध करते समय आपके ऑर्डर पेज पर पुष्ट किए जाते हैं। हम ऐसा समय नहीं बताते जो पूरा न कर सकें।",
        "वापसी प्राप्त होकर जाँच होने के बाद रिफ़ंड हमारी रिफ़ंड नीति के अनुसार होता है।",
      ],
    },
  },
  refunds: {
    title: { en: "Refunds Policy", hi: "रिफ़ंड नीति" },
    body: {
      en: [
        "Approved refunds are issued to the original payment method used for the order.",
        "For orders paid online, the refund is initiated once the returned item is received and checked. Bank posting times vary by provider.",
        "Partial refunds may apply where only some items in an order are returned.",
        "If any HomeGenie commission or points were recorded against a refunded order, the corresponding amount is reversed so that records stay accurate.",
        "Refund status is visible on your order page, and every refund is recorded in our audit trail.",
      ],
      hi: [
        "स्वीकृत रिफ़ंड उसी भुगतान माध्यम में जारी किया जाता है जिससे ऑर्डर किया गया था।",
        "ऑनलाइन भुगतान वाले ऑर्डर में, लौटाई गई वस्तु प्राप्त होकर जाँच होने पर रिफ़ंड शुरू किया जाता है। बैंक में राशि आने का समय प्रोवाइडर पर निर्भर करता है।",
        "यदि ऑर्डर की कुछ ही वस्तुएँ लौटाई गई हों तो आंशिक रिफ़ंड लागू हो सकता है।",
        "यदि रिफ़ंड किए गए ऑर्डर पर कोई होम जीनी कमीशन या पॉइंट्स दर्ज थे, तो रिकॉर्ड सटीक रखने हेतु वह राशि वापस समायोजित कर दी जाती है।",
        "रिफ़ंड स्थिति आपके ऑर्डर पेज पर दिखती है और हर रिफ़ंड हमारे ऑडिट रिकॉर्ड में दर्ज होता है।",
      ],
    },
  },
  support: {
    title: { en: "Support", hi: "सहायता" },
    body: {
      en: [
        "Our team can help with orders, deliveries, returns, payments and your HomeGenie account.",
        "The quickest way to reach us is from your order page, where your order number is attached automatically.",
        "Support contact details for HOME GENIES are being finalised and will be published here and in your profile.",
        "We will never ask you for your password, full card number or any OTP.",
      ],
      hi: [
        "हमारी टीम ऑर्डर, डिलीवरी, वापसी, भुगतान और आपके होम जीनी खाते में सहायता कर सकती है।",
        "हमसे संपर्क का सबसे तेज़ तरीका आपका ऑर्डर पेज है, जहाँ आपका ऑर्डर नंबर स्वतः जुड़ जाता है।",
        "होम जीनीज़ के सहायता संपर्क विवरण अंतिम रूप दिए जा रहे हैं और यहाँ तथा आपकी प्रोफ़ाइल में प्रकाशित होंगे।",
        "हम आपसे कभी भी पासवर्ड, पूरा कार्ड नंबर या ओटीपी नहीं मांगेंगे।",
      ],
    },
  },
};

export default function Legal() {
  const { slug } = useParams();
  const { lang } = useI18n();
  const doc = DOC[slug] || DOC.terms;
  const l = lang === "hi" ? "hi" : "en";

  return (
    <div className="relative isolate min-h-screen overflow-x-hidden bg-background" data-testid="legal-page">
      <span aria-hidden="true" className="pointer-events-none absolute -left-24 top-24 -z-10 h-72 w-72 rounded-full bg-hg-violet/20 blur-3xl" />
      <span aria-hidden="true" className="pointer-events-none absolute -right-24 top-[40%] -z-10 h-64 w-64 rounded-full bg-hg-pink/10 blur-3xl" />
      <header className="sticky top-0 z-30 px-3 pt-3 sm:px-5" style={{ paddingTop: "max(0.75rem, env(safe-area-inset-top, 0px))" }}>
        <div className="hg-glass mx-auto flex h-14 max-w-3xl items-center justify-between gap-2 !rounded-2xl px-3 sm:h-16 sm:px-4">
          <Link to="/" className="min-w-0 shrink" aria-label="HOME GENIES">
            <img src="/brand/logo-icon.png" alt="" className="h-9 w-9 rounded-xl object-cover ring-1 ring-hg-violet/40 min-[400px]:hidden" />
            <span className="hidden min-[400px]:block"><Logo size="sm" /></span>
          </Link>
          <div className="flex shrink-0 items-center gap-2">
            <LanguageSwitcher compact />
            <Link to="/" className="inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-sm font-medium text-muted2 transition-colors hover:bg-hg-violet/10 hover:text-ink" data-testid="legal-back">
              <ArrowLeft size={15} /> <span className="hidden min-[380px]:inline">{l === "hi" ? "वापस" : "Back"}</span>
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 pb-12 pt-6 sm:px-5 sm:pt-8">
        <nav className="-mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0" aria-label="Policies">
          <div className="flex w-max gap-2 sm:w-auto sm:flex-wrap">
            {Object.keys(DOC).map((k) => {
              const on = k === slug;
              return (
                <Link key={k} to={`/legal/${k}`} aria-current={on ? "page" : undefined}
                  className={`relative whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors ${on ? "text-white" : "hg-chip-off hover:text-ink"}`} data-testid={`legal-link-${k}`}>
                  {on && <motion.span layoutId="legal-chip" className="hg-chip-on absolute inset-0 rounded-full" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
                  <span className="relative">{DOC[k].title[l]}</span>
                </Link>
              );
            })}
          </div>
        </nav>

        <AnimatePresence mode="wait">
          <motion.article key={`${slug}-${l}`} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            className="hg-card mt-5 p-5 sm:p-8">
            <div className="flex items-center gap-3">
              <span className="hg-icon-chip !h-10 !w-10 shrink-0 !rounded-xl"><FileText size={18} /></span>
              <h1 className="min-w-0 break-words font-display text-2xl font-bold text-ink sm:text-3xl" data-testid="legal-title">{doc.title[l]}</h1>
            </div>
            <div className="mt-5 h-px w-full bg-gradient-to-r from-hg-violet/60 via-hg-lavender/30 to-transparent" />
            <div className="mt-6 space-y-5">
              {doc.body[l].map((p, i) => (
                <motion.p key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 + i * 0.04, duration: 0.3 }}
                  className={`break-words text-[15px] leading-7 text-muted2 sm:text-base sm:leading-8 ${l === "hi" ? "font-hindi" : ""}`} data-testid={`legal-para-${i + 1}`}>{p}</motion.p>
              ))}
            </div>
          </motion.article>
        </AnimatePresence>

        <footer className="mt-8 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 border-t border-brand-50 pt-6 text-sm">
          {Object.keys(DOC).map((k) => (
            <Link key={k} to={`/legal/${k}`} className={`font-medium transition-colors ${k === slug ? "text-hg-lavender" : "text-muted2 hover:text-ink"}`}>
              {DOC[k].title[l]}
            </Link>
          ))}
        </footer>
      </main>
    </div>
  );
}
