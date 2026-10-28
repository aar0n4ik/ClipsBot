/* Английский режим: строки, которые дашборд собирает на ходу, не остаются русскими.
   Содержимое клипов (заголовки в кавычках) — не интерфейс, его не переводим. */
const fs = require("fs");
const path = require("path");
let src = fs.readFileSync(path.join(__dirname, "..", "docs", "i18n.js"), "utf8")
  .replace("window.__i18n = { setLang, lang: () => lang };", "window.__i18n = { setLang, lang: () => lang, toEn };");

global.MutationObserver = class { observe() {} disconnect() {} };
global.NodeFilter = { SHOW_TEXT: 4 };
global.location = { search: "" };
const win = { addEventListener() {}, dispatchEvent() {}, location: global.location };
global.window = win;
global.navigator = { languages: ["en"] };
global.localStorage = { getItem: () => "en", setItem() {} };
global.document = { documentElement: { lang: "" }, addEventListener() {}, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => ({ style: {}, setAttribute() {}, appendChild() {}, classList: { add() {} } }),
  body: {}, readyState: "complete", createTreeWalker: () => ({ nextNode: () => null }) };
global.addEventListener = () => {};
global.CustomEvent = class { constructor() {} };
eval(src);

const t = win.__i18n.toEn;
const cases = [
  "Лимит сегодня: вышло 3 из 5",
  "Лимит сегодня: вышло 3 из 5 · осталось 2, следующий в 20:07",
  "Лимит сегодня: вышло 5 из 5 · лимит на сегодня исчерпан",
  "Лимит на сегодня исчерпан",
  "Следующий в 20:07",
  "Проверка в 21:07",
  "следующим в очереди",
  "выложу при ближайшем запуске",
  "8 499 просмотров",
  "8 499 просмотров · 1 в черновиках",
  "Слишком много запросов. Бот подождёт и повторит сам.",
  "Временный сбой на стороне площадки. Бот повторит попытку сам.",
  "Суточный лимит публикаций площадки почти исчерпан. Продолжим завтра.",
  "Монтируется: «Вейп хуже сигарет»",
  "Последний собранный клип: «Тесла сама затормозила»",
];
let bad = 0;
for (const x of cases) {
  const out = String(t(x)).replace(/[“"«][^”"»]*[”"»]/g, "");   // заголовок клипа — это контент, а не интерфейс
  if (/[А-Яа-яЁё]/.test(out)) { bad++; console.log("❌ осталось по-русски:", JSON.stringify(x), "→", JSON.stringify(t(x))); }
  if (/\.\./.test(String(t(x)))) { bad++; console.log("❌ двойная точка:", JSON.stringify(t(x))); }
}
if (bad) { console.log("❌ i18n:", bad, "проблем"); process.exit(1); }
console.log("✅ i18n: динамические строки переводятся");
