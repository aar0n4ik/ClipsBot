/* Сцена «Выкладка» должна показывать ТО, что уходит прямо сейчас, и отпускать этап через 10 минут.
   Раньше: любой незакрытый статус (включая retry, который висит сутками) держал этап «Выкладка»
   навсегда, а клип для сцены выбирался по дате создания — то есть чужой. */
const fs = require("fs"), path = require("path");
const html = fs.readFileSync(path.join(__dirname, "..", "docs/index.html"), "utf8");

// вырезаем проверяемые функции из страницы и исполняем их изолированно
const need = ["const UPLOAD_WINDOW_MS", "const fresh =", "function uploadStartedAt", "function uploadingClip", "function uploadBusy"];
let code = "";
for (const n of need) {
  const i = html.indexOf(n);
  if (i < 0) { console.error("FAIL: не найдено в index.html: " + n); process.exit(1); }
  let j = html.indexOf("\n", i), depth = (html.slice(i, j).match(/\{/g) || []).length - (html.slice(i, j).match(/\}/g) || []).length;
  while (depth > 0) { const k = html.indexOf("\n", j + 1); const line = html.slice(j, k);
    depth += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length; j = k; }
  code += html.slice(i, j) + "\n";
}
let D;
const postingNow = new Map();
eval(code.replace(/postingNow\.get\(c\.id\) \|\| 0/, "postingNow.get(c.id) || 0"));

let failed = 0;
const ok = (c, m) => { if (!c) { console.error("  FAIL " + m); failed++; } };
const iso = msAgo => new Date(Date.now() - msAgo).toISOString();

/* 1 · зависший retry больше не держит этап «Выкладка» */
D = { clips: [{ id: "old", posts: { tiktok: { status: "retry", started_at: iso(20 * 3600e3) } } }] };
ok(!uploadBusy(), "retry 20 часов назад всё ещё считается активной заливкой");

/* 2 · идущая заливка — считается */
D = { clips: [{ id: "now", posts: { tiktok: { status: "uploading", started_at: iso(60e3) } } }] };
ok(uploadBusy(), "заливка минуту назад не распознана");

/* 3 · заливка старше 10 минут этап отпускает */
D = { clips: [{ id: "stale", posts: { tiktok: { status: "uploading", started_at: iso(11 * 60e3) } } }] };
ok(!uploadBusy(), "заливка 11 минут назад всё ещё держит этап");

/* 4 · «выложить сейчас» на СТАРОМ клипе показывает именно его, а не свежесозданный */
D = { clips: [
  { id: "fresh_clip", created_at: iso(60e3), posts: {} },
  { id: "chosen", created_at: iso(30 * 3600e3), force_post: iso(30e3), posts: {} },
] };
ok(uploadBusy(), "force_post не распознан как идущая заливка");
ok(uploadingClip() && uploadingClip().id === "chosen",
   "сцена показывает " + JSON.stringify(uploadingClip() && uploadingClip().id) + " вместо клипа, который заливают");

/* 5 · старое нажатие «выложить сейчас» не висит вечно */
D = { clips: [{ id: "c", force_post: iso(3 * 3600e3), posts: {} }] };
ok(!uploadBusy(), "force_post трёхчасовой давности всё ещё держит этап");

if (failed) { console.error(`\ntest_scene: ${failed} проверок упало`); process.exit(1); }
console.log("test_scene: ok — этап «Выкладка» живёт 10 минут и показывает нужный клип");
