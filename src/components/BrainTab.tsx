import React from "react";
import { AppData, Decision } from "../types";
import { Language, t } from "../lib/i18n";
import { Brain, RotateCcw, CheckCircle2, PauseCircle, Send } from "lucide-react";

interface BrainTabProps {
  data: AppData;
  lang: Language;
  onRevertDecision: (decision: Decision) => void;
}

export const BrainTab: React.FC<BrainTabProps> = ({
  data,
  lang,
  onRevertDecision,
}) => {
  const feedItems = data.status.brain?.feed || [];
  const decisions = data.decisions || [];

  return (
    <div style={{ display: "grid", gap: 18 }}>
      {/* Overview of Producer Rhythm */}
      <div className="panel">
        <div className="ph2">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Brain size={24} color="var(--accent)" />
            <div>
              <h3>{t("Как продюсер решает, что и когда выкладывать", lang)}</h3>
              <span className="muted small">
                {lang === "en"
                  ? "Rhythm over bursts: daily slots at peak hours, 2h minimum gap, best clips queued first, reserve never burns"
                  : "Ритм вместо всплесков: слоты в лучшие часы, пауза от 2 ч, лучшие клипы идут первыми"}
              </span>
            </div>
          </div>
          <span className="chip good">
            {lang === "en" ? "Producer Active" : "Продюсер активен"}
          </span>
        </div>

        {/* Live Decisions Feed */}
        <div style={{ display: "grid", gap: 14, marginTop: 16 }}>
          {feedItems.length === 0 ? (
            <p className="muted small">
              {lang === "en"
                ? "No producer decisions recorded yet. Decisions appear after the first hourly run."
                : "Решений ещё нет — появятся после первого прогона публикации."}
            </p>
          ) : (
            feedItems.map((item, idx) => {
              const isPost = item.action === "post";
              const isWait = item.action === "wait";

              return (
                <div
                  key={idx}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "70px 1fr",
                    gap: 14,
                    padding: "14px 0",
                    borderBottom: "1px solid var(--line)",
                    alignItems: "flex-start",
                  }}
                >
                  <time className="mono muted small" style={{ paddingTop: 2 }}>
                    {item.at.slice(11, 16)}
                  </time>

                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                      <span
                        className={`chip ${isPost ? "good" : isWait ? "warn" : "acc"}`}
                      >
                        {isPost ? (
                          <>
                            <Send size={12} /> {lang === "en" ? "Post" : "Публикация"}
                          </>
                        ) : isWait ? (
                          <>
                            <PauseCircle size={12} /> {lang === "en" ? "Wait" : "Ожидание"}
                          </>
                        ) : (
                          item.action
                        )}
                      </span>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>
                        {item.reason}
                      </span>
                      <span className="muted small mono">
                        by {item.by}
                      </span>
                    </div>

                    {/* Producer & Critic Thoughts */}
                    {item.thoughts && item.thoughts.length > 0 && (
                      <div
                        style={{
                          marginTop: 8,
                          padding: "8px 12px",
                          borderRadius: 10,
                          background: "var(--panel-2)",
                          fontSize: 13,
                          display: "grid",
                          gap: 4,
                        }}
                      >
                        {item.thoughts.map((th, tidx) => (
                          <div key={tidx} style={{ display: "flex", gap: 8 }}>
                            <b style={{ color: "var(--accent)" }}>{th.who}:</b>
                            <span>{th.reason}</span>
                            {th.agree && (
                              <CheckCircle2 size={14} color="var(--good)" style={{ marginLeft: "auto" }} />
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Policy Shifts & Reversible Actions */}
      <div className="panel">
        <div className="ph2">
          <h3>{lang === "en" ? "Behavior Changes & Experiments" : "Изменения поведения бота"}</h3>
          <span className="muted small">
            {lang === "en" ? "Self-tuning policy" : "Самообучающийся контур"}
          </span>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {decisions.map(d => (
            <div
              key={d.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "12px 14px",
                borderRadius: 12,
                background: "var(--panel-2)",
                border: "1px solid var(--line)",
                gap: 14,
                flexWrap: "wrap",
              }}
            >
              <div style={{ flex: 1, minWidth: 260 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <span className="chip acc">{d.kind}</span>
                  <span className="muted small mono">{d.at.slice(0, 10)}</span>
                </div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{d.summary}</div>
              </div>

              {d.reversible && (
                <button
                  type="button"
                  className="iconbtn"
                  onClick={() => onRevertDecision(d)}
                  title="Revert to previous policy and lock for 14 days"
                >
                  <RotateCcw size={14} />
                  <span>{t("Откатить", lang)}</span>
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
