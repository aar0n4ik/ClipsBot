import React, { useState } from "react";
import { AppData, Clip } from "../types";
import { Language, t } from "../lib/i18n";
import { Play, Copy, Check, Send, XCircle, RefreshCw, AlertCircle } from "lucide-react";

interface ClipsTabProps {
  data: AppData;
  lang: Language;
  onPostNow: (clip: Clip) => void;
  onCancelClip: (clip: Clip) => void;
  onRetryClip: (clip: Clip) => void;
  onPlayClip: (clip: Clip) => void;
  onCopyText: (text: string) => void;
}

type ClipSegment = "ready" | "drafts" | "out" | "problems" | "rejected";

export const ClipsTab: React.FC<ClipsTabProps> = ({
  data,
  lang,
  onPostNow,
  onCancelClip,
  onRetryClip,
  onPlayClip,
  onCopyText,
}) => {
  const [activeSeg, setActiveSeg] = useState<ClipSegment>("ready");
  const [expandedClipId, setExpandedClipId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleCopyComment = (clipId: string, text: string) => {
    onCopyText(text);
    setCopiedId(clipId);
    setTimeout(() => setCopiedId(null), 1500);
  };

  // Filter clips based on segment
  const filteredClips = data.clips.filter(c => {
    if (activeSeg === "ready") {
      return c.status === "ready";
    }
    if (activeSeg === "drafts") {
      return Object.values(c.posts || {}).some(p => p.status === "inbox");
    }
    if (activeSeg === "out") {
      return c.status === "posted" || c.status === "used";
    }
    if (activeSeg === "problems") {
      return (
        c.status === "failed" ||
        c.status === "retry" ||
        Object.values(c.posts || {}).some(p => p.status === "failed" || p.status === "retry")
      );
    }
    return false;
  });

  const rejectedMoments = data.status.funnel?.rejected || [];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Segment switcher */}
      <div className="seg">
        <button
          type="button"
          className={activeSeg === "ready" ? "on" : ""}
          onClick={() => setActiveSeg("ready")}
        >
          {t("Ожидают публикации", lang)} ({data.clips.filter(c => c.status === "ready").length})
        </button>
        <button
          type="button"
          className={activeSeg === "drafts" ? "on" : ""}
          onClick={() => setActiveSeg("drafts")}
        >
          {t("Черновики TikTok", lang)} ({data.clips.filter(c => Object.values(c.posts || {}).some(p => p.status === "inbox")).length})
        </button>
        <button
          type="button"
          className={activeSeg === "out" ? "on" : ""}
          onClick={() => setActiveSeg("out")}
        >
          {t("Опубликованные", lang)}
        </button>
        <button
          type="button"
          className={activeSeg === "problems" ? "on" : ""}
          onClick={() => setActiveSeg("problems")}
        >
          {t("Ошибки", lang)}
        </button>
        <button
          type="button"
          className={activeSeg === "rejected" ? "on" : ""}
          onClick={() => setActiveSeg("rejected")}
        >
          {t("Отклонённые", lang)} ({rejectedMoments.length})
        </button>
      </div>

      {activeSeg === "drafts" && (
        <div className="alert info">
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          <div>
            <b>{t("TikTok пока без аудита API", lang)}</b> —{" "}
            {lang === "en"
              ? "The bot sends drafts to your TikTok inbox. Open TikTok → Profile → Drafts and tap 'Post' to synchronize release with Shorts and Reels."
              : "бот кладёт ролик в черновики TikTok в ту же минуту, что и на Shorts и Reels. Открой TikTok → Профиль → Черновики (Входящие) и нажми «Опубликовать», чтобы вышло одновременно."}
          </div>
        </div>
      )}

      {/* Normal Clips Cards */}
      {activeSeg !== "rejected" ? (
        <div className="clips">
          {filteredClips.length === 0 ? (
            <div className="panel" style={{ gridColumn: "1 / -1", textAlign: "center", padding: "40px 20px" }}>
              <p className="muted">
                {lang === "en" ? "No clips in this section right now." : "В этом разделе пока нет клипов."}
              </p>
            </div>
          ) : (
            filteredClips.map(clip => {
              const isExpanded = expandedClipId === clip.id;
              const hasDraft = Object.values(clip.posts || {}).some(p => p.status === "inbox");

              return (
                <div key={clip.id} className="clip">
                  {/* Poster Thumbnail */}
                  <div className="clip-poster" onClick={() => onPlayClip(clip)} style={{ cursor: "pointer" }}>
                    <div style={{ textAlign: "center", padding: 8 }}>
                      <Play size={24} color="var(--accent)" />
                    </div>
                    <span className="clip-score">{clip.score}/10</span>
                    <span className="clip-dur">{clip.duration}s</span>
                  </div>

                  {/* Info and Actions */}
                  <div className="clip-info">
                    <div>
                      <div className="clip-hook">{clip.overlay}</div>
                      <div className="clip-what">{clip.what || clip.why}</div>

                      {/* Platforms links or draft badges */}
                      <div className="clip-plats">
                        {["tiktok", "youtube", "instagram"].map(plat => {
                          const pInfo = (clip.posts || {})[plat];
                          const pTarget = (clip.targets || {})[plat];
                          const isInbox = pInfo?.status === "inbox";
                          const isPosted = pInfo?.status === "posted" || pInfo?.status === "used";

                          return (
                            <span
                              key={plat}
                              className={`mini ${isInbox ? "acc" : ""}`}
                              style={{
                                background: isPosted ? "var(--good-soft)" : undefined,
                                color: isPosted ? "var(--good)" : undefined,
                                borderColor: isPosted ? "var(--good-line)" : undefined,
                              }}
                            >
                              <span
                                className="plg"
                                style={{
                                  width: 16,
                                  height: 16,
                                  background: plat === "tiktok" ? "#000" : plat === "youtube" ? "#FF0000" : "#E4405F",
                                  fontSize: 9,
                                }}
                              >
                                {plat.slice(0, 2).toUpperCase()}
                              </span>
                              <span>{isInbox ? "Draft" : isPosted ? (lang === "en" ? "Posted" : "Выложен") : pTarget?.status || "Ready"}</span>
                            </span>
                          );
                        })}
                      </div>

                      {/* First comment copy */}
                      {clip.first_comment && (
                        <div
                          style={{
                            marginTop: 10,
                            padding: "6px 10px",
                            borderRadius: 8,
                            background: "var(--panel-2)",
                            border: "1px solid var(--line)",
                            fontSize: 12.5,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 8,
                          }}
                        >
                          <span style={{ color: "var(--mute)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {t("Первый коммент", lang)}: {clip.first_comment}
                          </span>
                          <button
                            type="button"
                            className="mini"
                            style={{ padding: "2px 8px", fontSize: 11 }}
                            onClick={() => handleCopyComment(clip.id, clip.first_comment || "")}
                          >
                            {copiedId === clip.id ? <Check size={12} color="var(--good)" /> : <Copy size={12} />}
                            {copiedId === clip.id ? t("Скопировано", lang) : t("Скопировать", lang)}
                          </button>
                        </div>
                      )}

                      {/* Expandable details */}
                      {isExpanded && (
                        <div
                          style={{
                            marginTop: 10,
                            padding: 10,
                            borderRadius: 10,
                            background: "var(--panel-2)",
                            border: "1px solid var(--line)",
                            fontSize: 12.5,
                            display: "grid",
                            gap: 6,
                          }}
                        >
                          <div>
                            <b>{t("Почему взят", lang)}:</b> {clip.why || clip.what}
                          </div>
                          {clip.brain?.trimmed_s && (
                            <div>
                              <b>{lang === "en" ? "Silence trimmed" : "Вырезано пауз"}:</b> {clip.brain.trimmed_s}s ({clip.brain.cuts || 2} cuts)
                            </div>
                          )}
                          <div>
                            <b>{lang === "en" ? "Category" : "Категория"}:</b> {clip.category}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Action buttons */}
                    <div className="clip-actions">
                      <button
                        type="button"
                        className="mini"
                        onClick={() => setExpandedClipId(isExpanded ? null : clip.id)}
                      >
                        {isExpanded ? (lang === "en" ? "Hide" : "Скрыть") : t("Подробнее", lang)}
                      </button>

                      {clip.status === "ready" && (
                        <>
                          <button
                            type="button"
                            className="mini acc"
                            onClick={() => onPostNow(clip)}
                            title="Post immediately without waiting for schedule slot"
                          >
                            <Send size={12} /> {t("Опубликовать сейчас", lang)}
                          </button>
                          <button
                            type="button"
                            className="mini"
                            onClick={() => onCancelClip(clip)}
                            title="Cancel publishing"
                          >
                            <XCircle size={12} /> {t("Отменить", lang)}
                          </button>
                        </>
                      )}

                      {(clip.status === "failed" || clip.status === "retry") && (
                        <button
                          type="button"
                          className="mini acc"
                          onClick={() => onRetryClip(clip)}
                        >
                          <RefreshCw size={12} /> {t("Повторить", lang)}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      ) : (
        /* Rejected moments table */
        <div className="panel">
          <div className="ph2">
            <h3>{t("Почему моменты не стали клипами", lang)}</h3>
            <span className="muted small">
              {lang === "en"
                ? "Scouted moments rejected after AI screening or video quality review"
                : "Отклонённые кандидаты после проверки текста или видео"}
            </span>
          </div>

          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("Когда", lang)}</th>
                  <th>{t("Место в стриме", lang)}</th>
                  <th>{t("Этап", lang)}</th>
                  <th className="r">{t("Оценка", lang)}</th>
                  <th>{t("Причина", lang)}</th>
                </tr>
              </thead>
              <tbody>
                {rejectedMoments.map((item, idx) => (
                  <tr key={idx}>
                    <td className="muted small">{item.at ? item.at.slice(11, 16) : "--:--"}</td>
                    <td className="mono font-semibold">
                      {Math.floor(item.t / 3600)}:{String(Math.floor((item.t % 3600) / 60)).padStart(2, "0")}:{String(item.t % 60).padStart(2, "0")}
                    </td>
                    <td>
                      <span className="chip">{item.stage}</span>
                    </td>
                    <td className="r mono font-bold">
                      <span className={item.score && item.score >= 7 ? "chip good" : "chip"}>
                        {item.score || "—"}/10
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 500 }}>{item.reason}</div>
                      {item.what && <div className="muted small">{item.what}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
