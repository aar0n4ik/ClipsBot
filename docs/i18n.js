/* ClipsBot i18n — RU / EN language switcher
   Saves choice in localStorage under key "clips:lang"
   Injects translated text via MutationObserver so dynamic content is covered.
*/
(function () {
  "use strict";
  const LS_KEY = "clips:lang";
  let lang = (() => {
    try {
      const saved = localStorage.getItem(LS_KEY);
      if (saved === "en" || saved === "ru") return saved;
      return "ru"; // сайт русский по умолчанию, выбор пользователя запоминается
    } catch { return "ru"; }
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
    "Свой период": "Custom",

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
    "Где вышел (просмотры)": "Where posted (views)",
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
  };

  /* ─── Translation engine ──────────────────────────────────────────── */
  const original = new WeakMap(); // textNode → original Russian text
  const applied  = new WeakMap(); // textNode → last value we wrote

  // Для частичных совпадений берём только длинные ключи (короткие вроде «из», «Все» ломают текст), сначала самые длинные.
  const PARTIAL = Object.keys(EN).filter(k => k.length >= 6).sort((x, y) => y.length - x.length);

  function toEn(src) {
    const trimmed = src.trim();
    const full = EN[trimmed];
    if (full !== undefined) return src.replace(trimmed, () => full);
    let out = src;
    for (const ru of PARTIAL) if (out.includes(ru)) out = out.split(ru).join(EN[ru]);
    return out;
  }

  function translate(node) {
    const current = node.nodeValue;
    // Если приложение само поменяло текст, считаем новое значение оригиналом.
    if (applied.get(node) !== current) original.set(node, current);

    const src = original.get(node) || "";
    if (!src.trim()) return;

    const target = lang === "en" ? toEn(src) : src;
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
    const sel = document.getElementById("langSelect");
    if (sel) sel.value = lang;
  }

  function init() {
    const sel = document.getElementById("langSelect");
    if (sel) {
      sel.value = lang;
      sel.addEventListener("change", e => setLang(e.target.value));
    }
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
