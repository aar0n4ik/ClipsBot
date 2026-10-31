export type Language = "ru" | "en";

export const EN_DICT: Record<string, string> = {
  /* Header */
  "Обновить": "Refresh",
  "Настройки": "Settings",
  "Нарезки": "ClipsBot SaaS",
  "Обзор": "Overview",
  "Клипы": "Clips",
  "Аналитика": "Analytics",
  "Решения": "AI Producer",
  "Подписка": "Subscription",
  "Каналы": "Channels",
  "Помощь": "Help",

  /* Periods */
  "Сегодня": "Today",
  "Вчера": "Yesterday",
  "7 дней": "7 days",
  "14 дней": "14 days",
  "30 дней": "30 days",
  "Всё время": "All time",
  "Свой период": "Custom range",
  "Прошлый месяц": "Last month",
  "сегодня": "today",
  "вчера": "yesterday",
  "за 7 дней": "for 7 days",
  "за 14 дней": "for 14 days",
  "за 30 дней": "for 30 days",
  "за прошлый месяц": "for last month",
  "за всё время": "all time",
  "за период": "for period",
  "Применить": "Apply",
  "С": "From",
  "По": "To",
  "Статистика считается по дням": "Stats are counted per day",

  /* Platforms */
  "Все площадки": "All platforms",

  /* Overview & Hero */
  "Журнал бота": "Bot Event Log",
  "Этапы работы бота": "Bot pipeline stages",
  "Нет стрима": "Waiting for stream",
  "Идёт стрим": "Live stream",
  "Поиск": "Moment search",
  "Анализ": "AI transcript",
  "Видео": "Video review",
  "Монтаж": "Editing",
  "Публикация": "Publishing",
  "Просмотры": "Views",
  "по дням": "by day",
  "Площадки": "Platforms",
  "Лучшие клипы": "Top Clips",
  "Просмотры за период": "Views for period",
  "Квота клипов за месяц": "Monthly Clip Quota",
  "Использовано в тарифе": "Used in Plan",
  "Осталось в этом месяце": "Remaining this cycle",
  "Часов стримов обработано": "Stream hours parsed",
  "Тарифный план": "Subscription Plan",
  "Сменить тариф": "Change Plan",
  "Управление подпиской": "Manage Subscription",

  /* Clips Tab */
  "Ожидают публикации": "Awaiting publishing",
  "Черновики TikTok": "TikTok drafts",
  "Опубликованные": "Published",
  "Ошибки": "Errors",
  "Отклонённые": "Rejected",
  "TikTok пока без аудита API": "TikTok API sandbox note",
  "Почему моменты не стали клипами": "Why moments did not become clips",
  "Когда": "When",
  "Место в стриме": "Stream timecode",
  "Этап": "Stage",
  "Оценка": "Score",
  "Причина": "Reason",
  "Опубликовать сейчас": "Post now",
  "Отменить": "Cancel",
  "Повторить": "Retry",
  "Первый коммент": "First comment",
  "Скопировать": "Copy",
  "Скопировано": "Copied",
  "Подробнее": "Details",
  "Почему взят": "Why selected",
  "Звук": "Audio",

  /* Analytics */
  "Оценка ИИ против реальных просмотров": "AI Score vs Real Views",
  "Темы": "Topics",
  "Стиль заголовка и часы": "Title style & Best hours",
  "Клипы и охват": "Clips & Reach",
  "Клип": "Clip",
  "Где опубликован (просмотры)": "Where published (views)",
  "Дата": "Date",
  "За период": "Period views",
  "Лучший": "Best",
  "Охват": "Reach",
  "опубликован": "published",

  /* Brain */
  "Как продюсер решает, что и когда выкладывать": "How the AI producer decides when to post",
  "Откатить": "Rollback",
  "откачено": "rolled back",

  /* Subscription / SaaS */
  "Тарифы и подписка": "Plans & Subscription",
  "Выберите тариф": "Select a Plan",
  "Ежемесячно": "Monthly",
  "Ежегодно (-20%)": "Annual (-20%)",
  "Текущий план": "Current Plan",
  "Перейти на тариф": "Switch to Plan",
  "Активен": "Active",
  "Действует до": "Renews on",
  "Способ оплаты": "Payment Method",
  "История счетов": "Invoice History",
  "Счёт": "Invoice",
  "Сумма": "Amount",
  "Статус": "Status",
  "Оплачено": "Paid",
  "Скачать": "Download",
  "Включено в тариф": "Included in plan",
  "клипов в месяц": "clips / month",
  "стримерских каналов": "streamer channels",
  "качество": "video quality",

  /* Channels */
  "Каналы и стримеры": "Streamer Channels",
  "Подключить канал": "Connect Channel",
  "Все подключённые стримеры": "All Connected Streamers",
  "Стример на Twitch": "Twitch Streamer",
  "Клипов нарезано": "Clips Created",
  "В эфире сейчас": "Live Now",
  "Оффлайн": "Offline",
  "Переключить": "Switch Active",
  "Удалить": "Remove",

  /* Help */
  "Спросить": "Ask assistant",
  "Ожидание ответа": "Thinking...",
  "Думает": "Thinking",
  "Что изменилось": "What changed",

  /* Settings */
  "Остановка бота": "Bot Control",
  "Как бот работает": "Bot parameters",
  "Отменить правки": "Reset edits",
  "Сохранить": "Save",
  "Ключ GitHub для записи": "GitHub write token",
  "Это устройство": "This device",
  "Язык": "Language",
  "Тема": "Theme",
  "Как в системе": "System default",
  "Светлая": "Light",
  "Тёмная": "Dark",
  "Забыть пароль и ключ на этом устройстве": "Forget credentials on this device",
  "Забыть": "Forget",
  "Система": "System diagnostics",
  "работает": "running",
  "остановлен": "stopped",
  "норма": "normal",
  "сбой": "error",
  "внимание": "warning",

  /* Alerts */
  "Стрим идёт, но Twitch не сохраняет запись.": "Stream is live but Twitch is not saving recordings.",
  "Стример должен включить «Сохранять прошлые трансляции» в настройках Twitch.": "The streamer must enable 'Store past broadcasts' in Twitch settings.",
  "Бот остановлен вручную:": "Bot stopped manually:",
  "Включить — кнопка «Стоп» вверху.": "Resume via the Bot Control button.",
  "Демо с выдуманными цифрами. На GitHub Pages будут только настоящие данные бота.": "Live demo of the SaaS auto-clipping platform. Streamers and clips are interactive.",

  /* Common */
  "Закрыть": "Close",
  "Да": "Yes",
  "Отмена": "Cancel",
  "Точно?": "Are you sure?",
};

let currentLang: Language = (() => {
  try {
    const saved = localStorage.getItem("clips:lang");
    if (saved === "en" || saved === "ru") return saved;
  } catch {}
  return "ru";
})();

export function getLang(): Language {
  return currentLang;
}

export function setLang(lang: Language) {
  currentLang = lang;
  try {
    localStorage.setItem("clips:lang", lang);
  } catch {}
}

export function t(key: string, lang: Language = currentLang): string {
  if (lang === "en" && EN_DICT[key]) {
    return EN_DICT[key];
  }
  return key;
}
