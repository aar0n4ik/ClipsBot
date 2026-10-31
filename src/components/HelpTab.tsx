import React, { useState } from "react";
import { Language, t } from "../lib/i18n";
import { MessageSquare, Send, Sparkles } from "lucide-react";

interface HelpTabProps {
  lang: Language;
  onApplySettingsDiff?: (key: string, value: any) => void;
}

interface Message {
  id: string;
  role: "user" | "bot";
  text: string;
  time: string;
  changed?: Array<{ what: string; from: any; to: any }>;
}

export const HelpTab: React.FC<HelpTabProps> = ({ lang, onApplySettingsDiff }) => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "bot",
      text:
        lang === "en"
          ? "Hello! I am your ClipsBot SaaS assistant. I can explain why clips were selected, check quota limits, switch channels, diagnose publishing issues, or explain your subscription features. What would you like to know?"
          : "Привет! Я помощник ClipsBot SaaS. Могу рассказать о тарифах и лимитах, объяснить выбор моментов нейросетью, проверить статус каналов или помочь с расписанием публикаций. Чем помочь?",
      time: "12:00",
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isThinking, setIsThinking] = useState(false);

  const presetHints = [
    lang === "en" ? "How many clips left in current quota?" : "Сколько клипов осталось в лимите тарифа?",
    lang === "en" ? "Why didn't the last clip ship to Reels?" : "Почему последний клип не вышел на Reels?",
    lang === "en" ? "Pause posting for 24 hours" : "Поставь выкладку на паузу на сутки",
    lang === "en" ? "How to connect a new streamer channel?" : "Как подключить новый канал стримера?",
  ];

  const handleSendMessage = (textToSend?: string) => {
    const text = (textToSend || inputValue).trim();
    if (!text) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      text,
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages(prev => [...prev, userMsg]);
    setInputValue("");
    setIsThinking(true);

    setTimeout(() => {
      let botReply = "";
      let changed: Array<{ what: string; from: any; to: any }> | undefined = undefined;

      const lower = text.toLowerCase();
      if (lower.includes("лимит") || lower.includes("quota") || lower.includes("осталось") || lower.includes("left")) {
        botReply =
          lang === "en"
            ? "On your current Pro subscription plan, you have used 84 of 150 clips (66 clips remaining). Quota resets automatically on November 15, 2026."
            : "На вашем текущем тарифе Pro использовано 84 из 150 клипов (осталось 66 клипов). Лимит автоматически обновится 15 ноября 2026.";
      } else if (lower.includes("канал") || lower.includes("channel") || lower.includes("подключ")) {
        botReply =
          lang === "en"
            ? "To connect another streamer, go to the 'Channels' tab and click '+ Connect Streamer'. On the Pro plan you can monitor up to 5 channels simultaneously."
            : "Чтобы подключить канал стримера, перейдите во вкладку 'Каналы' и нажмите '+ Подключить канал'. На вашем тарифе Pro доступно до 5 стримеров одновременно.";
      } else if (lower.includes("reels") || lower.includes("инстаграм") || lower.includes("instagram")) {
        botReply =
          lang === "en"
            ? "Instagram API reported a temporary rate-limit cooldown until 18:00 UTC ('API access blocked'). The bot put Reels on hold and did not ship to TikTok/Shorts alone to preserve synchronicity across all three channels."
            : "Instagram сообщил о временном лимите ('API access blocked [blocked]'). По правилу синхронности выкладка ожидает разблокировки Instagram, чтобы счётчик клипов не разошёлся.";
      } else if (lower.includes("пауз") || lower.includes("pause") || lower.includes("сутки")) {
        botReply =
          lang === "en"
            ? "Publishing paused for 24 hours. The bot will keep recording and editing fresh stream moments into reserve, but won't publish to TikTok, Shorts, or Reels until unpaused."
            : "Поставил публикацию на паузу на 24 часа. Стримы продолжают нарезаться и копиться в запасе, но новые ролики на площадки не уходят. Снять паузу можно в Настройках или здесь.";
        changed = [{ what: lang === "en" ? "Publishing" : "Публикация", from: "active", to: "paused 24h" }];
      } else {
        botReply =
          lang === "en"
            ? "Checked bot status: Twitch monitoring is live, 3 clips are ready in queue with scores 7-9, and the next release slot is scheduled for peak audience at 19:07."
            : "Проверил состояние: Twitch активен, в очереди 3 готовых клипа с оценками 7–9. Следующий пост назначен на вечерний пик в 19:07.";
      }

      setMessages(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: "bot",
          text: botReply,
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          changed,
        },
      ]);
      setIsThinking(false);
    }, 700);
  };

  return (
    <div className="panel" style={{ display: "grid", gap: 16 }}>
      <div className="ph2">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <MessageSquare size={22} color="var(--accent)" />
          <div>
            <h3>{t("Помощь", lang)}</h3>
            <span className="muted small">
              {lang === "en"
                ? "Ask anything about how the bot makes decisions, or instruct changes in natural language"
                : "Спроси что угодно о работе бота или измени настройки простыми словами"}
            </span>
          </div>
        </div>
        <span className={`chip ${isThinking ? "warn" : "good"}`}>
          {isThinking ? t("Думает", lang) : lang === "en" ? "Ready" : "Готов к ответу"}
        </span>
      </div>

      {/* Preset Hints Chips */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {presetHints.map((hint, i) => (
          <button
            key={i}
            type="button"
            className="mini"
            style={{ borderRadius: 99, padding: "6px 12px", fontSize: 13 }}
            onClick={() => handleSendMessage(hint)}
          >
            <Sparkles size={12} color="var(--accent)" />
            <span>{hint}</span>
          </button>
        ))}
      </div>

      {/* Chat Messages */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          minHeight: 280,
          maxHeight: 480,
          overflowY: "auto",
          padding: "10px 4px",
        }}
      >
        {messages.map(msg => {
          const isUser = msg.role === "user";
          return (
            <div
              key={msg.id}
              style={{
                alignSelf: isUser ? "flex-end" : "flex-start",
                maxWidth: "85%",
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <div
                style={{
                  padding: "12px 16px",
                  borderRadius: isUser ? "16px 16px 2px 16px" : "16px 16px 16px 2px",
                  background: isUser ? "var(--accent)" : "var(--panel-2)",
                  color: isUser ? "#fff" : "var(--ink)",
                  border: isUser ? "none" : "1px solid var(--line)",
                  fontSize: 14.5,
                  lineHeight: 1.45,
                }}
              >
                {msg.text}
              </div>

              {msg.changed && (
                <div
                  style={{
                    padding: "10px 14px",
                    borderRadius: 12,
                    background: "var(--accent-soft)",
                    color: "var(--accent-ink)",
                    fontSize: 13,
                    display: "grid",
                    gap: 4,
                  }}
                >
                  <b>{t("Что изменилось", lang)}:</b>
                  {msg.changed.map((c, ci) => (
                    <div key={ci}>
                      • {c.what}: <span style={{ textDecoration: "line-through" }}>{c.from}</span> → <b>{c.to}</b>
                    </div>
                  ))}
                </div>
              )}

              <span
                style={{
                  fontSize: 11,
                  color: "var(--mute)",
                  alignSelf: isUser ? "flex-end" : "flex-start",
                  margin: "0 4px",
                }}
              >
                {msg.time}
              </span>
            </div>
          );
        })}

        {isThinking && (
          <div style={{ alignSelf: "flex-start", color: "var(--mute)", fontStyle: "italic", fontSize: 13 }}>
            {t("Ожидание ответа", lang)}
          </div>
        )}
      </div>

      {/* Input box */}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <input
          type="text"
          className="inp"
          placeholder={lang === "en" ? "Ask a question or request a setting change..." : "Спроси что угодно про работу бота..."}
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") handleSendMessage();
          }}
        />
        <button
          type="button"
          className="btn amber"
          style={{ flexShrink: 0 }}
          onClick={() => handleSendMessage()}
          disabled={!inputValue.trim() || isThinking}
        >
          <Send size={15} />
          <span>{t("Спросить", lang)}</span>
        </button>
      </div>
    </div>
  );
};
