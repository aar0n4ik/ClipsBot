/* ClipsBot i18n — RU / EN language switcher
   Saves choice in localStorage under key "clips:lang"
   Injects translated text via MutationObserver so dynamic content is covered.
*/
(function () {
  "use strict";
  const LS_KEY = "clips:lang";
  // Язык браузера нужен только до первого осознанного выбора: дальше решает localStorage.
  function browserLang() {
    try {
      const list = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ""];
      for (const l of list) {
        const code = String(l).toLowerCase().slice(0, 2);
        if (code === "ru" || code === "uk" || code === "be" || code === "kk") return "ru";
        if (code) return "en";
      }
    } catch {}
    return "ru";
  }
  let lang = (() => {
    try {
      const saved = localStorage.getItem(LS_KEY);
      if (saved === "en" || saved === "ru") return saved;   // выбор пользователя живёт между заходами
    } catch {}
    return browserLang();   // до первого выбора — как в браузере
  })();

  /* ── Full RU → EN dictionary ─────────────────────────────────────── */
  const EN = {
    /* header */
    "Обновить": "Refresh",
    "Настройки": "Settings",

    /* period buttons */
    "Сегодня": "Today",
    "Вчера": "Yesterday",
    "7 дней": "7 days",
    "30 дней": "30 days",
    "Всё время": "All time",
    "Просмотры вчера": "Views yesterday",
    "Доход за 14 дней": "Earnings for 14 days",
    "Просмотры за 14 дней": "Views for 14 days",
    "Доход за прошлый месяц": "Earnings for last month",
    "Просмотры за прошлый месяц": "Views for last month",
    "Свой период": "Custom range",
    "за": "for",
    "за период": "for period",
    "за прошлый месяц": "for last month",
    "за 14 дней": "for 14 days",
    "вчера": "yesterday",
    "По": "To",
    "С": "From",
    "Применить": "Apply",
    "Статистика считается по дням": "Stats are counted per day",
    "14 дней": "14 days",

    /* platform select */
    "Все площадки": "All platforms",

    /* KPI cards */
    "Просмотры за период": "Views for period",
    "К выплате · новые клипы": "Payable · new clips",
    "К выплате · доплата за рост": "Payable · growth top-up",
    "По площадкам и клипам": "By platform & clip",
    "К выплате всего": "Total payable",
    "Подтвердить получение": "Confirm payout",
    "Скрыть напоминание": "Hide reminder",
    "Можно выводить": "Ready to withdraw",
    "до порога": "until threshold",
    "получено всего": "total received",
    "последний раз": "last time",

    /* pipeline / posting */
    "Конвейер нарезки": "Clipping pipeline",
    "Публикация": "Publishing",
    "Жду стрим": "Waiting for stream",
    "работает": "running",
    "ошибка": "error",
    "ждёт": "idle",
    "Стрим": "Stream",
    "Кусок записи": "Recording segment",
    "Прогресс": "Progress",
    "Обновлено": "Updated",
    "Ждут публикации": "Awaiting publishing",
    "Следующий пост по плану": "Next post scheduled",
    "Следующая проверка через": "Next check in",
    "Оффлайн": "Offline",
    "эфир был": "last live",
    "LIVE": "LIVE",
    "зрит.": "viewers",

    /* pipeline stage labels */
    "звук": "audio",
    "чат": "chat",
    "пики": "peaks",
    "речь": "speech",
    "ИИ": "AI",
    "монтаж": "edit",

    /* chart */
    "Просмотры по дням": "Views by day",
    "считается по лучшей площадке каждого клипа": "counted by best platform per clip",
    "последние 60 дней · ": "last 60 days · ",
    "выбранный период выделен · ": "selected period highlighted · ",

    /* clips table */
    "Клипы и доход": "Clips & earnings",
    "Клип": "Clip",
    "Где опубликован (просмотры)": "Where published (views)",
    "Дата": "Date",
    "За период": "Period views",
    "Лучший": "Best",
    "К выплате": "Payable",
    "новый": "new",
    "доплата": "top-up",
    "оплачен": "paid",
    "клипов": "clips",
    "новых клипов": "new clips",
    "новых клипа": "new clips",
    "новый клип": "new clip",
    "Пока нет опубликованных роликов. Как только площадки покажут первые просмотры, они появятся здесь.": "No published videos yet. Once platforms report views, they will appear here.",

    /* breakdown dialog */
    "Новые клипы": "New clips",
    "Доплата за рост": "Growth top-up",
    "Клипы, за которые ещё не платили. Сумма считается по площадке, где у клипа больше всего просмотров.": "Clips not yet paid. Amount is based on the platform with most views.",
    "Клипы, которые выросли после прошлой выплаты. Платится только прирост лучшего результата сверх уже оплаченного.": "Clips that grew after the last payout. Only the incremental best-result growth is paid.",
    "Закрыть": "Close",
    "Все": "All",
    "Уже оплачено": "Already paid",
    "Пусто": "Empty",
    "Сейчас здесь ничего нет.": "Nothing here right now.",

    /* ledger */
    "Реестр выплат": "Payout log",
    "Добавить получение": "Add payout",
    "Этот месяц": "This month",
    "Прошлый месяц": "Last month",
    "Показывать отменённые": "Show cancelled",
    "Получено за выбранное": "Received in period",
    "из них за новые": "of which new",
    "доплаты за рост": "growth top-ups",
    "Записей": "Entries",
    "Ещё не оплачено": "Unpaid",
    "Реестр не загрузился:": "Ledger failed to load:",
    "Записей пока нет. Когда получишь деньги, нажми «Подтвердить получение»: бот запишет сумму, дату и какие клипы на каких площадках она закрыла.": "No entries yet. Once you receive payment, tap \"Confirm payout\" and the bot will record the amount, date and which clips were covered.",
    "Отчёт": "Report",
    "Вернуть": "Restore",
    "отменено": "cancelled",
    "новых клипов · ": "new clips · ",
    "доплата за рост": "growth top-up",
    "недоплата": "shortfall",
    "переплата": "overpayment",
    "записано": "recorded",
    "Отменить запись? Она останется в реестре зачёркнутой, а сумма вернётся в «К выплате».": "Cancel this entry? It will remain in the log as crossed out and the amount will return to \"Payable\".",
    "Отменить запись": "Cancel entry",
    "Оставить": "Keep",

    /* payout dialog */
    "Точно записать?": "Confirm recording?",
    "Сколько получил": "Amount received",
    "Когда": "When",
    "Сейчас": "Now",
    "Другая дата": "Custom date",
    "Комментарий (необязательно)": "Comment (optional)",
    "например: PayPal, за неделю": "e.g. PayPal, weekly",
    "Отмена": "Cancel",
    "Дальше": "Next",
    "Назад": "Back",
    "Да, записать в реестр": "Yes, record it",
    "Сохраняю…": "Saving…",
    "Укажи сумму больше нуля.": "Please enter an amount greater than zero.",
    "Сначала добавь ключ GitHub в настройках.": "Please add your GitHub key in settings first.",
    "Неоплаченных просмотров сейчас нет. Запись сохранит только сумму и дату.": "No unpaid views right now. The entry will save only the amount and date.",

    /* statement dialog */
    "Отчёт о выплате": "Payout report",
    "Скопировать текстом": "Copy as text",
    "Скопировать CSV": "Copy CSV",
    "Получено": "Received",
    "Ставка": "Rate",
    "По расчёту": "Calculated",
    "Тип": "Type",
    "Ссылки (просмотры на момент выплаты)": "Links (views at time of payout)",
    "Было оплачено": "Previously paid",
    "Оплачено сейчас": "Paid now",
    "Сумма": "Amount",
    "Каждый клип оплачивается один раз по лучшей площадке. «Доплата» — только рост лучшего результата сверх ранее оплаченного.": "Each clip is paid once by best platform. \"Top-up\" covers only growth beyond what was previously paid.",

    /* video dialog */
    "Не удалось загрузить файл: его уже удалили после публикации или репозиторий закрыт.": "Could not load file: it was deleted after publishing or the repository is private.",

    /* queue */
    "Очередь и последние клипы": "Queue & recent clips",
    "ждут публикации": "awaiting publishing",
    "Клипов пока нет. После первого стрима сюда придут готовые нарезки с оценкой ИИ.": "No clips yet. After the first stream, ready clips with AI scores will appear here.",
    "В очереди": "Queued",
    "Отправлен в TikTok, не подтверждён": "Sent to TikTok inbox",
    "Черновик не опубликован": "Draft not published",
    "Опубликован": "Published",
    "Обрабатывается": "Processing",
    "Ошибка": "Error",
    "Устарел": "Expired",
    "Выложен": "Posted",
    "Повтор": "Retry",
    "Битый": "Broken",
    "риск": "risk",
    "▶ Смотреть": "▶ Watch",
    "Подробнее": "Details",
    "Первый коммент:": "First comment:",
    "Копировать": "Copy",
    "Почему взяли:": "Why selected:",
    "Звук:": "Audio:",
    "Почему выложен тогда:": "Why posted then:",
    "Смотреть полный стрим": "Watch full stream",
    "Отменить публикацию": "Cancel publishing",
    "Повторить публикацию": "Retry publishing",
    "Отменить публикацию этого клипа? Потом можно будет сделать новый, похожий.": "Cancel publishing this clip? A similar one can be created later.",

    /* learn */
    "Что бот выяснил": "What the bot learned",
    "Обучение на паузе. ": "Learning is paused. ",
    "Учтено роликов:": "Videos counted:",
    "Пока данных мало, всё держится около «как обычно» — выводы появляются, когда разница устойчива (уверенность от 85% и минимум 8 роликов).": "While data is limited everything stays near \"as usual\" — conclusions emerge when differences are consistent (≥85% confidence, ≥8 videos).",
    "Стиль заголовка": "Hook style",
    "Панчлайн в первые секунды": "Punchline in first seconds",
    "Английская строка субтитров": "English subtitle line",
    "Полоса прогресса": "Progress bar",
    "недосказанность": "tease",
    "конфликт": "conflict",
    "цифра": "number",
    "цитата": "quote",
    "да": "yes",
    "нет": "no",
    "только RU": "RU only",
    "RU + EN": "RU + EN",
    "полоса — доля новых клипов с этим вариантом; справа — эффект к обычным просмотрам": "bar = share of new clips with this variant; right = effect vs average views",
    "Лучшие часы": "Best hours",
    "Постов в сутки": "Posts per day",
    "разгон": "warm-up",
    "потолок по данным": "data-driven cap",
    "Подсказка ИИ-отборщику": "AI selector hint",
    "Появится после первых публикаций.": "Will appear after first publications.",

    /* insights */
    "Какие темы заходят": "Top categories",
    "Площадки": "Platforms",
    "Средний лучший результат клипа по теме. Бот сам поднимает в очереди темы, которые заходят.": "Average best clip result by category. The bot promotes well-performing topics in the queue.",
    "Появится, когда наберётся статистика.": "Will appear once enough data is collected.",
    "Всего просмотров на площадке. За период лучшим было:": "Total platform views. Best for the period:",

    /* categories */
    "Смешное": "Funny",
    "Конфликт": "Conflict",
    "Деньги": "Money",
    "Америка": "America",
    "Клиенты": "Customers",
    "Дорога": "Road",
    "Эмоции": "Emotional",
    "Чат": "Chat",
    "Другое": "Other",

    /* decisions */
    "Решения бота": "Bot decisions",
    "Только с откатом": "Rollbackable only",
    "Поставить обучение на паузу": "Pause learning",
    "Включить обучение": "Resume learning",
    "Ждут выполнения:": "Pending:",
    "команда": "command",
    "команды": "commands",
    "команд": "commands",
    "бот применит их при следующем запуске.": "the bot will apply them on the next run.",
    "Откатить": "Rollback",
    "откачено": "rolled back",
    "вариант": "variant",
    "темы": "topics",
    "часы": "hours",
    "объём": "volume",
    "здоровье": "health",
    "откат": "rollback",
    "пропуск": "skip",
    "звук": "audio",
    "подсказка": "hint",
    "пауза": "pause",
    "Вернуть как было и закрепить на 14 дней?": "Revert to previous and lock for 14 days?",
    "Откатить": "Rollback",
    "Не надо": "Cancel",
    "Решений пока нет. Здесь появится каждое изменение поведения бота: что поменялось, почему, с какими цифрами.": "No decisions yet. Every bot behaviour change will appear here: what changed, why, with figures.",

    /* system */
    "Система": "System",
    "Проверка Twitch": "Twitch check",
    "Нарезка": "Clipping",
    "Статистика и обучение": "Stats & learning",
    "Ежедневная проверка": "Daily check",
    "Монтаж": "Rendering",
    "норма": "ok",
    "сбой": "error",
    "внимание": "warning",
    "не подключён": "not connected",
    "ошибка": "error",
    "доступ есть": "connected",
    "Подключить": "Connect",
    "бот продлевает сам": "bot renews automatically",
    "доступ ещё": "expires in",
    "дн.": "days",
    "файлов в очереди на GitHub:": "files in GitHub queue:",
    "Появится после первого запуска.": "Will appear after the first run.",

    /* alerts */
    "Стрим идёт, но Twitch не сохраняет запись.": "Stream is live but Twitch is not saving the recording.",
    "Стример должен включить «Сохранять прошлые трансляции» в настройках Twitch.": "The streamer must enable \"Store past broadcasts\" in Twitch settings.",
    "Сбой:": "Error:",
    "GitHub давно не запускал задачу.": "GitHub hasn't run the scheduled job in a while.",
    "Проверь вкладку Actions: не выключено ли расписание.": "Check the Actions tab to see if the schedule is disabled.",
    "Ранний сигнал.": "Early signal.",
    "нужен повторный вход.": "needs re-authentication.",
    "Кусок": "Segment",
    "стрима не обработался.": "of stream failed to process.",
    "Запусти в Actions «2 · Process» с галочкой «Повторить пропуски». Ошибка:": "Run \"2 · Process\" in Actions with \"Retry skipped\" checked. Error:",
    "последний успех": "last success",
    "Открыть лог": "Open log",

    /* health modes */
    "норма": "normal",
    "присмотреться": "watch",
    "остывание": "cooldown",
    "ждёт": "idle",

    /* gate / login */
    "Нарезки": "Clips",
    "Данные зашифрованы. Введи пароль дашборда (секрет": "Data is encrypted. Enter the dashboard password (secret",
    "Запомнить на этом устройстве": "Remember on this device",
    "Открыть": "Open",
    "Неверный пароль.": "Incorrect password.",

    /* settings dialog */
    "Напоминание о выплате": "Payout reminder",
    "Подсветка и напоминание, когда к выплате накопится": "Highlight and remind when payable reaches",
    "или больше": "or more",
    "Ключ GitHub для записи": "GitHub write key",
    "Нужен для кнопок «Подтвердить получение», «Откатить» и пауз. GitHub → Settings → Developer settings → Fine-grained tokens → только этот репозиторий, права Contents: Read and write. Хранится только в этом браузере.":
      "Required for \"Confirm payout\", \"Rollback\" and pause buttons. GitHub → Settings → Developer settings → Fine-grained tokens → this repo only, Contents: Read and write. Stored in this browser only.",
    "Проверяю…": "Checking…",
    "Сохранено (в демо не проверяется).": "Saved (not verified in demo mode).",
    "Ключ работает, запись доступна.": "Key works, write access confirmed.",
    "Не подошёл:": "Invalid:",
    "Ключ сохранён на этом устройстве.": "Key saved on this device.",
    "Ключ не задан.": "No key set.",
    "Сохранить": "Save",
    "Ставка и порог вывода": "Rate & withdrawal threshold",
    "Забыть пароль и ключ на этом устройстве": "Forget password & key on this device",
    "Забыть": "Forget",
    "Забыто": "Forgotten",
    "Готово": "Done",
    "Язык": "Language",

    /* demo banner */
    "Это демо с выдуманными цифрами, чтобы было видно, как всё выглядит. На твоём сайте GitHub Pages будут только настоящие данные бота.":
      "This is a demo with made-up numbers to show how everything looks. Your GitHub Pages site will show only real bot data.",

    /* misc time */
    "только что": "just now",
    "мин назад": "min ago",
    "ч назад": "h ago",
    "дн назад": "d ago",
    "Скопировано": "Copied",
    "Выдели текст и скопируй вручную": "Select the text and copy it manually",
    "В демо команды не отправляются": "Commands are not sent in demo mode",
    "Отправлено. Бот выполнит при следующем запуске (до часа)": "Sent. The bot will apply it on the next run (within an hour).",
    "Не получилось сохранить из-за одновременных изменений. Попробуй ещё раз.": "Save failed due to concurrent changes. Please try again.",
    "Добавь ключ GitHub в настройках, чтобы сохранять изменения.": "Add your GitHub key in Settings to save changes.",
    "Запись отменена": "Entry cancelled",
    "Запись возвращена": "Entry restored",
    "Напоминание выключено, вернуть можно в настройках": "Reminder off — re-enable it in Settings",

    /* owed / period labels */
    "Доход сегодня": "Earnings today",
    "Доход вчера": "Earnings yesterday",
    "Доход за 7 дней": "Earnings for 7 days",
    "Доход за 30 дней": "Earnings for 30 days",
    "Доход за всё время": "Earnings all time",
    "за 1 000 просмотров лучшей площадки клипа": "per 1,000 views of the clip's best platform",
    "новых клипов за период · всего клипов": "new clips in period · total clips",
    "ещё ни разу не оплачены": "never paid",
    "вырос после выплаты": "grew since payout",
    "выросли после выплаты": "grew since payout",
    "клипов выросли": "clips grew",

    /* health/posting status */
    "нет данных": "no data",
    "сегодня": "today",
    "из": "of",
    "план": "plan",
    "последний пост": "last post",
    "постов ещё не было": "no posts yet",
    "аккаунт не подключён": "account not connected",
    "Следующий пост по плану (": "Next post scheduled (",
    ") через": ") in",
    "потолок подобран по данным": "data-driven cap",
    "обычный режим": "normal mode",
    "разгон аккаунта, день": "account warm-up, day",
    "режим «норма» → «присмотреться»": "mode: normal → watch",
    "Последние ролики в первые 2 часа отстают от нормы — ранний сигнал": "Recent videos underperform in first 2 hours — early signal",
    "эфир идёт": "stream is live",
    "обработано кусков:": "segments processed:",
    "публикации в норме": "publishing normal",
    "статистика собрана": "stats collected",
    "всё проверено": "all checks passed",
    "из них": "of which",
    "подключено": "connected",
    /* сцена этапа на обзоре */
    "Проверяю Twitch, не начался ли эфир": "Checking Twitch for a new stream",
    "эфиров ещё не было": "no streams yet",
    "Последняя запись": "Last recording",
    "Обработано": "Processed",
    "Идёт запись фрагмента": "Recording a segment",
    "Последние фрагменты": "Recent segments",
    "эфир идёт": "live now",
    "Поиск моментов": "Finding moments",
    "Фрагмент стрима": "Stream segment",
    "В этом фрагменте пока нет отмеченных моментов.": "No moments marked in this segment yet.",
    "Анализ куска": "Chunk analysis",
    "Расшифровка речи": "Speech transcript",
    "Расшифровки пока нет: бот ещё не разбирал речь в этом куске.": "No transcript yet: the bot has not parsed speech in this chunk.",
    "Оценка ИИ": "AI score",
    "Беру": "Taking",
    "Отбросил": "Dropped",
    "Проверка видео": "Video check",
    "Смотрю кадры": "Watching frames",
    "Кадры": "Frames",
    "кадр не сохранён": "frame not saved",
    "нет кадра": "no frame",
    "Кандидатов на проверку пока нет.": "No candidates to check yet.",
    "Монтаж клипа": "Editing the clip",
    "Монтировать пока нечего.": "Nothing to edit yet.",
    "Формат": "Format",
    "Длина": "Length",
    "Склеек": "Cuts",
    "без склеек": "no cuts",
    "Вырезано пауз": "Silence trimmed",
    "Субтитры": "Subtitles",
    "Выкладывать пока нечего.": "Nothing to publish yet.",
    "ещё не уходил": "not sent yet",
    "идёт загрузка": "uploading",
    "Бот ещё не обработал ни одной записи.": "The bot has not processed a recording yet.",
    "Первый фрагмент ещё записывается.": "The first segment is still recording.",
    /* помощь */
    "Это крупная правка": "That is a big change",
    "Поправил сам": "Changed it myself",
    "Не получилось": "Did not work",
    "Поправит сам:": "Changes itself:",
    "Не возьмёт:": "Will not take on:",

    /* ── добавлено: полное покрытие интерфейса ─────────────────── */
    "Демо с выдуманными цифрами. На GitHub Pages будут только настоящие данные бота.": "Demo with made-up numbers. GitHub Pages shows only the bot's real data.",
    "Пароль и ключ удалятся только из этого браузера. В репозитории ключ останется.": "The password and key are removed from this browser only. The key stays in the repository.",
    "Файл не загрузился: его уже удалили после публикации или репозиторий закрыт.": "The file didn't load: it was deleted after publishing, or the repository is private.",
    "Поиск и монтаж идут дальше. Снять паузу — вкладка «Помощь» или «Настройки».": "Finding and editing continue. Unpause from the “Help” or “Settings” tab.",
    "Решений ещё нет — появятся после первого запуска публикации с новым мозгом.": "No decisions yet — they appear after the first posting run on the new brain.",
    "столько готовых держим про запас; дальше планка отбора поднимается на балл": "how many ready clips we keep in reserve; above that the bar rises by a point",
    "Бот снова будет подстраивать стиль заголовков, темы и часы по статистике.": "The bot will go back to tuning title style, topics and hours from the stats.",
    "Жду 19:07: вечерний пик аудитории, а у клипа с эфира ещё 34 часа жизни.": "Waiting for 19:07: the audience's evening peak, and the stream clip still has 34 hours of life.",
    "клип ровно на пороге ИИ смотрит ещё раз независимо, итог — среднее": "a clip right at the threshold gets an independent second look; the result is the average",
    "Пока пусто: список наполнится после куска стрима с новым мозгом.": "Empty for now: the list fills after a stream segment on the new brain.",
    "Ключ GitHub не подошёл (нужны права Contents: Read and write).": "The GitHub key didn't work (needs Contents: Read and write).",
    "Ключ GitHub не подошёл: нужен доступ Contents: Read and write.": "The GitHub key didn't work: it needs Contents: Read and write.",
    "Нарезка, выкладка и статистика продолжат работу по расписанию.": "Clipping, posting and stats keep running on schedule.",
    "Настройки появятся после первого запуска бота с новой версией.": "Settings appear after the bot's first run on the new version.",
    "Сильный клип с эфира, пауза прошла, вечер — выкладываю сразу.": "Strong clip from the stream, the gap has passed, it's evening — posting right away.",
    "Выводы появляются от 8 роликов на вариант и уверенности 85%.": "Findings appear from 8 videos per variant and 85% confidence.",
    "Добавь ключ GitHub в Настройках, чтобы сохранять изменения.": "Add a GitHub key in Settings to save changes.",
    "меньше трёх часов ролики отбирают друг у друга первый показ": "under three hours videos steal each other's first impressions",
    "считается по площадке, где у клипа больше всего просмотров": "counted on the platform where the clip has the most views",
    "финальная оценка после того, как ИИ посмотрел видео (1–10)": "the final score after the AI watched the video (1–10)",
    "Вопросов пока не было. Спроси что угодно про работу бота.": "No questions yet. Ask anything about how the bot works.",
    "Записей нет. Получил деньги — нажми «Записать получение».": "No records. Got paid? Hit “Record a payout”.",
    "находит истории и тихие панчлайны, которые чат не заметил": "finds stories and quiet punchlines that chat missed",
    "gemini-4-argon умнее, gemini-3.8-flash дешевле и быстрее": "gemini-4-argon is smarter, gemini-3.8-flash is cheaper and faster",
    "Actions → «2 · Process» → галочка «Повторить пропуски».": "Actions → “2 · Process” → tick “Retry gaps”.",
    "Стример должен включить «Сохранять прошлые трансляции».": "The streamer has to turn on “Store past broadcasts”.",
    "лаги, есть ли момент, где резать, правдив ли заголовок": "lags, whether the moment is real, where to cut, whether the title is honest",
    "Неоплаченных просмотров нет — запишется только сумма.": "No unpaid views — only the amount will be recorded.",
    "паузы, которые ИИ отметил по видео, вырезаются всегда": "pauses the AI flagged from the video are always cut",
    "Применится при следующем запуске каждой задачи бота.": "Applies on each bot task's next run.",
    "ниже не выйдет никогда, даже если выкладывать нечего": "below this nothing ever ships, even with an empty queue",
    "отдыхает до 18:00 UTC: Instagram: API access blocked": "paused until 18:00 UTC: Instagram: API access blocked",
    "у ключа нет права записи (Contents: Read and write)": "the key has no write access (Contents: Read and write)",
    "Клип не выйдет ни на одну площадку. Файл удалится.": "The clip ships to no platform. The file is deleted.",
    "Публикация запущена — через пару минут клип выйдет": "Publishing started — the clip goes live in a couple of minutes",
    "в день без стрима выкладываем из запаса, но меньше": "on a day without a stream we post from reserve, but less",
    "выше монтируем только то, что сильнее уже лежащего": "above this we only edit what beats what's already queued",
    "Данных ещё нет: бот не сделал ни одного запуска.": "No data yet: the bot hasn't run once.",
    "Отправлено: бот выполнит до следующей публикации": "Sent: the bot will do it before the next post",
    "ИИ проверяет, правда ли в кадре то, о чём речь.": "The AI checks whether the frame really shows what's being said.",
    "новые стримы не режутся, очередь выкладывается": "new streams aren't cut, the queue keeps posting",
    "Как продюсер решает, что и когда выкладывать": "How the producer decides what to post and when",
    "Параллельно прошлый клип уходит на площадки.": "Meanwhile the previous clip is going out to the platforms.",
    "Своё название (видно в статистике и отчётах)": "Custom title (shown in stats and reports)",
    "обычно выходит 0–2: лучше меньше, но сильнее": "usually 0–2: fewer but stronger is better",
    "с какой суммы напоминать, что можно выводить": "the amount at which to remind you that you can withdraw",
    "yt_main: «остывание» → «норма». всё в норме": "yt_main: “cooldown” → “normal”. all fine",
    "всё: нарезку, анализ, выкладку и статистику": "everything: clipping, analysis, posting and stats",
    "Вернётся как было и закрепится на 14 дней.": "Reverts to how it was and locks for 14 days.",
    "Данные зашифрованы. Введи пароль дашборда.": "The data is encrypted. Enter the dashboard password.",
    "Подними ставку до $1.50 за 1000 просмотров": "Raise the rate to $1.50 per 1,000 views",
    "После прошлого релиза прошло 60 мин из 90.": "60 of 90 minutes have passed since the last release.",
    "Эти просмотры больше не попадут в выплату.": "These views will no longer count toward a payout.",
    "один раз на весь клип, без движения камеры": "once for the whole clip, no camera movement",
    "Появится, когда клипам будет больше 48 ч.": "Appears once clips are older than 48 h.",
    "охранник разворачивает к служебному входу": "the guard sends him to the service entrance",
    "Почему последний клип не вышел на Reels?": "Why didn't the last clip ship to Reels?",
    "с такой оценкой берём сверх всех лимитов": "at this score we take it regardless of any limit",
    "Стример реагирует на ситуацию на заказе": "The streamer reacts to something on a delivery",
    "клипы режутся и копятся, но не выходят": "clips are cut and queued, but nothing ships",
    "нарезка, анализ, публикация и статистика": "clipping, analysis, publishing and stats",
    "ИИ-продюсер решает, когда выкладывать": "the AI producer decides when to post",
    "Идущая сейчас нарезка будет прервана.": "The clipping run in progress will be interrupted.",
    "Пока пусто — бот ещё ничего не делал.": "Empty for now — the bot hasn't done anything yet.",
    "Разбивки по клипам у этой записи нет.": "This record has no per-clip breakdown.",
    "Оценка ИИ против реальных просмотров": "AI score vs real views",
    ". Включить — кнопка «Стоп» вверху.": ". Turn back on with the “Stop” button at the top.",
    "Жду 19:07: вечерний пик аудитории.": "Waiting for 19:07: the audience's evening peak.",
    "ИИ смотрит видео каждого финалиста": "the AI watches each finalist's video",
    "Поставь выкладку на паузу на сутки": "Pause posting for a day",
    "Стиль заголовка: данных пока мало.": "Title style: not enough data yet.",
    "Сдвигать кадр, если стример сбоку": "Shift the frame if the streamer is off to the side",
    "дашборд: ключ записи (зашифрован)": "dashboard: write key (encrypted)",
    "Исключить из статистики и выплат": "Exclude from stats and payouts",
    "Числа должны быть не меньше нуля": "Numbers must not be below zero",
    "по лучшей площадке каждого клипа": "by each clip's best platform",
    "понятная ситуация, есть развязка": "a clear situation with a payoff",
    "Второе мнение на границе порога": "Second opinion at the threshold",
    "Пока нет роликов с просмотрами.": "No videos with views yet.",
    "Почему моменты не стали клипами": "Why moments didn't become clips",
    "С какой оценки монтировать клип": "Minimum score to edit a clip",
    "свежесть важнее идеального часа": "freshness beats the perfect hour",
    "В демо вопросы не отправляются": "Questions aren't sent in the demo",
    "Максимум клипов из часа стрима": "Max clips per hour of stream",
    "Стиль заголовка к норме канала": "Title style vs the channel's norm",
    "Укажи сумму (можно с минусом).": "Enter an amount (negative is allowed).",
    "Штраф $200 за 5 минут парковки": "A $200 ticket for 5 minutes of parking",
    "вернуть в статистику и выплаты": "return to stats and payouts",
    "ключ не видит этот репозиторий": "the key can't see this repository",
    "например: стример просил паузу": "for example: the streamer asked for a pause",
    "нарезку и анализ новых стримов": "clipping and analysis of new streams",
    "ИИ слушает весь стрим целиком": "the AI listens to the whole stream",
    "Изменений поведения пока нет.": "No behaviour changes yet.",
    "Клиентка оставила $100 чаевых": "A customer left a $100 tip",
    "Пауза длиннее, с — вырезается": "Pauses longer than, s — are cut",
    "черновик так и не опубликован": "the draft was never published",
    "Корректор субтитров по звуку": "Subtitle proofreader against the audio",
    "Неоплаченных просмотров нет.": "No unpaid views.",
    "Поставить обучение на паузу?": "Pause learning?",
    "Сильный клип с эфира — сразу": "Strong clip from the stream — right away",
    "выложу при ближайшем запуске": "will post on the next run",
    "конфликт с понятной ставкой": "conflict with clear stakes",
    "TikTok пока без аудита API": "TikTok is not API-audited yet",
    "Бездомные живут лучше нас?": "Do homeless people live better than us?",
    "Забыть на этом устройстве?": "Forget on this device?",
    "Обед в Санта-Монике за $40": "A $40 lunch in Santa Monica",
    "С какой оценки выкладывать": "Minimum score to post",
    "Ставка за 1 000 просмотров": "Rate per 1,000 views",
    "Чат заказал пиццу… клиенту": "Chat ordered a pizza… for the customer",
    "Это дубликат другого видео": "This is a duplicate of another video",
    "Вырезать паузы и молчание": "Cut pauses and silence",
    "Пауза между релизами, мин": "Gap between releases, min",
    "Релизов в сутки без эфира": "Releases per day without a stream",
    "Что закрывает эта выплата": "What this payout covers",
    "дашборд: вопрос помощнику": "dashboard: question to the assistant",
    "звук, чат, клипы зрителей": "audio, chat, viewer clips",
    "ключ неверный или отозван": "the key is wrong or revoked",
    "реестр: запись возвращена": "ledger: record restored",
    "Изменить ставку и вывод?": "Change rate and withdrawal?",
    "Нужны клипы старше 48 ч.": "Needs clips older than 48 h.",
    "Охрана не пустила в лифт": "Security wouldn't let him in the lift",
    "Релизов в сутки с эфиром": "Releases per day with a stream",
    "Ресторан забыл ползаказа": "The restaurant forgot half the order",
    "Собака не отдавала пакет": "The dog wouldn't give up the bag",
    "в черновиках — опубликуй": "in drafts — publish it",
    "выкладку на все площадки": "posting to every platform",
    "Автопилот повёз не туда": "Autopilot went the wrong way",
    "Бот остановлен вручную:": "Stopped manually:",
    "Доставка по ЛА на Тесле": "Delivering around LA in a Tesla",
    "Записать корректировку?": "Record an adjustment?",
    "Причина (необязательно)": "Reason (optional)",
    "Сделай порог вывода $30": "Set the withdrawal threshold to $30",
    "проверка раз в 10 минут": "checks every 10 minutes",
    "реестр: запись изменена": "ledger: record edited",
    "реестр: запись отменена": "ledger: record voided",
    "Нарезки albert1million": "albert1million clips",
    "Стиль заголовка и часы": "Title style and hours",
    "Ты вообще откуда, бро?": "Where are you even from, bro?",
    "обновление не удалось:": "update failed:",
    "реестр: ставка и вывод": "ledger: rate and withdrawal",
    "Запустить бота снова?": "Start the bot again?",
    "Исключительный момент": "Exceptional moment",
    "Сохранить и проверить": "Save and check",
    "Что ты делал сегодня?": "What did you do today?",
    "Школьник просит совет": "A schoolkid asks for advice",
    "реестр: корректировка": "ledger: adjustment",
    "реестр: пометки видео": "ledger: video flags",
    "9:16, субтитры, звук": "9:16, subtitles, audio",
    "Минимальная длина, с": "Minimum length, s",
    "Не выкладывать клип?": "Don't post this clip?",
    "Остановлено вручную:": "Stopped manually:",
    "Почему выбран и тексты": "Why it was selected, and the copy",
    "Сохранить изменения?": "Save changes?",
    "Сохранить настройки?": "Save settings?",
    "запись фрагментами по часу": "recording in one-hour segments",
    "обработано кусков: 1": "segments processed: 1",
    "ИИ (ключи и модели)": "AI (keys and models)",
    "Изменения поведения": "Behaviour changes",
    "Настройки сохранены": "Settings saved",
    "Последнее в журнале": "Latest in log",
    "Эфиров ещё не было.": "No streams yet.",
    "было иначе, стало «": "was different, now “",
    "разъединить склейку": "split the merge",
    "Бот снова работает": "Bot is running again",
    "Видео в статистике": "Videos in stats",
    "Включить обучение?": "Enable learning?",
    "Записать в реестр?": "Record in the ledger?",
    "Записать получение": "Record a payout",
    "Ничего не найдено.": "Nothing found.",
    "Отчёт для стримера": "Report for the streamer",
    "Площадок пока нет.": "No platforms yet.",
    "дашборд: настройки": "dashboard: settings",
    "поправил заголовок": "fixed the title",
    "Ожидание окна публикации": "Waiting for a publishing slot",
    "ИИ оценивает речь": "the AI scores the speech",
    "Откатить решение?": "Roll back the decision?",
    "Поиск по названию": "Search by title",
    "Этапы работы бота": "Bot pipeline stages",
    "жду: вечерний пик": "waiting: evening peak",
    "Опубликовать сейчас?": "Publish now?",
    "ИИ смотрит кадры": "the AI looks at the frames",
    "Изменить запись?": "Edit the record?",
    "К выплате сейчас": "Payable now",
    "Как бот работает": "How the bot works",
    "Модель для видео": "Model for video",
    "Модель продюсера": "Producer model",
    "Остановить бота?": "Stop the bot?",
    "Отборщик (текст)": "Screener (text)",
    "Отменить запись?": "Void the record?",
    "Оценок пока нет.": "No scores yet.",
    "Режиссёр (видео)": "Director (video)",
    "Черновики TikTok": "TikTok drafts",
    "курьер в америке": "courier in america",
    "нарезка и анализ": "clipping and analysis",
    "реакция на сумму": "reaction to an amount",
    "Вернуть запись?": "Restore the record?",
    "Запустить снова": "Start again",
    "Изменить запись": "Edit the record",
    "Клипов ещё нет.": "No clips yet.",
    "Неверная сумма.": "Invalid amount.",
    "Отменить правки": "Discard changes",
    "Оценка по видео": "Video score",
    "Ставка за 1 000": "Rate per 1,000",
    "Только публикация": "Publishing only",
    "без комментария": "no comment",
    "Опубликовать сейчас": "Publish now",
    "GitHub ответил": "GitHub replied",
    "Бот остановлен": "Bot is stopped",
    "Публикация клипа": "Publishing the clip",
    "Место в стриме": "Position in stream",
    "Не выкладывать": "Don't post",
    "Остановка бота": "Stopping the bot",
    "Отбор моментов": "Finding moments",
    "Получено всего": "Total received",
    "Потолок запаса": "Reserve ceiling",
    "Ставка и вывод": "Rate and withdrawal",
    "Что изменилось": "What changed",
    "Это устройство": "This device",
    "до пика 2 часа": "2 hours to the peak",
    "Не публиковать": "Don't publish",
    "обрабатывается": "processing",
    "#доставкавсша": "#deliveryintheusa",
    "Анализ текста": "Text analysis",
    "Ожидают публикации": "Awaiting publication",
    "Как в системе": "As in the system",
    "Корректировка": "Adjustment",
    "Почему тогда:": "Why then:",
    "Только анализ": "Analysis only",
    "дашборд: пуск": "dashboard: start",
    "как на стриме": "same as the stream",
    "корректировка": "adjustment",
    "своё название": "custom title",
    "Бот работает": "Bot is running",
    "Да, записать": "Yes, record it",
    "Запас клипов": "Clip reserve",
    "Запись куска": "Recording segment",
    "Лучшие клипы": "Best clips",
    "Остановлено:": "Stopped:",
    "Показать всё": "Show all",
    "Порог вывода": "Withdrawal threshold",
    "Прошли видео": "Passed video",
    "Прошли текст": "Passed text",
    "без названия": "untitled",
    "отмена клипа": "cancel clip",
    "Журнал бота": "Bot log",
    "ИИ-продюсер": "AI producer",
    "Какие клипы": "Which clips",
    "Комментарий": "Comment",
    "ждёт релиза": "awaiting release",
    "подключение": "connection",
    "свежак 9/10": "fresh 9/10",
    "(откачено)": "(reverted)",
    "Все выводы": "All findings",
    "Выкладываю": "Posting",
    "Идёт стрим": "Stream is live",
    "Нет стрима": "No stream",
    "Остановить": "Stop",
    "Отменённые": "Cancelled",
    "Отправлено": "Sent",
    "Статистика": "Stats",
    "за сегодня": "today",
    "копировать": "copy",
    "не ответил": "no reply",
    "подключить": "connect",
    "просмотров": "views",
    "статистика": "stats",
    "Аналитика": "Analytics",
    "Все этапы": "All stages",
    "Ожидание ответа": "Waiting for a reply",
    "Запустить": "Start",
    "Кандидаты": "Candidates",
    "Недоплата": "Underpaid",
    "Переплата": "Overpaid",
    "Сохранено": "Saved",
    "Эфир идёт": "Live now",
    "Я получил": "I received it",
    "в очереди": "queued",
    "в порядке": "fine",
    "исключить": "exclude",
    "ключ есть": "key present",
    "ключа нет": "no key",
    "обновлено": "updated",
    "повторить": "retry",
    "просмотра": "views",
    "Публикация": "Posting",
    "Опубликовать": "Publish",
    "Действия": "Actions",
    "Записано": "Recorded",
    "Изменить": "Edit",
    "Монтирую": "Editing",
    "Отменить": "Cancel",
    "Площадка": "Platform",
    "Спросить": "Ask",
    "На стриме": "On stream",
    "публикация": "publishing",
    "дашборд:": "dashboard:",
    "исключён": "excluded",
    "обучение": "learning",
    "откатить": "roll back",
    "площадка": "platform",
    "площадки": "platforms",
    "площадок": "platforms",
    "получено": "received",
    "продюсер": "producer",
    "просмотр": "view",
    "смотреть": "watch",
    "согласен": "agrees",
    "Выбрать": "Select",
    "Выплата": "Payout",
    "Выплаты": "Payouts",
    "История": "History",
    "Отклонённые": "Rejected",
    "Пометки": "Flags",
    "Причина": "Reason",
    "Разделы": "Sections",
    "Русский": "Russian",
    "Светлая": "Light",
    "Экспорт": "Export",
    "моменты": "moments",
    "нарезка": "clipping",
    "ответил": "replied",
    "открыть": "open",
    "отменён": "cancelled",
    "по дням": "by day",
    "правила": "rules",
    "стример": "streamer",
    "— нет —": "— none —",
    "Анализ": "Analysis",
    "Валюта": "Currency",
    "Видео:": "Video:",
    "Клипов": "Clips",
    "Критик": "Critic",
    "Оценка": "Score",
    "Ошибки": "Errors",
    "Пароль": "Password",
    "Период": "Period",
    "Помощь": "Help",
    "Рендер": "Render",
    "СТАВКА": "RATE",
    "Слушаю": "Listening",
    "Смотрю": "Watching",
    "Ссылки": "Links",
    "Точно?": "Are you sure?",
    "Тёмная": "Dark",
    "готова": "ready",
    "думает": "thinking",
    "критик": "critic",
    "отмена": "cancel",
    "оценка": "score",
    "повтор": "retry",
    "Видео": "Video",
    "Вышел": "Posted",
    "Опубликованные": "Published",
    "Клипы": "Clips",
    "Обзор": "Overview",
    "Опции": "Options",
    "Поиск": "Search",
    "Цифры": "Numbers",
    "вышел": "posted",
    "готов": "ready",
    "дубли": "duplicates",
    "из 10": "of 10",
    "кадры": "frames",
    "клипа": "clips",
    "клипы": "clips",
    "стрим": "stream",
    "Звук": "Audio",
    "Идёт": "Live",
    "Ключ": "Key",
    "Решения": "Decisions",
    "Пики": "Peaks",
    "Тема": "Topic",
    "Темы": "Topics",
    "Этап": "Stage",
    "выкл": "off",
    "демо": "demo",
    "клип": "clip",
    "мимо": "passed",
    "эфир": "stream",
    "Всё": "Everything",
    "Жду": "Waiting",
    "Ищу": "Finding",
    "Лог": "Log",
    "МСК": "MSK",
    "вкл": "on",
    "все": "all",
    "лог": "log",
    "Да": "Yes",
    "ок": "ok",
    "ч": "h",

    "Читаю данные бота и отвечаю. Обычно минута-две — страницу можно закрыть, ответ сохранится.": "Reading the bot's data and replying. Usually a minute or two — you can close the page, the answer is saved.",
    "Новая ставка действует для всех будущих расчётов. Уже записанные выплаты не меняются.": "The new rate applies to all future calculations. Payouts already recorded don't change.",
    "Ручная поправка суммы (бонус, комиссия, ошибка). Клипы не закрывает. Минус — вычесть.": "A manual amount correction (bonus, fee, mistake). Closes no clips. Negative subtracts.",
    "Сначала добавь ключ GitHub в Настройках — без него страница не может записать вопрос.": "Add a GitHub key in Settings first — without it the page can't write the question.",
    "Медиана лучшего результата · число клипов. Продюсер поднимает темы, которые заходят.": "Median best result · clip count. The producer pushes topics that land.",
    "Склеенные считаются одним клипом: платим один раз, по площадке с лучшим результатом.": "Merged videos count as one clip: paid once, on the best-performing platform.",
    "расписание слотов на день; в слот уходит лучший клип очереди, остальные не пропадают": "the day's slot schedule; each slot takes the queue's best clip, the rest aren't lost",
    "auto — облако Gemini (быстро и точнее), при сбое Whisper; whisper — только локально": "auto — Gemini cloud (fast and more accurate), Whisper on failure; whisper — local only",
    "Бот перестанет менять стиль заголовков, темы и часы. Отбор и выкладка продолжатся.": "The bot stops changing title style, topics and hours. Selection and posting continue.",
    "выключено — работает простой план по лучшим часам": "off — a simple plan by best hours is used",
    "ИИ смотрит видео финалиста 2/4": "The AI watches finalist 2/4",
    ", просмотры соберу через час": ", views in an hour",
    ", статистику соберу через час": ", stats in an hour",
    "дашборд: стоп (": "dashboard: stop (",
    "остановлен": "stopped",
    "Просмотры": "Views",
    "· кусок": "· segment",
    "Все выводы": "All payouts",
    "лучший час по плану": "best hour per the plan",
    "согласен": "agrees",
    "· фрагмент": "· segment",
    "Запись фрагмента": "Recording segment",
    "Опубликовал": "Posted",
    "Ожидает": "Waiting",
    "Думает": "Thinking",
    "Анализ текста": "Text analysis",
    "Заголовки": "Titles",
    "Анализ видео": "Video analysis",
    "Контроль качества": "Quality control",
    "Отбор": "Selection",
    "Дубликат": "Duplicate",
    "Звук": "Audio",
    "На паузе": "Paused",

    "Удалён вручную": "Removed manually",
    "Отменён": "Cancelled",
    "Пропущен для синхронизации": "Skipped for sync",
    "Публикуется": "Publishing",
    "Обработка": "Processing",
    "В черновиках TikTok": "In TikTok drafts",
    "Ожидает публикации": "Awaiting publication",
    "кадров": "frames",
    "Просмотр": "Reviewing",
    "речи": "speech",
    "Разбор": "Analyzing",
    "моментов": "moments",
    "стрима": "stream",
    "Ожидание": "Waiting for",
    "Сейчас нечего публиковать: слабые клипы бот не выпускает. Новые клипы появятся после обработки следующего фрагмента стрима.": "Nothing to publish right now: the bot doesn't release weak clips. New clips will appear after the next stream segment is processed.",
    "За последние сутки публикаций не было.": "Nothing was published in the last 24 hours.",
    "Сумма выплаты": "Payout amount",
    "Считается по выбранным клипам": "Calculated from the selected clips",
    "Изменить вручную": "Edit manually",
    "Вернуть расчёт": "Use calculated amount",
    "Дата и время получения": "Date and time received",
    "Что закрывает эта выплата": "What this payout covers",
    "Все": "All",
    "Новый": "New",
    "Доплата": "Top-up",
    "Выбрать клип": "Select clip",
    "Невыбранные останутся к выплате": "Unselected ones remain payable",

    "(не согласен)": "(disagrees)",
    "Финальная оценка после просмотра видео": "Final score after watching the video",
    "Например: подними ставку до $1.50 за 1000 просмотров": "For example: raise the rate to $1.50 per 1,000 views",
    "выложено": "posted",
    "жду": "waiting",
    "владелец": "owner",
    "синхрон": "sync",
    "план": "plan",
    "предпроверка": "pre-check",
    "сильный клип с идущего эфира — занимает следующий слот раньше": "a strong clip from the live stream — takes the next slot early",
    "слоты на сегодня прошли": "today's slots are over",
    "ни одна площадка не подключена": "no platform is connected",
    "нет клипов нужного качества — ничего слабого не выкладываю": "no clips of the required quality — nothing weak gets posted",
    "проверка раз в 10 минут": "checking every 10 minutes",
    "Чат": "Chat",
    "Клиенты": "Customers",
    "выложил": "posted",
    "Максимальная длина, с": "Max length, s",
    "Медиана просмотров ролика": "Median views per video",
    "число роликов": "video count",
    "За период": "For the period",
    "потолок; обычно ИИ режет 15–45 с, длиннее минуты — только после отдельной проверки": "a ceiling; the AI usually cuts 15–45 s, anything over a minute only after a separate check",
    "Все площадки: стиль хука «цифра» заходит лучше (+35% к норме, n=11, уверенность 88%) — его доля 25% → 46%": "All platforms: the “number” hook style performs better (+35% over baseline, n=11, confidence 88%) — its share 25% → 46%",
    "Новых клипов": "New clips",
    "к прошлому периоду": "vs previous period",
    "в среднем": "avg",
    "Пока пусто — бот ещё ничего не делал.": "Nothing yet — the bot hasn't done anything.",
    "Площадок пока нет.": "No platforms yet.",
    "— бот кладёт ролик в черновики TikTok в ту же минуту, что и на Shorts и Reels. Открой TikTok → Профиль → Черновики (Входящие) и нажми «Опубликовать», чтобы вышло одновременно.": "— the bot drops the video into TikTok drafts the same minute it posts to Shorts and Reels. Open TikTok → Profile → Drafts (Inbox) and tap “Post” so everything goes out together.",
    "Дубликат — один и тот же момент, выложенный отдельно: склеенные считаются одним клипом и оплачиваются по площадке с лучшим результатом. Исключённое пропадает из статистики и выплат, его можно вернуть.": "A duplicate is the same moment posted separately: merged ones count as a single clip and are paid by the best-performing platform. Excluded videos drop out of stats and payouts, and can be restored.",
    "Отвечает тот же ИИ, что отбирает клипы: он читает настоящие данные бота — очередь, оценки, площадки, деньги. Вопрос и ответ зашифрованы паролем дашборда. Ответ приходит за минуту-две, страницу можно закрыть.": "You're answered by the same AI that picks the clips: it reads the bot's real data — queue, scores, platforms, money. Question and answer are encrypted with the dashboard password. The reply takes a minute or two, you can close the page.",
    "ставку, порог вывода и валюту, пороги отбора и длину клипа, расписание и часы тишины, паузу площадки, стоп и запуск, повтор или отмену клипа, паузу обучения.": "the rate, payout threshold and currency, selection thresholds and clip length, the schedule and quiet hours, pausing a platform, stop and start, retrying or cancelling a clip, pausing learning.",
    "новые функции, переделку сайта, правки кода и логики отбора, новую площадку, починку багов. На такое ответит прямо и скажет, что нужно сделать в коде, — эту работу лучше отдать полноценной модели с доступом к репозиторию.": "new features, rebuilding the site, code and selection-logic changes, a new platform, bug fixes. It will say so directly and tell you what to change in the code — that work is better given to a full model with repo access.",
    "GitHub → Settings → Developer settings → Fine-grained tokens → только этот репозиторий, права Contents и Actions: Read and write. Ключ хранится в репозитории зашифрованным твоим паролем, поэтому вводится один раз для всех устройств.": "GitHub → Settings → Developer settings → Fine-grained tokens → this repository only, Contents and Actions: Read and write. The key is stored in the repo encrypted with your password, so you enter it once for all devices.",
    "Медиана лучшего результата клипа старше 48 ч. Если высокие оценки не набирают больше — ИИ ошибается, и порог стоит поднять.": "Median best result for clips older than 48 h. If high scores don't earn more views, the AI is off and the threshold should go up.",
    "Какие клипы закрыты, не меняется. Чтобы переделать выплату целиком — отмени её и запиши заново.": "Which clips are closed doesn't change. To redo a payout entirely, void it and record it again.",
    "Выйдет на все готовые площадки при ближайшем запуске публикации (бот сразу его запустит). Правила паузы между релизами для этого клипа не действуют.": "It will go out to every ready platform on the next publishing run (the bot starts one right away). The pause rules between releases don't apply to this clip.",
    "Ответ не пришёл за пять минут. Проверь вкладку Actions на GitHub: воркфлоу «6 · Assist» мог не запуститься.": "No answer in five minutes. Check the Actions tab on GitHub: the “6 · Assist” workflow may not have started.",
    "Вопрос записан, но запустить воркфлоу не вышло. Открой Actions → «6 · Assist» → Run workflow, ответ придёт сюда.": "The question is saved, but the workflow didn't start. Open Actions → “6 · Assist” → Run workflow, the answer will show up here.",
    "ИИ слушает фрагмент и исправляет ошибки распознавания (сленг, имена, бренды); бот запоминает исправления": "the AI listens to the fragment and fixes recognition errors (slang, names, brands); the bot remembers the corrections",
    "Команда отправлена; выйдет при ближайшем запуске (для мгновенного запуска ключу нужны права Actions)": "Command sent; it runs on the next scheduled start (instant start needs Actions rights on the key)",
    "Демо с выдуманными цифрами. На GitHub Pages будут только настоящие данные бота.": "Demo with made-up numbers. GitHub Pages shows only the bot's real data.",
    "Данные зашифрованы. Введи пароль дашборда.": "The data is encrypted. Enter the dashboard password.",
    "Запомнить на этом устройстве": "Remember on this device",
    "Неверный пароль.": "Wrong password.",
    "Язык": "Language",
    "Русский": "Русский",
  };

  /* ─── Translation engine ──────────────────────────────────────────── */
  const original = new WeakMap(); // textNode → original Russian text
  const applied  = new WeakMap(); // textNode → last value we wrote

  // Для частичных совпадений берём только длинные ключи (короткие вроде «из», «Все» ломают текст), сначала самые длинные.
  const PARTIAL = Object.keys(EN).filter(k => k.length >= 6).sort((x, y) => y.length - x.length);


  /* Составные фразы собираются в коде из кусков и числа. Пословная замена давала «клипов 3 из 7»:
     половина по-английски, половина нет. Поэтому целая строка сначала проверяется этими шаблонами. */
  const RX = [
    [/^Доход за (?:период )?(.+)$/, "Earnings for $1"],
    [/^Просмотры за (?:период )?(.+)$/, "Views for $1"],
    [/^Выбрано (\d+) из (\d+) на (.+)$/, "Selected $1 of $2 totaling $3"],
    [/^(?:Кусок|Фрагмент) (.+?): кандидатов (\d+), по тексту (\d+), по видео (\d+), клипов (\d+)$/, "Segment $1: $2 candidates, $3 passed text, $4 passed video, $5 clips"],
    [/^Публикация: (?:выложено|опубликовано): (.+)$/, "Publishing: posted to $1"],
    [/^владелец нажал «Выложить сейчас»$/, "owner pressed “Post now”"],
    [/^клип (\S+) вышел не везде — жду (.+), чтобы дотянуть; новые клипы не выходят, пока площадки не сравняются$/, "clip $1 didn't go out everywhere — waiting for $2 to catch up; new clips are held until the platforms match"],
    [/^дотягиваю (.+): клип уже вышел на других площадках$/, "catching up $1: the clip is already out on other platforms"],
    [/^жду (.+) — клип выходит только на всех площадках сразу$/, "waiting for $1 — a clip goes out only on all platforms at once"],
    [/^сегодня уже (\d+) релиз\(ов\) из (\d+) — лучшие из очереди уйдут завтра$/, "$1 of $2 releases already today — the best in the queue go out tomorrow"],
    [/^после прошлого релиза прошло (\d+) мин из (\d+)$/, "$1 of $2 min have passed since the last release"],
    [/^слот (\d\d:\d\d) — лучший клип очереди$/, "slot $1 — the queue's best clip"],
    [/^следующий слот в (\d\d:\d\d)$/, "next slot at $1"],
    [/^(.+) не прошла проверку перед загрузкой — клип ждёт, не выходит никуда$/, "$1 failed the pre-upload check — the clip waits and goes nowhere"],
    [/^ночь аудитории \((\S+) по (.+)\)$/, "audience night ($1 $2)"],
    [/^Проверка раз в (\d+) минут$/, "Checking every $1 minutes"],
    [/^(\d[\d\s  .,]*) зрител(?:ь|я|ей)$/, "$1 viewers"],
    [/^клипов (\d+) из (\d+)$/, "clips $1 of $2"],
    [/^Запись (?:куска|фрагмента) (.+)$/, "Recording segment $1"],
    [/^(?:Кусок|Фрагмент) (.+)$/, "Segment $1"],
    [/^В эфире (.+)$/, "Live $1"],
    [/^В эфире$/, "Live"],
    [/^(\d+) пик(?:ов|а|)$/, "$1 peaks"],
    [/^кандидатов (\d+)$/, "candidates $1"],
    [/^Оценка по видео (\d+) из 10$/, "Video score $1 of 10"],
    [/^(?:Вышел|Опубликован) (.+), (?:просмотры|статистику) соберу через час$/, "Posted $1, stats in an hour"],
    [/^(\d+) из (\d+) подключено$/, "$1 of $2 connected"],
    [/^1 площадка подключено$/, "1 platform connected"],
    [/^(\d+) площад(?:ка|ки|ок) подключено$/, "$1 platforms connected"],
    [/^(\d+) клип(?:ов|а|)$/, "$1 clips"],
    [/^(\d+) ч (\d+) мин$/, "$1 h $2 min"],
    [/^(\d+) мин$/, "$1 min"],
    [/^(\d+) мин назад$/, "$1 min ago"],
    [/^(\d+) ч назад$/, "$1 h ago"],
    [/^(\d+) дн назад$/, "$1 d ago"],
    [/^только что$/, "just now"],
    [/^доступ ещё (\d+) дн\.$/, "$1 days of access left"],
    [/^дубли ×(\d+)$/, "duplicates ×$1"],
    [/^Разъединить склейку \((\d+) видео\)$/, "Split the merge ($1 videos)"],
    [/^Лучшие часы \((.+)\)$/, "Best hours ($1)"],
    [/^название → «(.*)»$/, "title → “$1”"],
    [/^Скопировано$/, "Copied"],
    [/^порог (.+) набран\.$/, "the $1 threshold is reached."],
    [/^порог (.+) набран$/, "the $1 threshold is reached"],
    [/^в очереди (.+)$/, "in queue $1"],
    [/^(\d+(?:[.,]\d+)?) с$/, "$1 s"],
    [/^(\d+) ч$/, "$1 h"],
    [/^Вырезано пауз: (.+) \((\d+) склеек\)$/, "Pauses cut: $1 ($2 joins)"],
    [/^новые клипы (.+)$/, "new clips $1"],
    [/^доплата за рост (.+)$/, "growth top-up $1"],
    [/^файлов клипов на GitHub: (\d+) \((.+) МБ\)$/, "clip files on GitHub: $1 ($2 MB)"],
    [/^Эфир идёт (.+) — «(.+)»$/, "Live now $1 — “$2”"],
    [/^Эфир идёт (.+)$/, "Live now $1"],
    [/^Последний эфир был (.+)$/, "Last stream was $1"],
    [/^Эфиров ещё не было$/, "No streams yet"],
    [/^(.+) на (?:куске|фрагменте) (.+)$/, "$1 on segment $2"],
    [/^(?:Вышел|Опубликован) «(.+)» на (.+)$/, "Posted “$1” on $2"],
    [/^(?:Вышел|Опубликован) (.+)$/, "Posted $1"],
    [/^([\d\s  .,]+) просм\.$/, "$1 views"],
    [/^лучшая: (.+)$/, "best: $1"],
    [/^Просмотры за (.+)$/, "Views for $1"],
    [/^в среднем (.+) в день$/, "$1 per day on average"],
    [/^(\d+)% из (.+)$/, "$1% of $2"],
    [/^(.+) за 1 000 просмотров лучшей площадки$/, "$1 per 1,000 views on the best platform"],
    [/^Можно выводить — порог (.+) набран$/, "Ready to withdraw — the $1 threshold is reached"],
    [/^До вывода ещё (.+) · минимум (.+)$/, "$1 to go · minimum $2"],
    [/^Пост в (.+)$/, "Post at $1"],
    [/^отдыхает до (.+)$/, "resting until $1"],
    [/^обновлено (.+)$/, "updated $1"],
    [/^последнее решение (.+)$/, "last decision $1"],
    [/^(\d+) из (\d+)$/, "$1 of $2"],
    [/^Остановлено вручную: (.+)$/, "Stopped manually: $1"],
    [/^Параллельно прошлый клип уходит на площадки$/, "Meanwhile the previous clip is going out to the platforms"],
    [/^Выдели текст и скопируй вручную$/, "Select the text and copy it manually"],
  ];

  const CYR = /[А-Яа-яЁё]/;
  // Разделители, по которым строка режется на самостоятельные куски: точка-предложение, тире, точка с запятой, «·», двоеточие.
  const SPLIT = /(\s*[—–]\s*|\s*·\s*|(?<=[.!?…])\s+|\s*;\s*|:\s+)/;

  /* Перевод одной фразы. Возвращает null, если перевода нет — тогда остаётся русский оригинал.
     Главное правило: либо кусок переводится целиком, либо не трогаем вовсе. Смесь языков
     («паузу platforms», «Views за 7 days») хуже честного русского. */
  function phrase(s, depth) {
    s = s.trim().replace(/\(отдыхает до (\d\d:\d\d)\)/g, "(resting until $1)");
    if (!s || !CYR.test(s)) return null;

    const full = EN[s];
    if (full !== undefined) return full;

    // «Проверка раз в 10 минут.» — то же, что без точки, плюс точка
    if (/[^.…]\.$/.test(s)) {
      const r = phrase(s.slice(0, -1), depth + 1);
      if (r !== null) return r + ".";
    }
    // Начало с заглавной («Проверка…») ищем как строчное из словаря и поднимаем регистр
    if (/^[А-ЯЁ]/.test(s)) {
      const low = s[0].toLowerCase() + s.slice(1);
      if (EN[low] !== undefined) return EN[low][0].toUpperCase() + EN[low].slice(1);
    }

    // Несколько предложений подряд: переводим каждое отдельно, иначе жадный шаблон съедает хвост
    if (depth < 4) {
      const sents = s.split(/(?<=[.!?…])\s+/);
      if (sents.length > 1) {
        const tr = sents.map(x => phrase(x, depth + 1));
        if (tr.every(x => x !== null)) return tr.join(" ");
      }
    }

    for (const [re_, to] of RX) {
      const m = s.match(re_);
      if (!m) continue;
      return to.replace(/\$(\d)/g, (_, i) => {
        const part = m[+i] || "";
        if (depth >= 4 || !CYR.test(part)) return part;
        const t = phrase(part, depth + 1);
        return t === null ? part : t;
      });
    }

    // Строка собрана из нескольких самостоятельных кусков — переводим каждый отдельно.
    if (depth < 4) {
      const parts = s.split(SPLIT);
      if (parts.length > 1) {
        let hit = false;
        const out = parts.map((p, i) => {
          if (i % 2) return p;                       // разделитель
          const t = p.trim();
          if (!t) return p;
          if (!CYR.test(t)) return p;
          const r = phrase(t, depth + 1);
          if (r === null) return p;
          hit = true;
          return p.replace(t, () => r);
        }).join("");
        if (hit && !CYR.test(out)) return out;
      }
    }

    // Последнее средство — пословная подстановка, и только если она не оставила русских слов.
    let out = s;
    for (const ru of PARTIAL) if (out.includes(ru)) out = out.split(ru).join(EN[ru]);
    if (out !== s && !CYR.test(out)) return out;

    return null;
  }

  function toEn(src, depth) {
    const trimmed = src.trim();
    if (!trimmed) return src;
    let out = phrase(trimmed, depth || 0);
    if (out === null) return src;
    out = out.replace(/«([^»]*)»/g, "“$1”");   // кавычки тоже английские
    return src.replace(trimmed, () => out);
  }

  /* ?i18n=debug — выводит в консоль всё, что осталось по-русски в английском режиме.
     Чинить пропуски по списку, а не искать их глазами. */
  function reportMisses() {
    const left = new Set();
    document.querySelectorAll("body *").forEach(el => {
      if (/^(SCRIPT|STYLE|TEXTAREA)$/.test(el.nodeName)) return;
      el.childNodes.forEach(n => {
        if (n.nodeType === 3 && /[А-Яа-яЁё]/.test(n.nodeValue)) left.add(n.nodeValue.trim());
      });
    });
    if (left.size) console.warn("i18n: не переведено (" + left.size + "):", [...left].sort());
    else console.info("i18n: русского текста на странице не осталось");
    return [...left];
  }
  window.i18nMisses = reportMisses;

  /* Профессиональная лексика. Бот (и старые записи в журнале) пишет «кусок», «вышел», «жду» —
     на странице показываем «фрагмент», «опубликован», «ожидание». Только в журнале, ленте решений
     и статусах: названия клипов и тексты ИИ не трогаем. */
  const RW = w => new RegExp("(?<![А-Яа-яЁё])" + w + "(?![А-Яа-яЁё])", "g");
  const RU_PRO = [
    [RW("Кусок"), "Фрагмент"], [RW("кусок"), "фрагмент"], [RW("куска"), "фрагмента"], [RW("куске"), "фрагменте"],
    [RW("куски"), "фрагменты"], [RW("кусков"), "фрагментов"],
    [/Вышел (?=«)/g, "Опубликован "], [RW("выложено"), "опубликовано"],
    [RW("Выкладка"), "Публикация"], [RW("выкладка"), "публикация"], [RW("выкладку"), "публикацию"],
    [RW("выкладки"), "публикации"], [RW("выкладке"), "публикации"], [RW("выкладкой"), "публикацией"],
    [RW("Жду"), "Ожидание"], [/(?<![А-Яа-яЁё])жду:/g, "ожидание:"], [RW("жду"), "ожидаю"],
    [RW("отдыхает"), "на паузе"],
  ];
  const PRO_SCOPE = ".log, .fitem, #sys, #alerts, .alert";
  function ruPro(s) { let o = s; for (const [re_, to] of RU_PRO) o = o.replace(re_, to); return o; }

  /* Заглавная первая буква: подписи, статусы, кнопки, описания, тексты в ленте — всё, что начинает строку.
     Не трогаем ники и хэштеги (в первом слове есть цифра, _, @, #, точка), код и поля ввода. Инлайновый кусок
     в середине фразы («… <b>текст</b> …») тоже остаётся как есть. */
  const NO_CAP = "a.tw, .tw, code, pre, .mono, input, textarea, select, option, [data-nocap]";
  const CAP_ALWAYS = ".chip, .mini, .kind, .btn, .iconbtn, button, th, .fi-t, .thoughts b";
  const INLINE = /^(SPAN|B|EM|STRONG|A|I|SMALL|TIME|U)$/;
  function capFirst(node, t) {
    if (!/^\s*[a-zа-яё]/.test(t)) return t;
    if (/[0-9_@#./]/.test(t.trim().split(/\s/)[0])) return t;
    let el = node.parentElement;
    if (!el || node.previousSibling || el.closest(NO_CAP)) return t;
    while (el && INLINE.test(el.tagName) && !el.matches(CAP_ALWAYS)) {
      if (el.previousSibling) return t;
      el = el.parentElement;
    }
    return t.replace(/^(\s*)([a-zа-яё])/, (m, a, b) => a + b.toUpperCase());
  }

  function translate(node) {
    const current = node.nodeValue;
    // Если приложение само поменяло текст, считаем новое значение оригиналом.
    if (applied.get(node) !== current) original.set(node, current);

    const src = original.get(node) || "";
    if (!src.trim()) return;

    const pe = node.parentElement;
    let target = lang === "en" ? toEn(src) : (pe && pe.closest(PRO_SCOPE) ? ruPro(src) : src);
    target = capFirst(node, target);
    if (node.nodeValue !== target) node.nodeValue = target;
    applied.set(node, target);
  }

  const ATTRS = ["placeholder", "title", "aria-label"];
  function translateAttrs() {
    document.querySelectorAll("[placeholder],[title],[aria-label]").forEach(el => {
      ATTRS.forEach(a => {
        if (!el.hasAttribute(a)) return;
        const k = "i18n" + a.replace("-", "");
        if (el.dataset[k] === undefined) el.dataset[k] = el.getAttribute(a);
        const src = el.dataset[k];
        const val = lang === "en" ? toEn(src) : src;
        if (el.getAttribute(a) !== val) el.setAttribute(a, val);
      });
    });
  }

  function translateAll() {
    if (!document.body) return;
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(n) {
          const p = n.parentNode;
          if (!p || /^(SCRIPT|STYLE|TEXTAREA)$/.test(p.nodeName))
            return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        },
      }
    );
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(translate);
    translateAttrs();
    if (lang === "en" && /[?&]i18n=debug/.test(location.search)) {
      clearTimeout(translateAll._d);
      translateAll._d = setTimeout(reportMisses, 400);
    }

    // Page title
    document.title = lang === "en" && EN["Нарезки"] ? EN["Нарезки"] : "Нарезки";
    document.documentElement.lang = lang === "en" ? "en" : "ru";
  }

  let obs = null;
  function startObserver() {
    if (!obs) {
      obs = new MutationObserver(() => {
        obs.disconnect();
        translateAll();
        obs.observe(document.body, { childList: true, subtree: true, characterData: true });
      });
    }
    obs.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function setLang(value) {
    lang = value === "en" ? "en" : "ru";
    try { localStorage.setItem(LS_KEY, lang); } catch {}
    if (obs) obs.disconnect();
    translateAll();
    startObserver();
    // update selector UI if present
    document.querySelectorAll(".js-lang").forEach(el => { el.value = lang; });
    // числа, деньги и даты рисует само приложение — ему нужен повод перерисоваться
    try { window.dispatchEvent(new CustomEvent("i18n:lang", { detail: lang })); } catch {}
  }

  function init() {
    // селекторов языка может быть несколько (экран пароля и настройки) — все работают одинаково
    document.querySelectorAll(".js-lang").forEach(sel => {
      sel.value = lang;
      sel.addEventListener("change", e => setLang(e.target.value));
    });
    document.documentElement.lang = lang === "en" ? "en" : "ru";
    translateAll();
    startObserver();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // expose for console debugging
  window.__i18n = { setLang, lang: () => lang };
})();
