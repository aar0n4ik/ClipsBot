import React from "react";
import { AppData, StreamerChannel } from "../types";
import { Language, t } from "../lib/i18n";
import { Moon, Sun, Globe, Sparkles, ChevronDown } from "lucide-react";

interface HeaderProps {
  data: AppData;
  activeChannel: StreamerChannel;
  channels: StreamerChannel[];
  onSelectChannel: (channelId: string) => void;
  lang: Language;
  onLangChange: (lang: Language) => void;
  theme: string;
  onToggleTheme: () => void;
  onOpenSubscription: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  data,
  activeChannel,
  channels,
  onSelectChannel,
  lang,
  onLangChange,
  theme,
  onToggleTheme,
  onOpenSubscription,
}) => {
  const isDark = theme === "dark";
  const twitchUrl = `https://twitch.tv/${activeChannel.twitchLogin}`;
  const plan = data.plans.find(p => p.id === data.subscription.planId) || data.plans[1];

  return (
    <header className="top">
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <h1 className="logo">
          Clips<b>SaaS</b>
        </h1>

        {/* Streamer Workspace Channel Selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ position: "relative", display: "inline-block" }}>
            <select
              className="sel"
              style={{
                fontWeight: 700,
                paddingRight: 28,
                background: "var(--panel)",
                borderColor: "var(--line)",
                cursor: "pointer",
              }}
              value={activeChannel.id}
              onChange={e => onSelectChannel(e.target.value)}
              title={lang === "en" ? "Select streamer channel" : "Выбрать стримера"}
            >
              {channels.map(ch => (
                <option key={ch.id} value={ch.id}>
                  {ch.displayName} {ch.status === "live" ? "🔴 LIVE" : ""}
                </option>
              ))}
            </select>
          </div>

          <a
            className="tw"
            href={twitchUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="Open Twitch Stream"
          >
            <svg viewBox="-1.5 -1.5 19 19" aria-hidden="true">
              <path d="M3.857 0 1 2.857v10.286h3.429V16l2.857-2.857H9.57L14.714 8V0zm9.714 7.429-2.285 2.285H9l-2 2v-2H4.429V1.143h9.142z" />
              <path d="M11.857 3.143h-1.143V6.57h1.143zm-3.143 0H7.571V6.57h1.143z" />
            </svg>
            <span>{activeChannel.displayName}</span>
            {activeChannel.status === "live" && (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  fontSize: 12,
                  color: "var(--live)",
                  fontWeight: 700,
                }}
              >
                <span className="live-dot" />
                {activeChannel.viewers ? `${activeChannel.viewers.toLocaleString()} зрит.` : "LIVE"}
              </span>
            )}
          </a>
        </div>
      </div>

      <div className="top-actions">
        {/* Active Subscription Plan Badge */}
        <button
          type="button"
          className="mini acc"
          style={{
            padding: "6px 12px",
            borderRadius: 999,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
          onClick={onOpenSubscription}
          title={lang === "en" ? "Manage Subscription & Quota" : "Управление тарифом и квотами"}
        >
          <Sparkles size={14} />
          <span>{plan.name}</span>
          <span style={{ opacity: 0.75, fontSize: 11 }}>
            ({data.subscription.clipsUsedThisMonth}/{data.subscription.clipsQuotaThisMonth})
          </span>
        </button>

        {/* Language switch */}
        <button
          type="button"
          className="iconbtn"
          onClick={() => onLangChange(lang === "ru" ? "en" : "ru")}
          title="Switch Language"
        >
          <Globe size={15} />
          <span>{lang === "ru" ? "EN" : "RU"}</span>
        </button>

        {/* Theme switch */}
        <button
          type="button"
          className="iconbtn"
          onClick={onToggleTheme}
          title={isDark ? "Light theme" : "Dark theme"}
        >
          {isDark ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </header>
  );
};
