// node tests/test_money.js — денежная модель: лучший результат, доплаты, без двойной оплаты
const M = require("../docs/money.js");
const assert = (c, m) => { if (!c) { console.error("❌", m); process.exit(1); } };
const dayKey = d => d.toISOString().slice(0, 10);
const addDays = (k, n) => { const d = new Date(k + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const P = (id, platform, clip, views, hist) => ({ id, platform, account: platform + "_main", clip_id: clip, views, url: "u/" + id, history: hist || {} });

let posts = [P("t1", "tiktok", "c1", 5000), P("y1", "youtube", "c1", 3000), P("t2", "tiktok", "c2", 1200), P("i3", "instagram", null, 800)];
let G = M.groups(posts, [{ id: "c1", overlay: "Клип 1" }, { id: "c2", overlay: "Клип 2" }]);
let lines = M.owed(G, M.paidTo([], {}), 1);
let s = M.summarize(lines);
assert(s.new.count === 3 && s.topup.count === 0, "3 новых клипа");
assert(Math.abs(s.total - (5 + 1.2 + 0.8)) < 1e-9, "платим по лучшей площадке, а не по сумме: " + s.total);
const e1 = M.makeEntry(lines, s.total, 1, "USD", "2026-10-10T10:00:00Z", "PayPal");
// клип 1 вырос: YouTube обогнал TikTok
posts = [P("t1", "tiktok", "c1", 6000), P("y1", "youtube", "c1", 9000), P("t2", "tiktok", "c2", 1200), P("i3", "instagram", null, 800), P("t4", "tiktok", "c4", 2000)];
G = M.groups(posts, [{ id: "c1", overlay: "Клип 1" }]);
lines = M.owed(G, M.paidTo([e1], {}), 1);
s = M.summarize(lines);
const top = lines.find(l => l.g === "c1");
assert(top && top.kind === "topup" && top.views === 4000 && top.best.platform === "youtube", "доплата = только прирост лучшего (9000−5000)");
assert(!lines.find(l => l.g === "c2"), "без роста — не платим повторно");
assert(s.new.count === 1 && s.new.amount === 2 && s.topup.amount === 4, "новые и доплаты раздельно");
const e2 = M.makeEntry(lines, 6, 1, "USD", "2026-10-15T10:00:00Z", "");
assert(M.owed(G, M.paidTo([e1, e2], {}), 1).length === 0, "после выплаты долг 0 — двойная оплата невозможна");
e2.status = "void";
assert(M.summarize(M.owed(G, M.paidTo([e1, e2], {}), 1)).total === 6, "отмена записи возвращает сумму");
// старый формат реестра (v1)
const v1 = { amount: 5, videos: [{ id: "t1", views: 5000 }] };
assert(M.paidTo([v1], { t1: "c1" }).c1 === 5000, "совместимость со старым реестром");
// доход периода по лучшему результату
const pp = [P("a", "tiktok", "c9", 0, { "2026-10-01": 100, "2026-10-02": 1000 }), P("b", "youtube", "c9", 0, { "2026-10-01": 50, "2026-10-02": 1500 })];
const g = M.periodGain(M.groups(pp, []), "2026-10-02", "2026-10-02", addDays, dayKey);
assert(g.total === 1400 && g.byPlat.youtube === 1400, "доход дня = прирост максимума (1500−100): " + JSON.stringify(g));
// исключение клипа из расчёта (удалённый клип)
const exG = M.groups([P("q1", "tiktok", "cX", 4000), P("q2", "tiktok", "cY", 1000)], []);
assert(M.owed(exG, {}, 1, ["cX"]).every(l => l.g !== "cX") && M.owed(exG, {}, 1, ["cX"]).length === 1, "исключённый клип не попадает в расчёт");
assert(M.owed(exG, {}, 1).length === 2, "без исключений всё на месте");
// удалённые видео: без выплаты — убираем, с выплатой — оставляем
const dp = [P("d1", "tiktok", "cA", 3000), P("d2", "tiktok", "cB", 2000), P("d3", "tiktok", "cC", 900)];
dp[1].deleted_at = "2026-10-20T00:00:00Z";      // удалён, не выплачен
dp[2].deleted_at = "2026-10-20T00:00:00Z";      // удалён, но выплачен
const paidC = M.makeEntry(M.owed(M.groups([dp[2]], []), {}, 1), 0.9, 1, "USD", "2026-10-21T10:00:00Z", "");
const lp = M.livePosts(dp, [paidC]);
assert(!lp.find(p => p.id === "d2"), "удалённый невыплаченный убран");
assert(lp.find(p => p.id === "d3"), "удалённый выплаченный остался");
assert(lp.find(p => p.id === "d1"), "живой остался");
// дубли: один момент залит отдельно под разными clip_id — склеиваем, платим по лучшему, без двойной оплаты
const dupPosts = [P("a1", "tiktok", "cA", 3000), P("a2", "tiktok", "cB", 5000), P("a3", "youtube", "cC", 4000), P("z1", "tiktok", "cZ", 700)];
const dupClips = [{ id: "cA", overlay: "Как заработать в деревне?" }, { id: "cB", overlay: "Школьник просит совет" }, { id: "cC", overlay: "Школьник просит совет (Shorts)" }];
let al = M.aliasMap([["cB", "cA"]], [["cC", "cB"]]);
assert(al("cA") === "cA" && al("cB") === "cA" && al("cC") === "cA" && al("cZ") === "cZ", "склейка транзитивна, главный ключ — наименьший");
let dG = M.groups(dupPosts, dupClips, al);
assert(Object.keys(dG).length === 2, "3 дубля → 1 клип + 1 обычный");
let dl = M.owed(dG, M.paidTo([], {}, al), 1);
assert(Math.abs(M.summarize(dl).total - (5 + 0.7)) < 1e-9, "дубли считаются по лучшему (5000), а не по сумме");
assert(dl.find(l => l.g === "cA").title === "Школьник просит совет", "название — от клипа с лучшим результатом");
// без склейки — старое поведение (двойной счёт), т.е. склейка реально что-то меняет
assert(M.summarize(M.owed(M.groups(dupPosts, dupClips), {}, 1)).total > 11, "без склейки платили бы за каждый отдельно");
// выплата по склеенному, потом склейку убираем из временного списка — она живёт в записи
const dE = M.makeEntry(dl, 5.7, 1, "USD", "2026-10-26T10:00:00Z", "", [["cA", "cB", "cC"]]);
assert(dE.merged.length === 1 && !("merged" in dE.lines[0]), "склейка скопирована в запись выплаты");
const al2 = M.aliasMap([], dE.merged);
const dG2 = M.groups(dupPosts, dupClips, al2);
assert(M.owed(dG2, M.paidTo([dE], {}, al2), 1).length === 0, "после выплаты и без временного списка двойной оплаты нет");
// дубль вырос после выплаты — платим только прирост лучшего
dupPosts[2].views = 6500;
assert(M.owed(M.groups(dupPosts, dupClips, al2), M.paidTo([dE], {}, al2), 1)[0].views === 1500, "доплата только за прирост лучшего из дублей");
// выплата была ДО склейки по отдельности: берём максимум, а не сумму
const old1 = M.makeEntry(M.owed(M.groups([P("o1", "tiktok", "cA", 3000)], []), {}, 1), 3, 1, "USD", "2026-10-01T10:00:00Z", "");
const old2 = M.makeEntry(M.owed(M.groups([P("o2", "tiktok", "cB", 5000)], []), {}, 1), 5, 1, "USD", "2026-10-02T10:00:00Z", "");
assert(M.paidTo([old1, old2], {}, M.aliasMap([["cA", "cB"]])).cA === 5000, "уже оплаченное до склейки не складывается");
// удалённые видео при склейке
const dd = [P("e1", "tiktok", "cA", 3000), P("e2", "tiktok", "cB", 5000)]; dd.forEach(x => x.deleted_at = "2026-10-20T00:00:00Z");
assert(M.livePosts(dd, [], al).length === 0, "удалённые склеенные без выплаты убираются");
// ручные пометки: исключить и переименовать — работают и для склеенных групп
const ovG = M.applyOverrides(M.groups(dupPosts, dupClips, al), { cB: { excluded: true }, cZ: { label: "Мой клип" } }, al);
assert(!ovG.cA && ovG.cZ.title === "Мой клип", "исключение по любому ключу склеенной группы + своё название");
assert(M.owed(ovG, {}, 1).length === 1, "исключённый не попадает в выплату");
// частичная выплата: только выбранные клипы закрываются, остальное остаётся к выплате
const pG = M.groups([P("p1", "tiktok", "c1", 1000), P("p2", "tiktok", "c2", 2000)], []);
const pl = M.owed(pG, {}, 1);
const part = M.makeEntry(pl.filter(l => l.g === "c2"), 2, 1, "USD", "2026-10-26T10:00:00Z", "");
const rest = M.owed(pG, M.paidTo([part], {}), 1);
assert(rest.length === 1 && rest[0].g === "c1", "частичная выплата закрывает только выбранное");
// корректировка без клипов не трогает «оплачено до»
assert(Object.keys(M.paidTo([{ v: 2, kind: "adjust", amount: -3, lines: [] }], {})).length === 0, "корректировка не закрывает клипы");
console.log("✅ money: все проверки пройдены");

/* Деньги сходятся: «к выплате» и «доход за всё время» считают одно и то же.
   Старые ролики, лежавшие на аккаунте до бота, не попадают ни туда, ни туда. */
{
  const h = (o) => o;
  const mk = (id, plat, clip, views, hist, created) => ({ id, platform: plat, clip_id: clip, views, history: h(hist), create_time: created });
  const ts = d => Math.floor(new Date(d + "T12:00:00Z").getTime() / 1000);
  const posts = [
    mk("v1", "youtube", "c1", 1000, { "2026-10-21": 400, "2026-10-23": 1000 }, ts("2026-10-21")),
    mk("v2", "tiktok", "c1", 300, { "2026-10-21": 100, "2026-10-23": 300 }, ts("2026-10-21")),
    // клип вышел вчера, первый снимок — только сегодня: весь результат должен попасть в доход
    mk("v3", "youtube", "c2", 700, { "2026-10-23": 700 }, ts("2026-10-22")),
    // чужой ролик, который лежал на канале задолго до бота
    mk("v4", "youtube", null, 5000, { "2026-10-21": 4990, "2026-10-23": 5000 }, ts("2026-05-20")),
  ];
  const G2 = M.groups(posts, [{ id: "c1", overlay: "Клип 1" }, { id: "c2", overlay: "Клип 2" }]);
  const owedSum = M.summarize(M.owed(G2, M.paidTo([], {}), 1)).total;
  const gain = M.periodGain(G2, "2026-10-01", "2026-10-23", addDays, dayKey).total;
  assert(gain === 1700, "доход за всё время = 1000 + 700, старое чужое видео не в счёт (получено " + gain + ")");
  assert(Math.abs(owedSum - gain / 1000) < 1e-9, "«к выплате» и «доход за всё время» сходятся (" + owedSum + " vs " + gain / 1000 + ")");
  assert(M.owed(G2, M.paidTo([], {}), 1).every(l => l.g !== "ext:youtube:v4"), "старое чужое видео не в выплатах");
  const byPlat = M.periodGain(G2, "2026-10-01", "2026-10-23", addDays, dayKey).byPlat;
  assert(byPlat.youtube === 1700 && !byPlat.tiktok, "доход засчитан по лучшей площадке клипа");
}
console.log("✅ money: деньги сходятся");
