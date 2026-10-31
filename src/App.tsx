import React, { useState, useEffect } from "react";
import { AppData, Clip, Decision, SubscriptionPlan, StreamerChannel, GroupedClip } from "./types";
import { createDemoData } from "./lib/demoData";
import { Language, getLang, setLang, t } from "./lib/i18n";
import { groups } from "./lib/money";
import { Header } from "./components/Header";
import { TabsNav, TabKey } from "./components/TabsNav";
import { AlertsBanner } from "./components/AlertsBanner";
import { OverviewTab } from "./components/OverviewTab";
import { ClipsTab } from "./components/ClipsTab";
import { AnalyticsTab } from "./components/AnalyticsTab";
import { BrainTab } from "./components/BrainTab";
import { SubscriptionTab } from "./components/SubscriptionTab";
import { ChannelsTab } from "./components/ChannelsTab";
import { SettingsTab } from "./components/SettingsTab";
import { HelpTab } from "./components/HelpTab";
import { ConfirmModal, UpgradePlanModal, AddChannelModal, VideoModal } from "./components/Modals";

export const App: React.FC = () => {
  // Theme state
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem("clips:theme") || "dark";
    } catch {
      return "dark";
    }
  });

  // Language state
  const [lang, setLangState] = useState<Language>(getLang());

  // Navigation tab state
  const [activeTab, setActiveTab] = useState<TabKey>(() => {
    const hash = window.location.hash.slice(1) as TabKey;
    const validTabs: TabKey[] = ["overview", "clips", "stats", "brain", "subscription", "channels", "settings", "help"];
    return validTabs.includes(hash) ? hash : "overview";
  });

  // Data state
  const [data, setData] = useState<AppData>(() => createDemoData());

  // Active channel
  const activeChannel = data.channels.find(c => c.id === data.activeChannelId) || data.channels[0];

  // Toast notification
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3000);
  };

  // Modals state
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    body: string;
    yesText?: string;
    danger?: boolean;
    requiredWord?: string | null;
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: "",
    body: "",
    onConfirm: () => {},
  });

  const [upgradeModal, setUpgradeModal] = useState<boolean>(false);
  const [addChannelModal, setAddChannelModal] = useState<boolean>(false);
  const [videoModal, setVideoModal] = useState<{
    isOpen: boolean;
    clip: Clip | null;
  }>({
    isOpen: false,
    clip: null,
  });

  // Sync hash routing
  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash.slice(1) as TabKey;
      const validTabs: TabKey[] = ["overview", "clips", "stats", "brain", "subscription", "channels", "settings"];
      if (validTabs.includes(hash)) {
        setActiveTab(hash);
      }
    };
    window.addEventListener("hashchange", handleHash);
    return () => window.removeEventListener("hashchange", handleHash);
  }, []);

  const handleSelectTab = (tab: TabKey) => {
    setActiveTab(tab);
    window.location.hash = `#${tab}`;
  };

  const handleLangChange = (l: Language) => {
    setLang(l);
    setLangState(l);
  };

  const handleToggleTheme = () => {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    try {
      localStorage.setItem("clips:theme", nextTheme);
    } catch {}
  };

  const handleThemeChange = (tVal: string) => {
    setTheme(tVal);
    try {
      localStorage.setItem("clips:theme", tVal);
    } catch {}
  };

  // Channel switching
  const handleSelectChannel = (channelId: string) => {
    setData(prev => ({
      ...prev,
      activeChannelId: channelId,
    }));
    const target = data.channels.find(c => c.id === channelId);
    if (target) {
      showToast(lang === "en" ? `Switched to ${target.displayName}` : `Канал переключен на ${target.displayName}`);
    }
  };

  // Add new streamer channel
  const handleAddChannel = (
    login: string,
    displayName: string,
    platforms: { tiktok: boolean; youtube: boolean; instagram: boolean }
  ) => {
    const newChan: StreamerChannel = {
      id: `ch_${login}_${Date.now().toString(36)}`,
      twitchLogin: login,
      displayName,
      status: "live",
      viewers: 950,
      currentStreamTitle: "Трансляция Twitch / Новые нарезки",
      clipsCount: 0,
      platforms,
    };

    setData(prev => ({
      ...prev,
      channels: [...prev.channels, newChan],
      activeChannelId: newChan.id,
    }));
    showToast(lang === "en" ? `Channel ${displayName} connected successfully!` : `Канал ${displayName} успешно подключен!`);
  };

  // Remove channel
  const handleRemoveChannel = (channel: StreamerChannel) => {
    setConfirmModal({
      isOpen: true,
      title: lang === "en" ? "Remove Streamer Channel?" : "Удалить канал стримера?",
      body: lang === "en"
        ? `Are you sure you want to disconnect ${channel.displayName} (twitch.tv/${channel.twitchLogin}) from auto-clipping?`
        : `Отключить стримера ${channel.displayName} (twitch.tv/${channel.twitchLogin}) от автонарезки?`,
      yesText: lang === "en" ? "Remove" : "Удалить",
      danger: true,
      onConfirm: () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        setData(prev => {
          const remaining = prev.channels.filter(c => c.id !== channel.id);
          return {
            ...prev,
            channels: remaining,
            activeChannelId: remaining[0]?.id || "",
          };
        });
        showToast(lang === "en" ? "Channel removed." : "Канал удалён.");
      },
    });
  };

  // Subscription plan change
  const handleSelectPlan = (plan: SubscriptionPlan, cycle: "monthly" | "annual") => {
    setData(prev => ({
      ...prev,
      subscription: {
        ...prev.subscription,
        planId: plan.id,
        billingCycle: cycle,
        clipsQuotaThisMonth: plan.maxClipsPerMonth,
      },
      invoices: [
        {
          id: `inv_${Date.now().toString(36)}`,
          date: new Date().toISOString().slice(0, 10),
          planName: `${plan.name} (${cycle === "annual" ? "Annual" : "Monthly"})`,
          amount: cycle === "annual" ? plan.priceAnnual : plan.priceMonthly,
          status: "paid",
        },
        ...prev.invoices,
      ],
    }));
    showToast(lang === "en" ? `Upgraded to ${plan.name} plan!` : `Тариф изменён на ${plan.name}!`);
  };

  // Grouped clips calculation for views & reach
  const grouped = groups(data.posts, data.clips);

  // Clip Actions
  const handlePostNow = (clip: Clip) => {
    setConfirmModal({
      isOpen: true,
      title: t("Опубликовать сейчас?", lang),
      body: `${lang === "en" ? "Post immediately to TikTok, Shorts, and Reels:" : "Выложить на все готовые площадки при ближайшем запуске:"} «${clip.overlay}» (${clip.score}/10).`,
      yesText: t("Опубликовать", lang),
      onConfirm: () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        setData(prev => ({
          ...prev,
          clips: prev.clips.map(c =>
            c.id === clip.id
              ? {
                  ...c,
                  status: "posted",
                  posts: {
                    tiktok: { status: "inbox", posted_at: new Date().toISOString() },
                    youtube: { status: "posted", posted_at: new Date().toISOString() },
                    instagram: { status: "posted", posted_at: new Date().toISOString() },
                  },
                }
              : c
          ),
          subscription: {
            ...prev.subscription,
            clipsUsedThisMonth: prev.subscription.clipsUsedThisMonth + 1,
          },
        }));
        showToast(lang === "en" ? "Publishing started — clip is shipping!" : "Публикация запущена — клип уходит на площадки!");
      },
    });
  };

  const handleCancelClip = (clip: Clip) => {
    setConfirmModal({
      isOpen: true,
      title: t("Не выкладывать клип?", lang),
      body: `${lang === "en" ? "Discard and remove from release queue:" : "Отменить публикацию клипа:"} «${clip.overlay}».`,
      yesText: t("Не выкладывать", lang),
      danger: true,
      onConfirm: () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        setData(prev => ({
          ...prev,
          clips: prev.clips.filter(c => c.id !== clip.id),
        }));
        showToast(lang === "en" ? "Clip canceled and removed." : "Клип отменён.");
      },
    });
  };

  const handleRetryClip = (clip: Clip) => {
    setData(prev => ({
      ...prev,
      clips: prev.clips.map(c =>
        c.id === clip.id
          ? {
              ...c,
              status: "ready",
            }
          : c
      ),
    }));
    showToast(lang === "en" ? "Retrying upload..." : "Повторная загрузка клипа...");
  };

  const handleRevertDecision = (decision: Decision) => {
    setConfirmModal({
      isOpen: true,
      title: t("Откатить решение?", lang),
      body: `${decision.summary}. ${lang === "en" ? "Revert to previous policy and lock for 14 days?" : "Вернуть как было и закрепить на 14 дней?"}`,
      yesText: t("Откатить", lang),
      onConfirm: () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        setData(prev => ({
          ...prev,
          decisions: (prev.decisions || []).filter(d => d.id !== decision.id),
        }));
        showToast(lang === "en" ? "Decision rolled back successfully." : "Решение успешно откачено.");
      },
    });
  };

  const handleToggleStopBot = (mode: "all" | "post" | "process" | "resume", reason?: string) => {
    if (mode === "resume") {
      setData(prev => ({
        ...prev,
        switches: { process: false, post: false, stats: false },
      }));
      showToast(lang === "en" ? "Bot resumed!" : "Бот снова запущен!");
      return;
    }

    setConfirmModal({
      isOpen: true,
      title: t("Остановить бота?", lang),
      body: `${lang === "en" ? "Stop mode" : "Режим остановки"}: ${mode}. ${lang === "en" ? "Current clipping will pause." : "Идущая сейчас нарезка будет приостановлена."}`,
      yesText: t("Остановить", lang),
      danger: true,
      requiredWord: "СТОП",
      onConfirm: () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        setData(prev => ({
          ...prev,
          switches: {
            process: mode !== "post",
            post: mode !== "process",
            stats: mode === "all",
            at: new Date().toISOString(),
            note: reason,
          },
        }));
        showToast(lang === "en" ? "Bot stopped." : "Бот остановлен.");
      },
    });
  };

  return (
    <div id="app" className={`app ${theme === "dark" ? "dk" : ""}`}>
      <div className="wrap shell">
        {/* Header */}
        <Header
          data={data}
          activeChannel={activeChannel}
          channels={data.channels}
          onSelectChannel={handleSelectChannel}
          lang={lang}
          onLangChange={handleLangChange}
          theme={theme}
          onToggleTheme={handleToggleTheme}
          onOpenSubscription={() => handleSelectTab("subscription")}
        />

        {/* Navigation Tabs */}
        <TabsNav
          activeTab={activeTab}
          onSelectTab={handleSelectTab}
          lang={lang}
          data={data}
        />

        {/* Alerts & Notices */}
        <AlertsBanner
          data={data}
          lang={lang}
          onOpenSettings={() => handleSelectTab("settings")}
        />

        {/* Main Content Pages */}
        <main className="page" style={{ padding: 0 }}>
          {activeTab === "overview" && (
            <OverviewTab
              data={data}
              activeChannel={activeChannel}
              grouped={grouped}
              lang={lang}
              onNavigateTab={handleSelectTab}
              onPlayClip={clip => setVideoModal({ isOpen: true, clip })}
              onOpenUpgradeModal={() => setUpgradeModal(true)}
            />
          )}

          {activeTab === "clips" && (
            <ClipsTab
              data={data}
              lang={lang}
              onPostNow={handlePostNow}
              onCancelClip={handleCancelClip}
              onRetryClip={handleRetryClip}
              onPlayClip={clip => setVideoModal({ isOpen: true, clip })}
              onCopyText={showToast}
            />
          )}

          {activeTab === "stats" && (
            <AnalyticsTab
              data={data}
              grouped={grouped}
              lang={lang}
            />
          )}

          {activeTab === "brain" && (
            <BrainTab
              data={data}
              lang={lang}
              onRevertDecision={handleRevertDecision}
            />
          )}

          {activeTab === "subscription" && (
            <SubscriptionTab
              data={data}
              lang={lang}
              onSelectPlan={handleSelectPlan}
              onCancelSubscription={() => {
                showToast(lang === "en" ? "Subscription auto-renewal canceled." : "Автопродление отключено.");
              }}
              onDownloadInvoice={invId => {
                showToast(lang === "en" ? `Invoice ${invId} downloaded.` : `Квитанция ${invId} скачана.`);
              }}
            />
          )}

          {activeTab === "channels" && (
            <ChannelsTab
              data={data}
              activeChannel={activeChannel}
              lang={lang}
              onSelectChannel={handleSelectChannel}
              onOpenAddChannelModal={() => setAddChannelModal(true)}
              onRemoveChannel={handleRemoveChannel}
            />
          )}

          {activeTab === "help" && (
            <HelpTab
              lang={lang}
              onApplySettingsDiff={(k, v) => {
                setData(prev => ({
                  ...prev,
                  settings: {
                    ...prev.settings,
                    values: { ...prev.settings.values, [k]: v },
                  },
                }));
              }}
            />
          )}

          {activeTab === "settings" && (
            <SettingsTab
              data={data}
              lang={lang}
              onLangChange={handleLangChange}
              theme={theme}
              onThemeChange={handleThemeChange}
              onSaveSettings={vals => {
                setData(prev => ({
                  ...prev,
                  settings: { ...prev.settings, values: { ...prev.settings.values, ...vals } },
                }));
                showToast(lang === "en" ? "Settings saved!" : "Настройки сохранены!");
              }}
              onSaveToken={_tok => showToast(lang === "en" ? "Token saved!" : "Ключ сохранён!")}
              onToggleStopBot={handleToggleStopBot}
              onForgetDevice={() => {
                try {
                  localStorage.clear();
                } catch {}
                showToast(lang === "en" ? "Credentials forgotten." : "Данные очищены.");
              }}
            />
          )}
        </main>
      </div>

      {/* Modals */}
      <ConfirmModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        body={confirmModal.body}
        yesText={confirmModal.yesText}
        danger={confirmModal.danger}
        requiredWord={confirmModal.requiredWord}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal(prev => ({ ...prev, isOpen: false }))}
        lang={lang}
      />

      <UpgradePlanModal
        isOpen={upgradeModal}
        plans={data.plans}
        currentPlanId={data.subscription.planId}
        billingCycle={data.subscription.billingCycle}
        lang={lang}
        onSelectPlan={handleSelectPlan}
        onClose={() => setUpgradeModal(false)}
      />

      <AddChannelModal
        isOpen={addChannelModal}
        lang={lang}
        onAddChannel={handleAddChannel}
        onClose={() => setAddChannelModal(false)}
      />

      <VideoModal
        isOpen={videoModal.isOpen}
        clip={videoModal.clip}
        lang={lang}
        onClose={() => setVideoModal({ isOpen: false, clip: null })}
      />

      {/* Toast Notification */}
      {toastMsg && <div className="toast">{toastMsg}</div>}
    </div>
  );
};
