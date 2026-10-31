import React, { useState } from "react";
import { AppData, StreamerChannel } from "../types";
import { Language, t } from "../lib/i18n";
import { PlusCircle, Radio, Trash2, ExternalLink, CheckCircle2, User } from "lucide-react";

interface ChannelsTabProps {
  data: AppData;
  activeChannel: StreamerChannel;
  lang: Language;
  onSelectChannel: (channelId: string) => void;
  onOpenAddChannelModal: () => void;
  onRemoveChannel: (channel: StreamerChannel) => void;
}

export const ChannelsTab: React.FC<ChannelsTabProps> = ({
  data,
  activeChannel,
  lang,
  onSelectChannel,
  onOpenAddChannelModal,
  onRemoveChannel,
}) => {
  const currentPlan = data.plans.find(p => p.id === data.subscription.planId) || data.plans[1];
  const maxChannels = currentPlan.maxChannels;
  const canAddMore = data.channels.length < maxChannels;

  return (
    <div style={{ display: "grid", gap: 20 }}>
      {/* Channels Overview Card */}
      <div className="panel">
        <div className="ph2">
          <div>
            <h3>{t("Каналы и стримеры", lang)}</h3>
            <span className="muted small">
              {data.channels.length} {lang === "en" ? `of ${maxChannels} channels connected` : `из ${maxChannels} доступно в тарифе ${currentPlan.name}`}
            </span>
          </div>

          <button
            type="button"
            className="btn amber"
            disabled={!canAddMore}
            onClick={onOpenAddChannelModal}
          >
            <PlusCircle size={16} />
            <span>{t("Подключить канал", lang)}</span>
          </button>
        </div>

        {!canAddMore && (
          <div className="alert info" style={{ marginBottom: 16 }}>
            {lang === "en"
              ? `You have reached the channel limit (${maxChannels}) for your ${currentPlan.name} plan. Upgrade to Agency & Studio to connect up to 5 streamer channels.`
              : `Достигнут лимит каналов (${maxChannels}) в тарифе ${currentPlan.name}. Перейдите на тариф Agency & Studio, чтобы подключить до 5 стримеров.`}
          </div>
        )}

        {/* Streamers Grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
          {data.channels.map(ch => {
            const isActive = ch.id === activeChannel.id;
            const twitchUrl = `https://twitch.tv/${ch.twitchLogin}`;

            return (
              <div
                key={ch.id}
                style={{
                  borderRadius: 16,
                  border: `2px solid ${isActive ? "var(--accent)" : "var(--line)"}`,
                  background: isActive ? "var(--panel-2)" : "var(--panel)",
                  padding: 20,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  gap: 16,
                  boxShadow: isActive ? "0 8px 24px -10px rgba(47, 107, 255, 0.3)" : "none",
                }}
              >
                <div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div
                        style={{
                          width: 44,
                          height: 44,
                          borderRadius: "50%",
                          background: "#9146FF",
                          display: "grid",
                          placeItems: "center",
                          color: "#fff",
                          fontWeight: 800,
                          fontSize: 18,
                        }}
                      >
                        {ch.displayName.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <b style={{ fontSize: 16, display: "block" }}>{ch.displayName}</b>
                        <a
                          href={twitchUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="muted small"
                          style={{ display: "inline-flex", alignItems: "center", gap: 4, textDecoration: "none" }}
                        >
                          twitch.tv/{ch.twitchLogin} <ExternalLink size={11} />
                        </a>
                      </div>
                    </div>

                    <span className={`chip ${ch.status === "live" ? "good" : ""}`}>
                      {ch.status === "live" ? (
                        <>
                          <Radio size={12} className="live-dot" /> LIVE ({ch.viewers?.toLocaleString()})
                        </>
                      ) : (
                        t("Оффлайн", lang)
                      )}
                    </span>
                  </div>

                  {ch.currentStreamTitle && (
                    <div
                      style={{
                        padding: "8px 10px",
                        borderRadius: 8,
                        background: "var(--panel)",
                        border: "1px solid var(--line)",
                        fontSize: 12.5,
                        color: "var(--ink)",
                        marginBottom: 12,
                      }}
                    >
                      📺 {ch.currentStreamTitle}
                    </div>
                  )}

                  {/* Connected Platforms */}
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span className="muted small">{lang === "en" ? "Auto-Publish:" : "Автопостинг:"}</span>
                    <span className="mini" style={{ opacity: ch.platforms.tiktok ? 1 : 0.4 }}>
                      TikTok {ch.platforms.tiktok ? "✓" : "—"}
                    </span>
                    <span className="mini" style={{ opacity: ch.platforms.youtube ? 1 : 0.4 }}>
                      Shorts {ch.platforms.youtube ? "✓" : "—"}
                    </span>
                    <span className="mini" style={{ opacity: ch.platforms.instagram ? 1 : 0.4 }}>
                      Reels {ch.platforms.instagram ? "✓" : "—"}
                    </span>
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                  <span className="muted small">
                    {ch.clipsCount} {lang === "en" ? "clips created" : "клипов нарезано"}
                  </span>

                  <div style={{ display: "flex", gap: 8 }}>
                    {isActive ? (
                      <span className="chip good">✓ {lang === "en" ? "Selected" : "Выбран"}</span>
                    ) : (
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() => onSelectChannel(ch.id)}
                      >
                        {t("Переключить", lang)}
                      </button>
                    )}

                    {data.channels.length > 1 && (
                      <button
                        type="button"
                        className="iconbtn"
                        onClick={() => onRemoveChannel(ch)}
                        title={lang === "en" ? "Remove channel" : "Удалить канал"}
                      >
                        <Trash2 size={14} color="var(--bad)" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
