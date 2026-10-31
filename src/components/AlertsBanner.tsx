import React from "react";
import { AppData } from "../types";
import { Language, t } from "../lib/i18n";
import { AlertTriangle, AlertCircle, Info } from "lucide-react";

interface AlertsBannerProps {
  data: AppData;
  lang: Language;
  onOpenSettings: () => void;
}

export const AlertsBanner: React.FC<AlertsBannerProps> = ({
  data,
  lang,
  onOpenSettings,
}) => {
  const alerts: Array<{ type: "bad" | "warn" | "info"; title: string; text: string; action?: () => void; actionText?: string }> = [];

  const L = data.status.live || {};
  if (L.is_live && L.vod_missing) {
    alerts.push({
      type: "bad",
      title: t("Стрим идёт, но Twitch не сохраняет запись.", lang),
      text: t("Стример должен включить «Сохранять прошлые трансляции» в настройках Twitch.", lang),
    });
  }

  const s = data.switches || {};
  const isStopped = s.process || s.post || s.stats;
  if (isStopped) {
    const parts = [
      s.process && (lang === "en" ? "clipping & analysis" : "нарезка и анализ"),
      s.post && (lang === "en" ? "publishing" : "публикация"),
      s.stats && (lang === "en" ? "stats" : "статистика"),
    ].filter(Boolean);

    alerts.push({
      type: "warn",
      title: t("Бот остановлен вручную:", lang),
      text: `${parts.join(", ")}. ${t("Включить — кнопка «Стоп» вверху.", lang)}`,
      action: onOpenSettings,
      actionText: t("Настройки", lang),
    });
  }

  // System errors
  for (const [comp, check] of Object.entries(data.status.system || {})) {
    if (check.level === "error") {
      alerts.push({
        type: "bad",
        title: `${lang === "en" ? "Error in" : "Сбой:"} ${comp}`,
        text: check.msg,
      });
    }
  }

  // Tokens auth alerts
  for (const [acc, token] of Object.entries(data.status.tokens || {})) {
    if (token.error && token.kind === "auth") {
      alerts.push({
        type: "bad",
        title: `${acc}: ${lang === "en" ? "Needs re-authentication" : "нужен повторный вход."}`,
        text: token.error,
      });
    }
  }

  return (
    <div className="alerts">
      <div className="demo-note">
        {t("Демо с выдуманными цифрами. На GitHub Pages будут только настоящие данные бота.", lang)}
      </div>

      {alerts.map((alert, i) => (
        <div key={i} className={`alert ${alert.type}`}>
          {alert.type === "bad" ? (
            <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          ) : alert.type === "warn" ? (
            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          ) : (
            <Info size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          )}
          <div style={{ flex: 1 }}>
            <b>{alert.title} </b>
            <span>{alert.text}</span>
            {alert.action && (
              <button
                type="button"
                className="mini acc"
                style={{ marginLeft: 8 }}
                onClick={alert.action}
              >
                {alert.actionText}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};
