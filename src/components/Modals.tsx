import React, { useState } from "react";
import { Clip, SubscriptionPlan, StreamerChannel } from "../types";
import { Language, t } from "../lib/i18n";
import { X, Check, Sparkles, PlusCircle } from "lucide-react";

// Confirmation Dialog Modal
interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  body: string | React.ReactNode;
  yesText?: string;
  danger?: boolean;
  requiredWord?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  lang: Language;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  title,
  body,
  yesText = "Да",
  danger = false,
  requiredWord = null,
  onConfirm,
  onCancel,
  lang,
}) => {
  const [typedWord, setTypedWord] = useState("");

  if (!isOpen) return null;

  const isWordValid = !requiredWord || typedWord.trim().toUpperCase() === requiredWord.toUpperCase();

  return (
    <div className="modal-overlay">
      <div className="modal-card">
        <div className="modal-header">
          <h3>{title}</h3>
          <button type="button" className="modal-close" onClick={onCancel}>
            <X size={20} />
          </button>
        </div>

        <div style={{ fontSize: 14.5, lineHeight: 1.5, color: "var(--ink)", marginBottom: 16 }}>
          {body}
        </div>

        {requiredWord && (
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
              {lang === "en" ? `Type '${requiredWord}' to confirm:` : `Чтобы подтвердить, напишите «${requiredWord}»:`}
            </label>
            <input
              type="text"
              className="inp"
              placeholder={requiredWord}
              value={typedWord}
              onChange={e => setTypedWord(e.target.value)}
              autoFocus
            />
          </div>
        )}

        <div className="modal-actions">
          <button type="button" className="btn" onClick={onCancel}>
            {t("Отмена", lang)}
          </button>
          <button
            type="button"
            className={`btn ${danger ? "danger" : "amber"}`}
            disabled={!isWordValid}
            onClick={() => {
              if (isWordValid) onConfirm();
            }}
          >
            {yesText}
          </button>
        </div>
      </div>
    </div>
  );
};

// Plan Upgrade / Change Modal
interface UpgradePlanModalProps {
  isOpen: boolean;
  plans: SubscriptionPlan[];
  currentPlanId: string;
  billingCycle: "monthly" | "annual";
  lang: Language;
  onSelectPlan: (plan: SubscriptionPlan, cycle: "monthly" | "annual") => void;
  onClose: () => void;
}

export const UpgradePlanModal: React.FC<UpgradePlanModalProps> = ({
  isOpen,
  plans,
  currentPlanId,
  billingCycle: initialCycle,
  lang,
  onSelectPlan,
  onClose,
}) => {
  const [cycle, setCycle] = useState<"monthly" | "annual">(initialCycle);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-card wide">
        <div className="modal-header">
          <h3>{t("Выберите тариф", lang)}</h3>
          <button type="button" className="modal-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div style={{ display: "inline-flex", gap: 8, padding: 4, borderRadius: 10, background: "var(--panel-2)", border: "1px solid var(--line)" }}>
            <button
              type="button"
              className={`mini ${cycle === "monthly" ? "acc" : ""}`}
              onClick={() => setCycle("monthly")}
            >
              {t("Ежемесячно", lang)}
            </button>
            <button
              type="button"
              className={`mini ${cycle === "annual" ? "acc" : ""}`}
              onClick={() => setCycle("annual")}
            >
              {t("Ежегодно (-20%)", lang)}
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
          {plans.map(p => {
            const isCurrent = p.id === currentPlanId;
            const price = cycle === "annual" ? p.priceAnnual : p.priceMonthly;

            return (
              <div
                key={p.id}
                style={{
                  padding: 18,
                  borderRadius: 14,
                  border: `2px solid ${isCurrent ? "var(--accent)" : "var(--line)"}`,
                  background: isCurrent ? "var(--panel-2)" : "var(--panel)",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
                    <b style={{ fontSize: 16 }}>{p.name}</b>
                    <span className="mono font-bold" style={{ fontSize: 20 }}>${price}/мес</span>
                  </div>

                  <div style={{ display: "grid", gap: 6, fontSize: 12.5, color: "var(--mute)", margin: "14px 0" }}>
                    <div>• До {p.clipsPerDay} клипов в день ({p.maxClipsPerMonth}/мес)</div>
                    <div>• До {p.maxChannels} стримеров</div>
                    <div>• Качество: {p.quality}</div>
                  </div>
                </div>

                <button
                  type="button"
                  className={`btn ${isCurrent ? "" : "amber"} sm`}
                  style={{ width: "100%" }}
                  disabled={isCurrent}
                  onClick={() => {
                    onSelectPlan(p, cycle);
                    onClose();
                  }}
                >
                  {isCurrent ? `✓ ${t("Текущий план", lang)}` : t("Перейти на тариф", lang)}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// Add Streamer Channel Modal
interface AddChannelModalProps {
  isOpen: boolean;
  lang: Language;
  onAddChannel: (login: string, displayName: string, platforms: { tiktok: boolean; youtube: boolean; instagram: boolean }) => void;
  onClose: () => void;
}

export const AddChannelModal: React.FC<AddChannelModalProps> = ({
  isOpen,
  lang,
  onAddChannel,
  onClose,
}) => {
  const [login, setLogin] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [platforms, setPlatforms] = useState({ tiktok: true, youtube: true, instagram: true });

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!login.trim()) return;
    onAddChannel(
      login.trim().toLowerCase(),
      displayName.trim() || login.trim(),
      platforms
    );
    setLogin("");
    setDisplayName("");
    onClose();
  };

  return (
    <div className="modal-overlay">
      <div className="modal-card">
        <div className="modal-header">
          <h3>{t("Подключить канал", lang)}</h3>
          <button type="button" className="modal-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "grid", gap: 14 }}>
          <div>
            <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
              {lang === "en" ? "Twitch Channel Login / Username" : "Логин стримера на Twitch"}
            </label>
            <input
              type="text"
              className="inp"
              placeholder="e.g. buster, evelone192, zubarefff"
              value={login}
              onChange={e => setLogin(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div>
            <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
              {lang === "en" ? "Display Name (optional)" : "Отображаемое имя (необязательно)"}
            </label>
            <input
              type="text"
              className="inp"
              placeholder={login || "Buster"}
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
            />
          </div>

          <div>
            <span style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              {lang === "en" ? "Auto-Publish Platforms" : "Площадки для автопостинга"}
            </span>
            <div style={{ display: "grid", gap: 8 }}>
              {[
                { key: "tiktok" as const, label: "TikTok" },
                { key: "youtube" as const, label: "YouTube Shorts" },
                { key: "instagram" as const, label: "Instagram Reels" },
              ].map(p => (
                <label key={p.key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13.5, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={platforms[p.key]}
                    onChange={e => setPlatforms(prev => ({ ...prev, [p.key]: e.target.checked }))}
                  />
                  <span>{p.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="modal-actions" style={{ marginTop: 12 }}>
            <button type="button" className="btn" onClick={onClose}>
              {t("Отмена", lang)}
            </button>
            <button type="submit" className="btn amber" disabled={!login.trim()}>
              <PlusCircle size={15} />
              <span>{t("Подключить канал", lang)}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Video Playback Modal
interface VideoModalProps {
  isOpen: boolean;
  clip: Clip | null;
  lang: Language;
  onClose: () => void;
}

export const VideoModal: React.FC<VideoModalProps> = ({
  isOpen,
  clip,
  lang,
  onClose,
}) => {
  if (!isOpen || !clip) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ maxWidth: 440 }}>
        <div className="modal-header" style={{ marginBottom: 12 }}>
          <h3 style={{ fontSize: 18, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {clip.overlay}
          </h3>
          <button type="button" className="modal-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div
          style={{
            position: "relative",
            width: "100%",
            aspectRatio: "9/16",
            borderRadius: 16,
            background: "#000",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            padding: 20,
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 44, marginBottom: 12 }}>🎬</div>
          <b style={{ fontSize: 18, marginBottom: 6 }}>{clip.overlay}</b>
          <p style={{ fontSize: 13, color: "#94A3B8", maxWidth: "80%" }}>
            {clip.what || clip.why}
          </p>

          <div
            style={{
              position: "absolute",
              bottom: 24,
              left: 16,
              right: 16,
              padding: "8px 12px",
              borderRadius: 8,
              background: "rgba(0,0,0,0.6)",
              fontSize: 12,
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <span>Score: {clip.score}/10</span>
            <span>Duration: {clip.duration}s</span>
          </div>
        </div>

        <div className="modal-actions" style={{ marginTop: 16 }}>
          <button type="button" className="btn amber" onClick={onClose}>
            {t("Закрыть", lang)}
          </button>
        </div>
      </div>
    </div>
  );
};
