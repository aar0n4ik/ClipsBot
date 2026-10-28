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
  ["Вышел 5 мин назад, просмотры соберу через час", "Posted 5 min ago, views in an hour"],
  ["Запись куска 14:00", "Recording segment 14:00"],
].forEach(([ru, en]) => ok(toEn(ru) === en, `${JSON.stringify(ru)} -> ${JSON.stringify(toEn(ru))}, ожидалось ${JSON.stringify(en)}`));

/* 2 · ни одна строка интерфейса не остаётся русской */
const html = fs.readFileSync(path.join(ROOT, "docs/index.html"), "utf8");
const cand = new Set();
for (const m of html.matchAll(/"([^"\\\n]{2,90})"/g)) cand.add(m[1]);
for (const m of html.matchAll(/'([^'\\\n]{2,90})'/g)) cand.add(m[1]);
for (const m of html.matchAll(/>([^<>${}]{2,90})</g)) cand.add(m[1]);
const ui = [...cand].map(x => x.trim()).filter(x => CYR.test(x) && !/[<>{}`]|\$\{/.test(x));
const left = ui.filter(x => CYR.test(toEn(x))).sort();
ok(ui.length > 300, `строк для проверки подозрительно мало (${ui.length}) — сломался разбор index.html`);
if (left.length) {
  console.error(`  FAIL не переведено ${left.length} из ${ui.length}:`);
  left.forEach(x => console.error("        " + JSON.stringify(x)));
  failed++;
}

if (failed) { console.error(`\ntest_i18n: ${failed} проверок упало`); process.exit(1); }
console.log(`test_i18n: ok — ${ui.length} строк интерфейса, русского в английском режиме не осталось`);
