import React from "react";
import { Language, t } from "../lib/i18n";
import { AppData } from "../types";

export type TabKey = "overview" | "clips" | "stats" | "brain" | "subscription" | "channels" | "settings" | "help";

interface TabsNavProps {
  activeTab: TabKey;
  onSelectTab: (tab: TabKey) => void;
  lang: Language;
  data: AppData;
}

export const TabsNav: React.FC<TabsNavProps> = ({
  activeTab,
  onSelectTab,
  lang,
  data,
}) => {
  const readyClipsCount = data.clips.filter(c => c.status === "ready").length;
  const draftsCount = data.clips.filter(c =>
    Object.values(c.posts || {}).some(p => p.status === "inbox")
  ).length;
  const clipsBadge = readyClipsCount + draftsCount;

  const tabs: Array<{ key: TabKey; label: string; badge?: number }> = [
    { key: "overview", label: t("Обзор", lang) },
    { key: "clips", label: t("Клипы", lang), badge: clipsBadge },
    { key: "stats", label: t("Аналитика", lang) },
    { key: "brain", label: t("Решения", lang) },
    { key: "subscription", label: t("Подписка", lang) },
    { key: "channels", label: t("Каналы", lang) },
    { key: "settings", label: t("Настройки", lang) },
    { key: "help", label: t("Помощь", lang) },
  ];

  return (
    <nav className="tabs" role="tablist">
      {tabs.map(tab => {
        const isActive = activeTab === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`tab ${isActive ? "on" : ""}`}
            onClick={() => onSelectTab(tab.key)}
          >
            <span>{tab.label}</span>
            {tab.badge !== undefined && tab.badge > 0 && (
              <span className="badge">{tab.badge}</span>
            )}
          </button>
        );
      })}
    </nav>
  );
};
