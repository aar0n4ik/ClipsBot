import React, { useState } from "react";
import { AppData, GroupedClip } from "../types";
import { Language, t } from "../lib/i18n";
import { Eye, TrendingUp, Sparkles, BarChart2 } from "lucide-react";

interface AnalyticsTabProps {
  data: AppData;
  grouped: Record<string, GroupedClip>;
  lang: Language;
}

export const AnalyticsTab: React.FC<AnalyticsTabProps> = ({
  data,
  grouped,
  lang,
}) => {
  const [selectedPeriod, setSelectedPeriod] = useState<string>("7");
  const [platformFilter, setPlatformFilter] = useState<string>("");
  const [sortKey, setSortKey] = useState<"date" | "pviews" | "best">("best");

  // Filter groups
  let items = Object.values(grouped);
  if (platformFilter) {
    items = items.filter(g => g.posts.some(p => p.platform === platformFilter));
  }

  // Sort items
  items.sort((a, b) => {
    if (sortKey === "best") return b.bestViews - a.bestViews;
    if (sortKey === "date") return b.created - a.created;
    return b.bestViews - a.bestViews;
  });

  // Calculate Categories Stats
  const catStats: Record<string, { count: number; totalViews: number }> = {};
  items.forEach(g => {
    const cat = g.clip?.category || "other";
    if (!catStats[cat]) catStats[cat] = { count: 0, totalViews: 0 };
    catStats[cat].count += 1;
    catStats[cat].totalViews += g.bestViews;
  });

  const catList = Object.entries(catStats)
    .map(([cat, s]) => ({
      cat,
      avg: Math.round(s.totalViews / Math.max(1, s.count)),
      count: s.count,
    }))
    .sort((a, b) => b.avg - a.avg);

  const maxCatAvg = Math.max(...catList.map(c => c.avg), 1);

  // Score Calibration (Score 7, 8, 9 vs Avg Views)
  const scoreStats: Record<number, { count: number; totalViews: number }> = {
    7: { count: 0, totalViews: 0 },
    8: { count: 0, totalViews: 0 },
    9: { count: 0, totalViews: 0 },
  };
  items.forEach(g => {
    const score = g.clip?.score || 7;
    const rounded = Math.min(9, Math.max(7, Math.round(score)));
    if (scoreStats[rounded]) {
      scoreStats[rounded].count += 1;
      scoreStats[rounded].totalViews += g.bestViews;
    }
  });

  // Hook Style Performance from policy evidence
  const hookStyles = [
    { style: "number", label: lang === "en" ? "Number hook" : "Цифра в хуке", boost: "+35%", share: 46 },
    { style: "conflict", label: lang === "en" ? "Conflict / Stakes" : "Конфликт", boost: "+4%", share: 22 },
    { style: "tease", label: lang === "en" ? "Tease / Question" : "Недосказанность", boost: "-5%", share: 18 },
    { style: "quote", label: lang === "en" ? "Quote" : "Цитата", boost: "-10%", share: 14 },
  ];

  // Best 24h posting hours
  const hoursData = data.policy?.hours?.youtube || [
    0.2, 0.12, 0.06, 0.04, 0.04, 0.07, 0.18, 0.4, 0.55, 0.5, 0.48, 0.52,
    0.66, 0.7, 0.62, 0.58, 0.63, 0.78, 0.92, 1, 0.97, 0.9, 0.74, 0.44,
  ];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Controls Bar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
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

        <select
          className="sel"
          value={platformFilter}
          onChange={e => setPlatformFilter(e.target.value)}
        >
          <option value="">{t("Все площадки", lang)}</option>
          <option value="tiktok">TikTok</option>
          <option value="youtube">YouTube Shorts</option>
          <option value="instagram">Instagram Reels</option>
        </select>
      </div>

      {/* Top 2 Insights: Calibration & Categories */}
      <div className="grid2">
        <div className="panel">
          <div className="ph2">
            <h3>{t("Оценка ИИ против реальных просмотров", lang)}</h3>
          </div>
          <p className="muted small" style={{ marginBottom: 16 }}>
            {lang === "en"
              ? "Correlation between AI Director rating and real viewer retention/reach"
              : "Связь между оценкой ИИ-режиссёра и реальными просмотрами"}
          </p>

          <div style={{ display: "grid", gap: 12 }}>
            {[7, 8, 9].map(sc => {
              const st = scoreStats[sc];
              const avg = st.count ? Math.round(st.totalViews / st.count) : 0;
              const maxScoreAvg = Math.max(scoreStats[9].count ? scoreStats[9].totalViews / scoreStats[9].count : 1, 1000);
              const barWidth = Math.max(12, Math.round((avg / maxScoreAvg) * 100));

              return (
                <div key={sc}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 4 }}>
                    <span style={{ fontWeight: 700 }}>
                      {sc}/10 {sc === 9 ? (lang === "en" ? "(Viral Hit)" : "(Хит)") : sc === 8 ? (lang === "en" ? "(Strong)" : "(Сильный)") : (lang === "en" ? "(Standard)" : "(Норма)")}
                    </span>
                    <span className="mono">
                      <b>{avg.toLocaleString()}</b> {lang === "en" ? "views avg" : "просмотров в ср."} ({st.count} {lang === "en" ? "clips" : "кл."})
                    </span>
                  </div>
                  <div className="meter">
                    <i style={{ width: `${barWidth}%`, background: sc === 9 ? "#2F6BFF" : sc === 8 ? "#4C8DFF" : "#94A3B8" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="panel">
          <div className="ph2">
            <h3>{t("Темы", lang)}</h3>
          </div>
          <p className="muted small" style={{ marginBottom: 16 }}>
            {lang === "en"
              ? "Average best clip result per category. AI automatically prioritizes winning topics."
              : "Средний лучший результат по темам. Бот сам поднимает в очереди темы, которые заходят."}
          </p>

          <div style={{ display: "grid", gap: 10 }}>
            {catList.map(c => {
              const width = Math.max(10, Math.round((c.avg / maxCatAvg) * 100));
              return (
                <div key={c.cat}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 3 }}>
                    <span style={{ fontWeight: 600 }}>{c.cat}</span>
                    <span className="mono">{c.avg.toLocaleString()} {lang === "en" ? "views" : "просмотров"} ({c.count})</span>
                  </div>
                  <div className="meter">
                    <i style={{ width: `${width}%`, background: "var(--accent)" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Hook Style and Best Hours */}
      <div className="grid2">
        <div className="panel">
          <div className="ph2">
            <h3>{lang === "en" ? "Hook Style Performance" : "Стиль заголовка"}</h3>
          </div>
          <p className="muted small" style={{ marginBottom: 14 }}>
            {lang === "en"
              ? "Share of generated clips and view impact relative to channel baseline"
              : "Доля клипов с вариантом и эффект к обычным просмотрам"}
          </p>

          <div style={{ display: "grid", gap: 12 }}>
            {hookStyles.map(h => (
              <div key={h.style}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 4 }}>
                  <span style={{ fontWeight: 600 }}>{h.label}</span>
                  <span className="mono" style={{ color: h.boost.startsWith("+") ? "var(--good)" : "var(--warn)", fontWeight: 700 }}>
                    {h.boost} ({h.share}%)
                  </span>
                </div>
                <div className="meter">
                  <i style={{ width: `${h.share * 1.8}%`, background: h.boost.startsWith("+") ? "var(--accent)" : "var(--mute)" }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="ph2">
            <h3>{lang === "en" ? "Audience Activity by Hour" : "Лучшие часы аудитории"}</h3>
          </div>
          <p className="muted small" style={{ marginBottom: 14 }}>
            {lang === "en"
              ? "Daily schedule builds posting slots around peak viewer hours (2h minimum gap)"
              : "Слоты публикаций строятся вокруг пиковых часов (пауза минимум 2-3 часа)"}
          </p>

          <div style={{ display: "flex", alignItems: "flex-end", height: 90, gap: 2, paddingTop: 10 }}>
            {hoursData.map((val, h) => {
              const isPeak = val >= 0.85;
              return (
                <div
                  key={h}
                  style={{
                    flex: 1,
                    height: `${Math.round(val * 100)}%`,
                    background: isPeak ? "var(--accent)" : "var(--bar-dim)",
                    borderRadius: "2px 2px 0 0",
                  }}
                  title={`${h}:00 - ${Math.round(val * 100)}% reach`}
                />
              );
            })}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--mute)", marginTop: 6 }} className="mono">
            <span>00:00</span>
            <span>06:00</span>
            <span>12:00</span>
            <span>18:00 (Peak)</span>
            <span>23:00</span>
          </div>
        </div>
      </div>

      {/* Comprehensive Clips & Reach Table (Removed cost/earnings) */}
      <div className="panel">
        <div className="ph2">
          <h3>{t("Клипы и охват", lang)}</h3>
          <span className="muted small">
            {items.length} {lang === "en" ? "published clips" : "клипов"}
          </span>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("Клип", lang)}</th>
                <th>{t("Где опубликован (просмотры)", lang)}</th>
                <th>
                  <button type="button" onClick={() => setSortKey("date")} style={{ background: "none", border: 0, fontWeight: 700 }}>
                    {t("Дата", lang)} {sortKey === "date" ? "↓" : ""}
                  </button>
                </th>
                <th className="r">
                  <button type="button" onClick={() => setSortKey("best")} style={{ background: "none", border: 0, fontWeight: 700 }}>
                    {t("Охват", lang)} {sortKey === "best" ? "↓" : ""}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map(g => (
                <tr key={g.key}>
                  <td>
                    <b style={{ display: "block", fontSize: 14 }}>{g.title}</b>
                    {g.clip?.category && (
                      <span className="muted small">#{g.clip.category}</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {g.posts.map(p => (
                        <span key={p.id} className="mini">
                          <span
                            className="plg"
                            style={{
                              width: 14,
                              height: 14,
                              background: p.platform === "tiktok" ? "#000" : p.platform === "youtube" ? "#FF0000" : "#E4405F",
                              fontSize: 8,
                            }}
                          >
                            {p.platform.slice(0, 2).toUpperCase()}
                          </span>
                          <span className="mono">{p.views.toLocaleString()}</span>
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="muted small mono">
                    {new Date(g.created * 1000).toLocaleDateString(lang === "en" ? "en-US" : "ru-RU", { month: "short", day: "numeric" })}
                  </td>
                  <td className="r mono font-bold" style={{ color: "var(--accent)" }}>
                    {g.bestViews.toLocaleString()}
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
