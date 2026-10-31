import React, { useState } from "react";
import { AppData, Clip, GroupedClip, StreamerChannel } from "../types";
import { Language, t } from "../lib/i18n";
import { Play, TrendingUp, CheckCircle, Video, Sparkles, Film, Clock, Zap } from "lucide-react";

interface OverviewTabProps {
  data: AppData;
  activeChannel: StreamerChannel;
  grouped: Record<string, GroupedClip>;
  lang: Language;
  onNavigateTab: (tab: any) => void;
  onPlayClip?: (clip: Clip) => void;
  onOpenUpgradeModal: () => void;
}

export const OverviewTab: React.FC<OverviewTabProps> = ({
  data,
  activeChannel,
  grouped,
  lang,
  onNavigateTab,
  onPlayClip,
  onOpenUpgradeModal,
}) => {
  const [selectedPeriod, setSelectedPeriod] = useState<"today" | "7" | "30" | "all">("7");
  const [activePhaseIndex, setActivePhaseIndex] = useState<number>(() => {
    const P = data.status.process || {};
    if (activeChannel.status === "live") {
      if (P.stage_id === "render") return 5;
      if (P.stage_id === "video") return 4;
      if (P.stage_id === "judge" || P.stage_id === "speech") return 3;
      if (P.stage_id === "peaks" || P.stage_id === "scout") return 2;
      return 1;
    }
    return 0;
  });

  const stages = [
    { title: t("Нет стрима", lang), sub: lang === "en" ? "checks every 10 min" : "проверка раз в 10 минут" },
    { title: t("Идёт стрим", lang), sub: lang === "en" ? "1-hour chunks" : "запись фрагментами по часу" },
    { title: t("Поиск", lang), sub: lang === "en" ? "audio, chat, viewer clips" : "звук, чат, клипы зрителей" },
    { title: t("Анализ", lang), sub: lang === "en" ? "AI speech evaluation" : "ИИ оценивает речь" },
    { title: t("Видео", lang), sub: lang === "en" ? "AI watches video frames" : "ИИ смотрит кадры" },
    { title: t("Монтаж", lang), sub: lang === "en" ? "9:16, subtitles, audio" : "9:16, субтитры, звук" },
    { title: t("Публикация", lang), sub: lang === "en" ? "TikTok, Shorts, Reels" : "TikTok, Shorts, Reels" },
  ];

  // Stats calculation
  const totalViews = data.posts.reduce((sum, p) => sum + (p.views || 0), 0);
  const readyClips = data.clips.filter(c => c.status === "ready");
  const publishedClips = data.clips.filter(c => c.status === "posted" || c.status === "used");

  // Top 5 clips
  const topClips = Object.values(grouped)
    .sort((a, b) => b.bestViews - a.bestViews)
    .slice(0, 5);

  // Daily views bar chart (last 28 days)
  const historyDays: Record<string, number> = {};
  data.posts.forEach(p => {
    if (p.history) {
      Object.entries(p.history).forEach(([day, v]) => {
        historyDays[day] = (historyDays[day] || 0) + v;
      });
    }
  });

  const sortedDays = Object.keys(historyDays).sort().slice(-28);
  const maxDayViews = Math.max(...sortedDays.map(d => historyDays[d] || 0), 100);

  // Subscription plan & quota
  const currentPlan = data.plans.find(p => p.id === data.subscription.planId) || data.plans[1];
  const quotaUsed = data.subscription.clipsUsedThisMonth;
  const quotaTotal = data.subscription.clipsQuotaThisMonth;
  const quotaPercent = Math.min(100, Math.round((quotaUsed / quotaTotal) * 100));
  const remainingClips = Math.max(0, quotaTotal - quotaUsed);

  // Platform breakdown
  const platformViews: Record<string, number> = { tiktok: 0, youtube: 0, instagram: 0 };
  data.posts.forEach(p => {
    if (platformViews[p.platform] !== undefined) {
      platformViews[p.platform] += p.views || 0;
    }
  });

  return (
    <div style={{ display: "grid", gap: 20 }}>
      {/* Hero Header Section */}
      <div className="hero">
        <div className="hero-content">
          <div className="hero-left">
            <h2>
              {activeChannel.status === "live" ? (
                <>
                  {activeChannel.displayName} <em>LIVE</em>
                </>
              ) : (
                <>
                  {lang === "en" ? "MONITORING" : "СЛЕЖУ ЗА"} <em>{activeChannel.displayName.toUpperCase()}</em>
                </>
              )}
            </h2>
            <p className="lead">
              {activeChannel.status === "live"
                ? `${activeChannel.currentStreamTitle || "Twitch live stream"} · ${activeChannel.viewers ? activeChannel.viewers.toLocaleString() : 0} ${lang === "en" ? "live viewers" : "зрителей в эфире"}`
                : lang === "en"
                ? "The SaaS engine listens to stream recordings 24/7, detects high-virality hooks, formats 9:16 vertical shorts, and auto-publishes to TikTok, Shorts, and Reels."
                : "Сервис круглосуточно сканирует эфиры, находит лучшие моменты, монтирует 9:16 клипы с субтитрами и публикует во все соцсети по расписанию."}
            </p>

            <div className="hero-stats">
              <div>
                <b>{readyClips.length}</b>
                <span>{lang === "en" ? "Ready in queue" : "Готово в очереди"}</span>
              </div>
              <div>
                <b>{publishedClips.length}</b>
                <span>{lang === "en" ? "Published clips" : "Опубликовано"}</span>
              </div>
              <div>
                <b>{data.subscription.streamsProcessedHours} ч</b>
                <span>{lang === "en" ? "Stream hours parsed" : "Часов обработано"}</span>
              </div>
            </div>

            <div className="hero-log">
              <div className="hero-log-head">
                <span>
                  <i />
                  {t("Журнал бота", lang)}
                </span>
                <span className="mono">{lang === "en" ? "Auto-Pilot" : "Автопилот"}</span>
              </div>
              <div className="log-entry">
                <time className="mono">19:07</time>
                <span>{lang === "en" ? "Scheduled slot release for audience peak" : "Публикация в вечерний пик просмотров"}</span>
              </div>
              <div className="log-entry">
                <time className="mono">18:42</time>
                <span>{lang === "en" ? "AI Director verified video candidate (9/10 score)" : "ИИ проверил кадры финалиста (оценка 9/10)"}</span>
              </div>
              <div className="log-entry">
                <time className="mono">17:15</time>
                <span>{lang === "en" ? "Auto-trimmed 3.4s silence from latest highlight" : "Вырезано 3.4 сек пауз и добавлены субтитры"}</span>
              </div>
            </div>
          </div>

          <div className="hero-right">
            <div className="stage-window">
              <div className="stage-bar">
                <i />
                <i />
                <i />
                <span className="mono" style={{ marginLeft: 6 }}>
                  {stages[activePhaseIndex]?.title}
                </span>
              </div>
              <div className="stage-body">
                {activePhaseIndex === 0 && (
                  <div style={{ textAlign: "center", color: "#94A3B8" }}>
                    <div style={{ fontSize: 36, marginBottom: 8 }}>🛰️</div>
                    <b style={{ color: "#fff", display: "block", fontSize: 16 }}>
                      {lang === "en" ? "Waiting for stream" : "Ожидание начала эфира"}
                    </b>
                    <span style={{ fontSize: 13 }}>
                      {lang === "en"
                        ? "Checking Twitch every 10 minutes. Live broadcasts and VODs will be processed automatically."
                        : "Бот проверяет Twitch каждые 10 минут. Новые трансляции будут нарезаны автоматически."}
                    </span>
                  </div>
                )}

                {activePhaseIndex === 1 && (
                  <div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                      <span className="chip good">LIVE NOW</span>
                      <span className="mono small" style={{ color: "#94A3B8" }}>
                        {activeChannel.viewers ? activeChannel.viewers.toLocaleString() : 0} {lang === "en" ? "viewers" : "зрит."}
                      </span>
                    </div>
                    <b style={{ color: "#fff", fontSize: 15, display: "block", marginBottom: 6 }}>
                      {activeChannel.currentStreamTitle || "Twitch stream"}
                    </b>
                    <div style={{ marginTop: 14 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#94A3B8", marginBottom: 4 }}>
                        <span>{lang === "en" ? "Recording segment" : "Идёт запись фрагмента"}</span>
                        <span className="mono">42:15 / 60:00</span>
                      </div>
                      <div className="meter" style={{ background: "rgba(255,255,255,0.1)" }}>
                        <i style={{ width: "70%", background: "#4C8DFF" }} />
                      </div>
                    </div>
                  </div>
                )}

                {activePhaseIndex === 2 && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 12.5, color: "#94A3B8" }}>
                      <b>{lang === "en" ? "Scouting moments" : "Поиск ярких моментов"}</b>
                      <span>12 peaks detected</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "flex-end", height: 80, gap: 3, marginBottom: 10 }}>
                      {[30, 45, 25, 60, 95, 40, 70, 85, 30, 100, 50, 65, 40, 80, 55, 35, 90, 45, 20, 60].map((h, i) => (
                        <div
                          key={i}
                          style={{
                            flex: 1,
                            height: `${h}%`,
                            background: h > 75 ? "#FF9F1C" : "rgba(255,255,255,0.25)",
                            borderRadius: 2,
                          }}
                        />
                      ))}
                    </div>
                    <div style={{ fontSize: 12, color: "#CBD5E1" }}>
                      {lang === "en" ? "Audio spikes & chat reactions flagged 4 clip candidates" : "Анализ звука и активности чата выявил 4 момента"}
                    </div>
                  </div>
                )}

                {activePhaseIndex === 3 && (
                  <div>
                    <b style={{ color: "#fff", fontSize: 14, display: "block", marginBottom: 8 }}>
                      {lang === "en" ? "Speech Transcript & AI Score" : "Расшифровка речи и оценка"}
                    </b>
                    <div style={{ background: "rgba(255,255,255,0.06)", padding: 10, borderRadius: 8, fontSize: 13, color: "#E2E8F0", marginBottom: 10 }}>
                      «Клиентка выходит и говорит: вот тебе сто долларов на чай за скорость...»
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span className="chip good">{lang === "en" ? "Selected (Score 9/10)" : "Одобрено (Оценка 9/10)"}</span>
                      <span style={{ fontSize: 12, color: "#94A3B8" }}>{lang === "en" ? "Clear hook & punchline" : "Высокая виральность"}</span>
                    </div>
                  </div>
                )}

                {activePhaseIndex === 4 && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 13 }}>
                      <b style={{ color: "#fff" }}>{lang === "en" ? "Video Frame Review" : "Проверка видео на лаги"}</b>
                      <span className="chip good">Score 9/10</span>
                    </div>
                    <div style={{ position: "relative", height: 100, borderRadius: 8, background: "#1E293B", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <Video size={36} color="#4C8DFF" />
                      <div style={{ position: "absolute", bottom: 6, left: 8, fontSize: 11, color: "#fff" }}>
                        freezedetect: 0 freeze frames · 60fps OK
                      </div>
                    </div>
                    <p style={{ fontSize: 12, color: "#CBD5E1", marginTop: 8 }}>
                      {lang === "en" ? "Gemini 4 verified facecam framing and streamer reactions" : "ИИ проверил кадры, отсутствие лагов и центровку вебки"}
                    </p>
                  </div>
                )}

                {activePhaseIndex === 5 && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 13 }}>
                      <b style={{ color: "#fff" }}>{lang === "en" ? "Vertical Rendering (9:16)" : "Монтаж клипа (9:16)"}</b>
                      <span className="mono" style={{ color: "#4C8DFF" }}>1080×1920</span>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "80px 1fr", gap: 10, alignItems: "center" }}>
                      <div style={{ height: 110, borderRadius: 8, background: "#0F172A", border: "1px solid rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center", color: "#FFD23F", fontWeight: 800, fontSize: 12, textAlign: "center", padding: 4 }}>
                        ШТРАФ $200
                      </div>
                      <div style={{ fontSize: 12.5, color: "#CBD5E1", display: "grid", gap: 4 }}>
                        <div>• {lang === "en" ? "Length" : "Длина"}: 28s</div>
                        <div>• {lang === "en" ? "Silence trimmed" : "Вырезано пауз"}: 3.4s</div>
                        <div>• {lang === "en" ? "Subtitles" : "Субтитры"}: 2-line clean</div>
                      </div>
                    </div>
                  </div>
                )}

                {activePhaseIndex === 6 && (
                  <div>
                    <b style={{ color: "#fff", fontSize: 14, display: "block", marginBottom: 10 }}>
                      {lang === "en" ? "Synchronous Publishing" : "Синхронная публикация"}
                    </b>
                    <div style={{ display: "grid", gap: 6 }}>
                      {["TikTok", "YouTube Shorts", "Instagram Reels"].map((p, idx) => (
                        <div key={idx} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 10px", borderRadius: 8, background: "rgba(255,255,255,0.06)", fontSize: 13 }}>
                          <span>{p}</span>
                          <span style={{ color: "#5BE19A", display: "flex", alignItems: "center", gap: 4 }}>
                            <CheckCircle size={14} /> {lang === "en" ? "Published" : "Готово"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Railway Dock */}
        <div className="dock">
          <div className="rail">
            {stages.map((st, i) => {
              const isOn = activePhaseIndex === i;
              const isDone = activePhaseIndex > i;
              return (
                <button
                  key={i}
                  type="button"
                  className={`ri ${isOn ? "on" : isDone ? "done" : ""}`}
                  onClick={() => setActivePhaseIndex(i)}
                >
                  <span className="tr">
                    <i />
                  </span>
                  <b>{st.title}</b>
                  <span>{st.sub}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Subscription & Quota Card (Replaces old Money section) */}
      <div>
        <div className="ph2">
          <div>
            <h3>{t("Тариф и квота", lang) || (lang === "en" ? "Plan & Quotas" : "Тариф и квота")}</h3>
            <span className="muted small">
              {lang === "en"
                ? `Plan: ${currentPlan.name} · ${remainingClips} clips remaining until ${data.subscription.renewalDate}`
                : `Тариф: ${currentPlan.name} · Осталось ${remainingClips} клипов до ${data.subscription.renewalDate}`}
            </span>
          </div>

          <div className="seg">
            {(["today", "7", "30", "all"] as const).map(p => (
              <button
                key={p}
                type="button"
                className={selectedPeriod === p ? "on" : ""}
                onClick={() => setSelectedPeriod(p)}
              >
                {p === "today" ? t("Сегодня", lang) : p === "7" ? t("7 дней", lang) : p === "30" ? t("30 дней", lang) : t("Всё время", lang)}
              </button>
            ))}
          </div>
        </div>

        <div className="m-grid">
          {/* Plan Quota Ring Card */}
          <div className="m-pay">
            <div className="m-ring">
              <svg viewBox="0 0 100 100" style={{ transform: "rotate(-90deg)", width: "100%", height: "100%" }}>
                <circle cx="50" cy="50" r="40" stroke="rgba(255,255,255,0.25)" strokeWidth="9" fill="none" />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  stroke="#FFFFFF"
                  strokeWidth="9"
                  fill="none"
                  strokeDasharray="251.2"
                  strokeDashoffset={251.2 - (251.2 * quotaPercent) / 100}
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div className="m-pay-t">
              <span>{t("Квота клипов за месяц", lang)}</span>
              <h4>{quotaUsed} / {quotaTotal}</h4>
              <p>
                {remainingClips > 0
                  ? `${remainingClips} ${lang === "en" ? "clips remaining" : "клипов осталось"}`
                  : lang === "en" ? "Quota reached" : "Лимит исчерпан"}
              </p>
              <button
                type="button"
                className="m-btn"
                onClick={onOpenUpgradeModal}
              >
                {t("Сменить тариф", lang)}
              </button>
            </div>
          </div>

          {/* KPI Cards */}
          <div className="m-kpis">
            <div className="m-kpi-card">
              <div>
                <span className="m-kpi-lbl">{t("Просмотры за период", lang)}</span>
                <div className="m-kpi-val tnum">{totalViews.toLocaleString()}</div>
              </div>
              <TrendingUp size={24} color="var(--accent)" />
            </div>

            <div className="m-kpi-card">
              <div>
                <span className="m-kpi-lbl">{lang === "en" ? "Active Streamers" : "Каналов подключено"}</span>
                <div className="m-kpi-val tnum">{data.channels.length} / {currentPlan.maxChannels}</div>
              </div>
              <span className="chip good">{currentPlan.name}</span>
            </div>

            <div className="m-kpi-card">
              <div>
                <span className="m-kpi-lbl">{lang === "en" ? "Stream Processing Hours" : "Часов стримов обработано"}</span>
                <div className="m-kpi-val tnum">{data.subscription.streamsProcessedHours} ч</div>
              </div>
              <span className="chip acc">{lang === "en" ? "24/7 AI" : "ИИ-анализ"}</span>
            </div>
          </div>

          {/* Current Subscription Plan Card */}
          <div className="panel" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div>
              <div className="ph2" style={{ marginBottom: 8 }}>
                <h4 style={{ fontSize: 16, fontWeight: 700 }}>{currentPlan.name}</h4>
                <span className="chip good">{lang === "en" ? "Active" : "Активен"}</span>
              </div>
              <div style={{ fontSize: 26, fontWeight: 800, marginBottom: 6 }}>
                ${currentPlan.priceMonthly} <span style={{ fontSize: 14, fontWeight: 500, color: "var(--mute)" }}>/ {lang === "en" ? "mo" : "мес"}</span>
              </div>
              <div style={{ display: "grid", gap: 6, fontSize: 13, color: "var(--mute)" }}>
                <div>✓ {currentPlan.clipsPerDay} {lang === "en" ? "clips daily limit" : "клипов в день максимум"}</div>
                <div>✓ {currentPlan.quality}</div>
                <div>✓ {lang === "en" ? "Sync: TikTok, Shorts & Reels" : "Синхронно: TikTok, Shorts, Reels"}</div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button
                type="button"
                className="btn amber sm"
                style={{ flex: 1 }}
                onClick={() => onNavigateTab("subscription")}
              >
                <Sparkles size={14} />
                <span>{t("Управление подпиской", lang)}</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 28-Day Views Bar Chart */}
      <div className="m-card">
        <div className="ph2">
          <div>
            <h3>{t("Просмотры по дням", lang)}</h3>
            <span className="muted small">
              {lang === "en"
                ? "Total organic audience reach across all social channels (past 28 days)"
                : "Суммарный органический охват нарезками по всем соцсетям (последние 28 дней)"}
            </span>
          </div>
          <span className="chip acc" style={{ fontSize: 14 }}>
            {totalViews.toLocaleString()} views
          </span>
        </div>

        <div className="m-bars">
          {sortedDays.map((d, i) => {
            const v = historyDays[d] || 0;
            const hPercent = Math.max(8, Math.round((v / maxDayViews) * 100));
            const isRecent = i >= sortedDays.length - 7;
            return (
              <div
                key={d}
                className={`m-bar ${isRecent ? "active" : ""}`}
                style={{ height: `${hPercent}%` }}
                title={`${d}: ${v.toLocaleString()} views`}
              />
            );
          })}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--mute)", marginTop: 8 }}>
          <span className="mono">{sortedDays[0] || ""}</span>
          <span className="mono">{sortedDays[sortedDays.length - 1] || ""}</span>
        </div>
      </div>

      {/* Top 5 Clips Showcase */}
      <div className="panel">
        <div className="ph2">
          <h3>{t("Лучшие клипы", lang)}</h3>
          <button
            type="button"
            className="mini"
            onClick={() => onNavigateTab("clips")}
          >
            {lang === "en" ? "View all clips" : "Все клипы"} →
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 14 }}>
          {topClips.map((g, i) => (
            <div
              key={g.key}
              style={{
                borderRadius: 14,
                border: "1px solid var(--line)",
                background: "var(--panel-2)",
                padding: 12,
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                gap: 10,
              }}
            >
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div
                  style={{
                    width: 44,
                    height: 64,
                    borderRadius: 8,
                    background: "var(--panel)",
                    border: "1px solid var(--line)",
                    display: "grid",
                    placeItems: "center",
                    flexShrink: 0,
                    fontWeight: 800,
                    fontSize: 16,
                    color: "var(--accent)",
                  }}
                >
                  #{i + 1}
                </div>
                <div style={{ minWidth: 0 }}>
                  <b style={{ fontSize: 13.5, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {g.title}
                  </b>
                  <div style={{ fontSize: 12, color: "var(--mute)", marginTop: 2 }}>
                    <span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>
                      {g.bestViews.toLocaleString()}
                    </span>{" "}
                    views
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span className="plg" style={{ background: g.best.platform === "tiktok" ? "#0B0B0D" : g.best.platform === "youtube" ? "#FF0000" : "#E4405F" }}>
                  {g.best.platform.slice(0, 2).toUpperCase()}
                </span>
                {g.clip && onPlayClip && (
                  <button
                    type="button"
                    className="mini"
                    onClick={() => onPlayClip(g.clip!)}
                  >
                    <Play size={12} /> {lang === "en" ? "Watch" : "Смотреть"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
