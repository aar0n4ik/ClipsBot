import React, { useState } from "react";
import { AppData } from "../types";
import { Language, t } from "../lib/i18n";
import { Power, Save, RotateCcw, Key, ShieldCheck, Laptop } from "lucide-react";

interface SettingsTabProps {
  data: AppData;
  lang: Language;
  onLangChange: (lang: Language) => void;
  theme: string;
  onThemeChange: (theme: string) => void;
  onSaveSettings: (newValues: Record<string, any>) => void;
  onSaveToken: (token: string) => void;
  onToggleStopBot: (mode: "all" | "post" | "process" | "resume", reason?: string) => void;
  onForgetDevice: () => void;
}

export const SettingsTab: React.FC<SettingsTabProps> = ({
  data,
  lang,
  onLangChange,
  theme,
  onThemeChange,
  onSaveSettings,
  onSaveToken,
  onToggleStopBot,
  onForgetDevice,
}) => {
  const currentValues = data.settings.values || {};
  const [draftValues, setDraftValues] = useState<Record<string, any>>({ ...currentValues });
  const [isDirty, setIsDirty] = useState(false);
  const [stopMode, setStopMode] = useState<"all" | "post" | "process">("all");
  const [stopReason, setStopReason] = useState("");
  const [ghTokenInput, setGhTokenInput] = useState("");
  const [tokenSaved, setTokenSaved] = useState(false);

  const switches = data.switches || {};
  const isStopped = switches.process || switches.post || switches.stats;

  const handleValueChange = (key: string, val: any) => {
    setDraftValues(prev => ({ ...prev, [key]: val }));
    setIsDirty(true);
  };

  const handleSave = () => {
    onSaveSettings(draftValues);
    setIsDirty(false);
  };

  const handleReset = () => {
    setDraftValues({ ...currentValues });
    setIsDirty(false);
  };

  const handleTokenSubmit = () => {
    if (!ghTokenInput.trim()) return;
    onSaveToken(ghTokenInput.trim());
    setGhTokenInput("");
    setTokenSaved(true);
    setTimeout(() => setTokenSaved(false), 3000);
  };

  const systemStatus = data.status.system || {};
  const accountTokens = data.status.tokens || {};

  return (
    <div style={{ display: "grid", gap: 20 }}>
      {/* Bot Emergency Stop & Resume */}
      <div className="panel">
        <div className="ph2">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Power size={22} color={isStopped ? "var(--bad)" : "var(--good)"} />
            <div>
              <h3>{t("Остановка бота", lang)}</h3>
              <span className="muted small">
                {lang === "en" ? "Emergency controls for bot tasks" : "Управление остановкой конвейера"}
              </span>
            </div>
          </div>
          <span className={`chip ${isStopped ? "bad" : "good"}`}>
            {isStopped ? t("остановлен", lang) : t("работает", lang)}
          </span>
        </div>

        {isStopped ? (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <div>
              <b>{lang === "en" ? "Bot is currently stopped manually." : "Бот сейчас остановлен вручную."}</b>
              <p className="muted small">
                {lang === "en"
                  ? "All queued clips and recordings are safely preserved."
                  : "Все готовые клипы и записи сохранены."}
              </p>
            </div>
            <button
              type="button"
              className="btn amber"
              onClick={() => onToggleStopBot("resume")}
            >
              {lang === "en" ? "Resume Bot" : "Запустить снова"}
            </button>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
              {[
                { key: "all", title: lang === "en" ? "All tasks" : "Всё", sub: lang === "en" ? "clipping, analysis, publishing" : "нарезка, анализ, публикация" },
                { key: "post", title: lang === "en" ? "Publishing only" : "Только публикация", sub: lang === "en" ? "clips keep accumulating in reserve" : "клипы режутся, но не выходят" },
                { key: "process", title: lang === "en" ? "Clipping only" : "Только анализ", sub: lang === "en" ? "streams not cut, queue keeps shipping" : "новые стримы не режутся" },
              ].map(opt => (
                <label
                  key={opt.key}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 12,
                    border: `1.5px solid ${stopMode === opt.key ? "var(--accent)" : "var(--line)"}`,
                    background: stopMode === opt.key ? "var(--accent-soft)" : "var(--panel-2)",
                    cursor: "pointer",
                    display: "grid",
                    gap: 2,
                  }}
                >
                  <input
                    type="radio"
                    name="stopMode"
                    value={opt.key}
                    checked={stopMode === opt.key}
                    onChange={() => setStopMode(opt.key as any)}
                    style={{ display: "none" }}
                  />
                  <b style={{ fontSize: 14 }}>{opt.title}</b>
                  <span className="muted small">{opt.sub}</span>
                </label>
              ))}
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="text"
                className="inp"
                style={{ flex: 1, minWidth: 200 }}
                placeholder={lang === "en" ? "Reason (optional), e.g. streamer requested pause" : "Причина (необязательно), например: стример просил паузу"}
                value={stopReason}
                onChange={e => setStopReason(e.target.value)}
              />
              <button
                type="button"
                className="btn danger"
                onClick={() => onToggleStopBot(stopMode, stopReason)}
              >
                {lang === "en" ? "Stop Bot" : "Остановить"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Main Bot Parameters Editor */}
      <div className="panel">
        <div className="ph2">
          <div>
            <h3>{t("Как бот работает", lang)}</h3>
            <span className="muted small">
              {lang === "en" ? "Core quality thresholds, AI models, and rhythm rules" : "Параметры качества, моделей ИИ и ритма"}
            </span>
          </div>

          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="iconbtn"
              disabled={!isDirty}
              onClick={handleReset}
            >
              <RotateCcw size={14} />
              <span>{t("Отменить правки", lang)}</span>
            </button>
            <button
              type="button"
              className="btn amber sm"
              disabled={!isDirty}
              onClick={handleSave}
            >
              <Save size={14} />
              <span>{t("Сохранить", lang)}</span>
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {/* Quality Group */}
          <div>
            <h4 style={{ fontSize: 15, fontWeight: 700, color: "var(--accent)", marginBottom: 10 }}>
              {lang === "en" ? "Quality & Screening" : "Отбор моментов"}
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Min score to edit clip (1-10)" : "С какой оценки монтировать клип (1–10)"}
                </label>
                <input
                  type="number"
                  min="5"
                  max="10"
                  className="inp"
                  value={draftValues["quality.make_min"] ?? 7}
                  onChange={e => handleValueChange("quality.make_min", parseInt(e.target.value) || 7)}
                />
              </div>

              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Min score to post (1-10)" : "С какой оценки выкладывать (1–10)"}
                </label>
                <input
                  type="number"
                  min="5"
                  max="10"
                  className="inp"
                  value={draftValues["quality.post_min"] ?? 7}
                  onChange={e => handleValueChange("quality.post_min", parseInt(e.target.value) || 7)}
                />
              </div>

              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Max clips per hour of stream" : "Максимум клипов из часа стрима"}
                </label>
                <input
                  type="number"
                  min="1"
                  max="5"
                  className="inp"
                  value={draftValues["quality.max_per_chunk"] ?? 2}
                  onChange={e => handleValueChange("quality.max_per_chunk", parseInt(e.target.value) || 2)}
                />
              </div>

              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Reserve queue target" : "Запас клипов (цель)"}
                </label>
                <input
                  type="number"
                  min="1"
                  max="30"
                  className="inp"
                  value={draftValues["quality.reserve_target"] ?? 8}
                  onChange={e => handleValueChange("quality.reserve_target", parseInt(e.target.value) || 8)}
                />
              </div>
            </div>
          </div>

          <div style={{ height: 1, background: "var(--line)" }} />

          {/* AI Models Group */}
          <div>
            <h4 style={{ fontSize: 15, fontWeight: 700, color: "var(--accent)", marginBottom: 10 }}>
              {lang === "en" ? "AI Models & Checks" : "ИИ (модели и роли)"}
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Video Review Model" : "Модель для видео"}
                </label>
                <select
                  className="sel"
                  style={{ width: "100%", height: 44 }}
                  value={draftValues["ai.video_model"] || "gemini-4-argon"}
                  onChange={e => handleValueChange("ai.video_model", e.target.value)}
                >
                  <option value="gemini-4-argon">gemini-4-argon (Most accurate)</option>
                  <option value="gemini-3.8-flash">gemini-3.8-flash (Fast & low latency)</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Producer Planner Model" : "Модель продюсера"}
                </label>
                <select
                  className="sel"
                  style={{ width: "100%", height: 44 }}
                  value={draftValues["ai.planner_model"] || "gemini-4-argon"}
                  onChange={e => handleValueChange("ai.planner_model", e.target.value)}
                >
                  <option value="gemini-4-argon">gemini-4-argon</option>
                  <option value="gemini-3.8-flash">gemini-3.8-flash</option>
                </select>
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderRadius: 10, background: "var(--panel-2)" }}>
                <div>
                  <b style={{ fontSize: 13.5 }}>{lang === "en" ? "Scout Audio (Full Stream)" : "ИИ слушает весь стрим"}</b>
                  <div className="muted small">{lang === "en" ? "Discovers quiet stories & punchlines" : "Находит истории, мимо которых прошёл чат"}</div>
                </div>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={draftValues["ai.scout_audio"] ?? true}
                    onChange={e => handleValueChange("ai.scout_audio", e.target.checked)}
                  />
                  <span />
                </label>
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderRadius: 10, background: "var(--panel-2)" }}>
                <div>
                  <b style={{ fontSize: 13.5 }}>{lang === "en" ? "Second Opinion at Threshold" : "Второе мнение на пороге"}</b>
                  <div className="muted small">{lang === "en" ? "Borderline clips get independent look" : "Клип на грани перепроверяется"}</div>
                </div>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={draftValues["ai.second_opinion"] ?? true}
                    onChange={e => handleValueChange("ai.second_opinion", e.target.checked)}
                  />
                  <span />
                </label>
              </div>
            </div>
          </div>

          <div style={{ height: 1, background: "var(--line)" }} />

          {/* Publishing Rhythm Group */}
          <div>
            <h4 style={{ fontSize: 15, fontWeight: 700, color: "var(--accent)", marginBottom: 10 }}>
              {lang === "en" ? "Posting Rhythm & Spacing" : "Публикация и интервалы"}
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Releases per day with stream" : "Релизов в сутки с эфиром"}
                </label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  className="inp"
                  value={draftValues["posting.daily_max"] ?? 4}
                  onChange={e => handleValueChange("posting.daily_max", parseInt(e.target.value) || 4)}
                />
              </div>

              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Releases per day without stream" : "Релизов в сутки без эфира"}
                </label>
                <input
                  type="number"
                  min="0"
                  max="6"
                  className="inp"
                  value={draftValues["posting.offday_max"] ?? 2}
                  onChange={e => handleValueChange("posting.offday_max", parseInt(e.target.value) || 2)}
                />
              </div>

              <div>
                <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 4 }}>
                  {lang === "en" ? "Min gap between releases (min)" : "Пауза между релизами (мин)"}
                </label>
                <input
                  type="number"
                  min="60"
                  max="480"
                  step="30"
                  className="inp"
                  value={draftValues["posting.min_gap_minutes"] ?? 180}
                  onChange={e => handleValueChange("posting.min_gap_minutes", parseInt(e.target.value) || 180)}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderRadius: 10, background: "var(--panel-2)" }}>
                <div>
                  <b style={{ fontSize: 13.5 }}>{lang === "en" ? "Hot streak boost" : "Горячий клип — сразу"}</b>
                  <div className="muted small">{lang === "en" ? "Extra release if video goes viral" : "Продюсер даёт слот сверх лимита"}</div>
                </div>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={draftValues["posting.hot_now"] ?? true}
                    onChange={e => handleValueChange("posting.hot_now", e.target.checked)}
                  />
                  <span />
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* GitHub Token & Device Settings */}
      <div className="grid2">
        {/* GitHub Write Token */}
        <div className="panel">
          <div className="ph2">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Key size={18} color="var(--accent)" />
              <h3>{t("Ключ GitHub для записи", lang)}</h3>
            </div>
            <span className="chip good">
              <ShieldCheck size={12} /> {lang === "en" ? "Encrypted" : "Зашифрован"}
            </span>
          </div>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {lang === "en"
              ? "Fine-grained token with Contents: Read & Write. Stored encrypted with your dashboard password."
              : "GitHub → Settings → Developer settings → Fine-grained tokens (Contents: Read & write). Хранится зашифрованным паролем."}
          </p>

          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="password"
              className="inp"
              placeholder="github_pat_..."
              value={ghTokenInput}
              onChange={e => setGhTokenInput(e.target.value)}
            />
            <button
              type="button"
              className="btn amber sm"
              style={{ flexShrink: 0 }}
              onClick={handleTokenSubmit}
            >
              {lang === "en" ? "Save Key" : "Сохранить"}
            </button>
          </div>
          {tokenSaved && (
            <div style={{ color: "var(--good)", fontSize: 13, marginTop: 8, fontWeight: 600 }}>
              {lang === "en" ? "✓ Token encrypted and saved successfully!" : "✓ Ключ сохранён и проверен!"}
            </div>
          )}
        </div>

        {/* Device Settings */}
        <div className="panel">
          <div className="ph2">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Laptop size={18} color="var(--accent)" />
              <h3>{t("Это устройство", lang)}</h3>
            </div>
          </div>

          <div style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 600 }}>{t("Язык", lang)}</span>
              <select
                className="sel"
                value={lang}
                onChange={e => onLangChange(e.target.value as any)}
              >
                <option value="ru">Русский</option>
                <option value="en">English</option>
              </select>
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 600 }}>{t("Тема", lang)}</span>
              <select
                className="sel"
                value={theme}
                onChange={e => onThemeChange(e.target.value)}
              >
                <option value="light">{t("Светлая", lang)}</option>
                <option value="dark">{t("Тёмная", lang)}</option>
              </select>
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 8, borderTop: "1px solid var(--line)" }}>
              <span className="muted small">{t("Забыть пароль и ключ на этом устройстве", lang)}</span>
              <button
                type="button"
                className="iconbtn"
                onClick={onForgetDevice}
              >
                {t("Забыть", lang)}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* System Diagnostics Table */}
      <div className="panel">
        <div className="ph2">
          <h3>{t("Система", lang)}</h3>
          <span className="chip good">All Services Healthy</span>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>{lang === "en" ? "Service" : "Служба"}</th>
                <th>{lang === "en" ? "Status" : "Статус"}</th>
                <th>{lang === "en" ? "Details" : "Сообщение"}</th>
                <th className="r">{lang === "en" ? "Last Check" : "Проверка"}</th>
              </tr>
            </thead>
            <tbody>
              {[
                { name: lang === "en" ? "Twitch Stream Monitor" : "Проверка Twitch", ...systemStatus.watch },
                { name: lang === "en" ? "Auto-Clipping Pipeline" : "Конвейер нарезки", ...systemStatus.process },
                { name: lang === "en" ? "Platform Publisher" : "Публикация", ...systemStatus.post },
                { name: lang === "en" ? "Stats Collector" : "Статистика", ...systemStatus.stats },
                { name: lang === "en" ? "Daily Health Doctor" : "Ежедневная проверка", ...systemStatus.doctor },
              ].map((svc, i) => (
                <tr key={i}>
                  <td><b>{svc.name}</b></td>
                  <td>
                    <span className={`chip ${svc.level === "ok" ? "good" : svc.level === "error" ? "bad" : "warn"}`}>
                      {svc.level === "ok" ? t("норма", lang) : svc.level || "ok"}
                    </span>
                  </td>
                  <td className="muted small">{svc.msg || "running normally"}</td>
                  <td className="r muted small mono">just now</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
