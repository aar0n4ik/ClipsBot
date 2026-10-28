/* Покрытие перевода дашборда. Словарь переводит строку целиком, шаблоны RX — составные фразы
   с числом внутри. Любая новая русская строка в index.html без перевода роняет этот тест:
   раньше такие строки просто оставались русскими посреди английского интерфейса. */
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..");

global.localStorage = { getItem: () => "en", setItem: () => {} };
global.location = { search: "" };
global.NodeFilter = { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 };
global.document = {
  body: {}, title: "", documentElement: {},
  querySelectorAll: () => [], addEventListener: () => {},
  createTreeWalker: () => ({ nextNode: () => null }),
  getElementById: () => null, readyState: "complete",
};
global.MutationObserver = function () { return { observe() {}, disconnect() {} }; };
global.window = {};

const src = fs.readFileSync(path.join(ROOT, "docs/i18n.js"), "utf8")
  .replace(/\}\)\(\);?\s*$/, "  globalThis.__toEn = toEn;\n})();");
eval(src);
const toEn = globalThis.__toEn;
const CYR = /[А-Яа-яЁё]/;

let failed = 0;
function ok(cond, msg) { if (!cond) { console.error("  FAIL " + msg); failed++; } }

/* 1 · составные фразы переводятся целиком, без смеси языков */
[
  ["клипов 3 из 7", "clips 3 of 7"],
  ["В эфире 2 ч 15 мин", "Live 2 h 15 min"],
  ["Оценка по видео 8 из 10", "Video score 8 of 10"],
  ["Вышел 5 мин назад, просмотры соберу через час", "Posted 5 min ago, stats in an hour"],
  ["Запись куска 14:00", "Recording segment 14:00"],
].forEach(([ru, en]) => ok(toEn(ru) === en, `${JSON.stringify(ru)} -> ${JSON.stringify(toEn(ru))}, ожидалось ${JSON.stringify(en)}`));

/* 1b · составная строка переводится по кускам, а не превращается в смесь языков */
[
  ["Эфир идёт 3 ч 22 мин — «Delivering around LA in a Tesla». ИИ смотрит видео финалиста 2/4 на куске 2:00:00–4:00:00.",
   "Live now 3 h 22 min — “Delivering around LA in a Tesla”. The AI watches finalist 2/4 on segment 2:00:00–4:00:00."],
  ["Можно выводить — порог $20.00 набран.", "Ready to withdraw — the $20.00 threshold is reached."],
  ["148 103 просм.", "148 103 views"],
].forEach(([ru, en]) => ok(toEn(ru) === en, `${JSON.stringify(ru)} -> ${JSON.stringify(toEn(ru))}, ожидалось ${JSON.stringify(en)}`));

/* 1c · чего не знаем — оставляем по-русски целиком; смесь языков недопустима */
[
  "Стример спорит с охранником у входа, тот не пускает с заказом",
  "Какая-то совершенно новая строка от бота про площадки и клипы",
].forEach(ru => {
  const out = toEn(ru);
  ok(!/[A-Za-z]/.test(out.replace(/[^А-Яа-яЁёA-Za-z]/g, "")) || !CYR.test(out),
    `смесь языков: ${JSON.stringify(ru)} -> ${JSON.stringify(out)}`);
});

/* 1d · строки, которые приходят от бота и в HTML не лежат */
[
  ["Последний эфир был 12 ч назад. Проверка раз в 10 минут.", "Last stream was 12 h ago. Checking every 10 minutes."],
  ["Публикация: выложено: tiktok, youtube, instagram", "Publishing: posted to tiktok, youtube, instagram"],
  ["Кусок 4:58:00–5:19:35: кандидатов 3, по тексту 0, по видео 0, клипов 0", "Segment 4:58:00–5:19:35: 3 candidates, 0 passed text, 0 passed video, 0 clips"],
  ["владелец нажал «Выложить сейчас»", "owner pressed “Post now”"],
  ["владелец", "owner"],
  ["после прошлого релиза прошло 60 мин из 90", "60 of 90 min have passed since the last release"],
  ["следующий слот в 19:07", "next slot at 19:07"],
  ["ночь аудитории (2:00 по Europe/Moscow)", "audience night (2:00 Europe/Moscow)"],
  ["жду instagram (отдыхает до 18:00) — клип выходит только на всех площадках сразу", "waiting for instagram (resting until 18:00) — a clip goes out only on all platforms at once"],
].forEach(([ru, en]) => ok(toEn(ru) === en, `${JSON.stringify(ru)} -> ${JSON.stringify(toEn(ru))}, ожидалось ${JSON.stringify(en)}`));

/* 2 · ни одна строка интерфейса не остаётся русской */
const html = fs.readFileSync(path.join(ROOT, "docs/index.html"), "utf8");
const cand = new Set();
for (const m of html.matchAll(/"([^"\\\n]{2,400})"/g)) cand.add(m[1]);
for (const m of html.matchAll(/'([^'\\\n]{2,400})'/g)) cand.add(m[1]);
for (const m of html.matchAll(/>([^<>${}]{2,400})</g)) cand.add(m[1]);
for (const m of html.matchAll(/(?:placeholder|title|aria-label)="([^"]{2,400})"/g)) cand.add(m[1]);
const ui = [...cand].map(x => x.trim()).filter(x => CYR.test(x) && !/[<>{}`]|\$\{/.test(x));
/* «Русский» в списке языков остаётся по-русски в обоих режимах — так принято в переключателях. */
/* Ключи словаря этапов (STAGE) — это то, как бот пишет этап; на экран они попадают только через stageName(). */
const KEEP_RU = new Set(["Русский", "текст", "тексты", "видео", "критик", "отбор", "дубль", "звук", "монтаж"]);
const left = ui.filter(x => !KEEP_RU.has(x) && CYR.test(toEn(x))).sort();
ok(ui.length > 300, `строк для проверки подозрительно мало (${ui.length}) — сломался разбор index.html`);
if (left.length) {
  console.error(`  FAIL не переведено ${left.length} из ${ui.length}:`);
  left.forEach(x => console.error("        " + JSON.stringify(x)));
  failed++;
}

if (failed) { console.error(`\ntest_i18n: ${failed} проверок упало`); process.exit(1); }
console.log(`test_i18n: ok — ${ui.length} строк интерфейса, русского в английском режиме не осталось`);
