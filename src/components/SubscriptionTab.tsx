import React, { useState } from "react";
import { AppData, SubscriptionPlan } from "../types";
import { Language, t } from "../lib/i18n";
import { Check, Sparkles, CreditCard, Download, ShieldCheck, Zap } from "lucide-react";

interface SubscriptionTabProps {
  data: AppData;
  lang: Language;
  onSelectPlan: (plan: SubscriptionPlan, cycle: "monthly" | "annual") => void;
  onCancelSubscription: () => void;
  onDownloadInvoice: (invoiceId: string) => void;
}

export const SubscriptionTab: React.FC<SubscriptionTabProps> = ({
  data,
  lang,
  onSelectPlan,
  onCancelSubscription,
  onDownloadInvoice,
}) => {
  const [billingCycle, setBillingCycle] = useState<"monthly" | "annual">(
    data.subscription.billingCycle || "monthly"
  );

  const currentPlan = data.plans.find(p => p.id === data.subscription.planId) || data.plans[1];
  const quotaUsed = data.subscription.clipsUsedThisMonth;
  const quotaTotal = data.subscription.clipsQuotaThisMonth;
  const quotaPercent = Math.min(100, Math.round((quotaUsed / quotaTotal) * 100));

  return (
    <div style={{ display: "grid", gap: 20 }}>
      {/* Current Active Plan Overview */}
      <div className="panel">
        <div className="ph2">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Sparkles size={22} color="var(--accent)" />
            <div>
              <h3>{t("Тарифный план", lang)}: {currentPlan.name}</h3>
              <span className="muted small">
                {lang === "en"
                  ? `Renews on ${data.subscription.renewalDate} · ${data.subscription.paymentMethod}`
                  : `Автопродление ${data.subscription.renewalDate} · ${data.subscription.paymentMethod}`}
              </span>
            </div>
          </div>
          <span className="chip good">{t("Активен", lang)}</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginTop: 10 }}>
          {/* Quota Progress */}
          <div style={{ padding: 16, borderRadius: 14, background: "var(--panel-2)", border: "1px solid var(--line)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
              <span style={{ fontWeight: 600 }}>{t("Квота клипов за месяц", lang)}</span>
              <span className="mono font-bold">{quotaUsed} / {quotaTotal}</span>
            </div>
            <div className="meter" style={{ height: 10 }}>
              <i style={{ width: `${quotaPercent}%`, background: "var(--accent)" }} />
            </div>
            <span className="muted small" style={{ display: "block", marginTop: 6 }}>
              {Math.max(0, quotaTotal - quotaUsed)} {lang === "en" ? "clips remaining this cycle" : "клипов осталось до обновления"}
            </span>
          </div>

          {/* Stream Hours */}
          <div style={{ padding: 16, borderRadius: 14, background: "var(--panel-2)", border: "1px solid var(--line)" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--mute)", marginBottom: 4 }}>
              {t("Часов стримов обработано", lang)}
            </div>
            <div style={{ fontSize: 26, fontWeight: 800 }}>
              {data.subscription.streamsProcessedHours} <span style={{ fontSize: 14, fontWeight: 500, color: "var(--mute)" }}>{lang === "en" ? "hours" : "часов"}</span>
            </div>
            <span className="muted small" style={{ display: "block", marginTop: 4 }}>
              {lang === "en" ? "24/7 AI audio & chat analysis" : "Анализ эфиров через Gemini 4"}
            </span>
          </div>

          {/* Channels Allowed */}
          <div style={{ padding: 16, borderRadius: 14, background: "var(--panel-2)", border: "1px solid var(--line)" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--mute)", marginBottom: 4 }}>
              {lang === "en" ? "Connected Channels" : "Подключено каналов"}
            </div>
            <div style={{ fontSize: 26, fontWeight: 800 }}>
              {data.channels.length} <span style={{ fontSize: 14, fontWeight: 500, color: "var(--mute)" }}>/ {currentPlan.maxChannels}</span>
            </div>
            <span className="muted small" style={{ display: "block", marginTop: 4 }}>
              {lang === "en" ? "Twitch streamer workspaces" : "Стримерских каналов в тарифе"}
            </span>
          </div>
        </div>
      </div>

      {/* Subscription Plans Pricing Table */}
      <div className="panel">
        <div style={{ textAlign: "center", maxWidth: 640, margin: "0 auto 24px" }}>
          <h2 style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.01em", marginBottom: 8 }}>
            {t("Выберите тариф", lang)}
          </h2>
          <p className="muted">
            {lang === "en"
              ? "All plans include 24/7 Twitch monitoring, silence trimming, automatic subtitles, and multi-platform sync."
              : "Все тарифы включают круглосуточный мониторинг Twitch, удаление пауз, субтитры и публикацию в TikTok, Shorts и Reels."}
          </p>

          {/* Billing Cycle Toggle */}
          <div style={{ display: "inline-flex", alignItems: "center", gap: 10, marginTop: 18, padding: 4, borderRadius: 12, background: "var(--panel-2)", border: "1px solid var(--line)" }}>
            <button
              type="button"
              className={`mini ${billingCycle === "monthly" ? "acc" : ""}`}
              style={{ border: 0, padding: "6px 14px", borderRadius: 8 }}
              onClick={() => setBillingCycle("monthly")}
            >
              {t("Ежемесячно", lang)}
            </button>
            <button
              type="button"
              className={`mini ${billingCycle === "annual" ? "acc" : ""}`}
              style={{ border: 0, padding: "6px 14px", borderRadius: 8 }}
              onClick={() => setBillingCycle("annual")}
            >
              {t("Ежегодно (-20%)", lang)}
            </button>
          </div>
        </div>

        {/* Pricing Cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 18 }}>
          {data.plans.map(plan => {
            const isCurrent = plan.id === data.subscription.planId;
            const price = billingCycle === "annual" ? plan.priceAnnual : plan.priceMonthly;

            return (
              <div
                key={plan.id}
                style={{
                  borderRadius: 18,
                  border: `2px solid ${isCurrent ? "var(--accent)" : "var(--line)"}`,
                  background: isCurrent ? "var(--panel-2)" : "var(--panel)",
                  padding: 24,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  position: "relative",
                  boxShadow: isCurrent ? "0 12px 30px -10px rgba(47, 107, 255, 0.25)" : "none",
                }}
              >
                {plan.badge && (
                  <span
                    style={{
                      position: "absolute",
                      top: -12,
                      right: 20,
                      background: "var(--accent)",
                      color: "#fff",
                      fontSize: 11,
                      fontWeight: 800,
                      padding: "3px 10px",
                      borderRadius: 99,
                      textTransform: "uppercase",
                    }}
                  >
                    {plan.badge}
                  </span>
                )}

                <div>
                  <h4 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>{plan.name}</h4>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 16 }}>
                    <span style={{ fontSize: 36, fontWeight: 800 }}>${price}</span>
                    <span className="muted" style={{ fontSize: 14 }}>
                      / {lang === "en" ? "month" : "мес"}
                    </span>
                  </div>

                  <div style={{ display: "grid", gap: 10, marginBottom: 24, fontSize: 13.5 }}>
                    {plan.features.map((feat, fi) => (
                      <div key={fi} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                        <Check size={16} color="var(--accent)" style={{ flexShrink: 0, marginTop: 2 }} />
                        <span>{feat}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  {isCurrent ? (
                    <button
                      type="button"
                      className="btn"
                      style={{ width: "100%", fontWeight: 700 }}
                      disabled
                    >
                      ✓ {t("Текущий план", lang)}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn amber"
                      style={{ width: "100%" }}
                      onClick={() => onSelectPlan(plan, billingCycle)}
                    >
                      {t("Перейти на тариф", lang)}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Invoices & Billing History */}
      <div className="panel">
        <div className="ph2">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CreditCard size={18} color="var(--accent)" />
            <h3>{t("История счетов", lang)}</h3>
          </div>
          <span className="muted small">
            {lang === "en" ? "Invoices & receipts" : "Квитанции и чеки"}
          </span>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("Счёт", lang)}</th>
                <th>{t("Дата", lang)}</th>
                <th>{t("Тарифный план", lang)}</th>
                <th>{t("Сумма", lang)}</th>
                <th>{t("Статус", lang)}</th>
                <th className="r">{lang === "en" ? "Receipt" : "Квитанция"}</th>
              </tr>
            </thead>
            <tbody>
              {data.invoices.map(inv => (
                <tr key={inv.id}>
                  <td className="mono font-semibold">{inv.id}</td>
                  <td className="muted small">{inv.date}</td>
                  <td><b>{inv.planName}</b></td>
                  <td className="mono font-bold">${inv.amount}.00</td>
                  <td>
                    <span className="chip good">{t("Оплачено", lang)}</span>
                  </td>
                  <td className="r">
                    <button
                      type="button"
                      className="mini"
                      onClick={() => onDownloadInvoice(inv.id)}
                    >
                      <Download size={12} /> {t("Скачать", lang)}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
