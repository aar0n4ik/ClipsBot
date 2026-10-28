/* Денежная модель (общая для дашборда и тестов).
 *
 * Клип = один момент стрима, может выйти на 3 площадках. Платим за клип ОДИН раз — по лучшему
 * результату среди площадок, а не за сумму. Выросли просмотры после выплаты — доплачиваем только прирост.
 *
 * Как исключена двойная оплата: для каждого клипа хранится «оплачено до» = максимум лучших просмотров,
 * уже покрытых выплатами. К оплате = max(0, лучший результат сейчас − оплачено до). Любая новая запись
 * поднимает «оплачено до» ровно до того уровня, который она покрыла; те же просмотры второй раз
 * попасть в выплату не могут. Отменённая запись перестаёт учитываться — сумма возвращается в «к выплате».
 *
 * Дубли: один и тот же момент, залитый отдельно (разные clip_id), склеивается в один клип — «склейка» хранится
 * данными (реестр / MONEY_CONFIG → merge), а не в коде. Склеенный клип оплачивается по лучшему результату.
 * При записи выплаты склейка копируется в запись (entry.merged), поэтому её можно убрать из временного списка.
 */
(function (root) {
  "use strict";

  function viewsAt(p, day, dayKey) {
    const h = p.history || {}, keys = Object.keys(h).sort();
    if (!keys.length) return 0;
    if (day < keys[0]) {
      const created = p.create_time ? dayKey(new Date(p.create_time * 1000)) : keys[0];
      return created < keys[0] ? h[keys[0]] : 0;
    }
    let v = 0;
    for (const k of keys) { if (k <= day) v = h[k]; else break; }
    return v;
  }

  const rawKey = p => p.clip_id || `ext:${p.platform}:${p.id}`;

  /* Склейка дублей: списки групп ключей клипов ([[a, b], [c, d, e]]) → функция key → главный ключ.
   * Главный ключ — наименьший в группе, чтобы не зависел от порядка добавления. Незнакомый ключ возвращается как есть. */
  function aliasMap(...lists) {
    const parent = {};
    const find = k => { while (parent[k] !== undefined && parent[k] !== k) k = parent[k]; return k; };
    for (const list of lists) for (const grp of list || []) {
      const ks = (grp || []).filter(Boolean);
      for (const k of ks) if (parent[k] === undefined) parent[k] = k;
      for (let i = 1; i < ks.length; i++) {
        const a = find(ks[0]), b = find(ks[i]);
        if (a !== b) { if (a < b) parent[b] = a; else parent[a] = b; }
      }
    }
    return find;
  }
  const same = k => k;

  function groups(posts, clips, alias) {
    alias = alias || same;
    const byClip = Object.fromEntries((clips || []).map(c => [c.id, c]));
    const g = {};
    for (const p of posts) {
      const key = alias(rawKey(p));
      const x = (g[key] ||= { key, clip: null, posts: [], raw: new Set() });
      x.posts.push(p); x.raw.add(rawKey(p));
    }
    for (const x of Object.values(g)) {
      x.best = x.posts.reduce((a, b) => ((b.views || 0) > (a.views || 0) ? b : a), x.posts[0]);
      x.clip = byClip[x.best.clip_id] || x.posts.map(p => byClip[p.clip_id]).find(Boolean) || null;
      x.merged = x.raw.size > 1 ? [...x.raw].sort() : null;
      x.bestViews = x.best.views || 0;
      x.title = (x.clip && (x.clip.overlay || "")) || x.best.title || "Без названия";
      x.created = Math.min(...x.posts.map(p => p.create_time || 9e12));
      x.thumb = (x.clip && x.clip.thumb) || x.posts.find(p => p.thumb)?.thumb || null;
    }
    return g;
  }

  /* «оплачено до» по каждому клипу из записей реестра (v2 — по клипам; v1 — по роликам TikTok) */
  function paidTo(entries, postToGroup, alias) {
    alias = alias || same;
    const m = {};
    for (const e of entries) {
      if (e.status === "void") continue;
      if (e.lines) {
        for (const l of e.lines) { const k = alias(l.g); m[k] = Math.max(m[k] || 0, l.paid_to || 0); }
      } else if (e.videos) {           // старый формат: прибавки по роликам
        const add = {};
        for (const v of e.videos) {
          const g = alias(postToGroup[v.id] || `ext:tiktok:${v.id}`);
          add[g] = (add[g] || 0) + (v.views || 0);
        }
        for (const [g, v] of Object.entries(add)) m[g] = (m[g] || 0) + v;
      }
    }
    return m;
  }

  function owed(G, paid, rate, excluded) {
    const lines = [], skip = new Set(excluded || []);
    for (const x of Object.values(G)) {
      if (skip.has(x.key)) continue;          // исключённые из расчёта клипы (MONEY_CONFIG → excluded)
      const was = paid[x.key] || 0;
      const inc = Math.max(0, x.bestViews - was);
      if (!inc) continue;
      lines.push({
        g: x.key, merged: x.merged, title: x.title, thumb: x.thumb || null, kind: was > 0 ? "topup" : "new", prev_paid: was, paid_to: x.bestViews, views: inc,
        amount: Math.round(inc * rate / 10) / 100,
        best: { platform: x.best.platform, account: x.best.account, url: x.best.url, views: x.bestViews },
        links: x.posts.map(p => ({ platform: p.platform, account: p.account, url: p.url, views: p.views || 0 })),
      });
    }
    lines.sort((a, b) => b.amount - a.amount);
    return lines;
  }

  function summarize(lines) {
    const s = { new: { views: 0, amount: 0, count: 0 }, topup: { views: 0, amount: 0, count: 0 }, by_platform: {} };
    for (const l of lines) {
      const k = s[l.kind];
      k.views += l.views; k.amount += l.amount; k.count += 1;
      const bp = (s.by_platform[l.best.platform] ||= { new: { amount: 0, count: 0, views: 0 }, topup: { amount: 0, count: 0, views: 0 } });
      bp[l.kind].amount += l.amount; bp[l.kind].count += 1; bp[l.kind].views += l.views;
    }
    for (const k of ["new", "topup"]) s[k].amount = Math.round(s[k].amount * 100) / 100;
    s.total = Math.round((s.new.amount + s.topup.amount) * 100) / 100;
    return s;
  }

  /* Новая запись реестра: фиксирует, какие клипы, по какой площадке, сколько было оплачено и до скольки теперь. */
  function makeEntry(lines, amount, rate, currency, receivedAt, note, merged) {
    const s = summarize(lines);
    const k = s.total ? amount / s.total : 0;
    return {
      v: 2, id: "p" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      amount: Math.round(amount * 100) / 100, currency, rate, received_at: receivedAt, recorded_at: new Date().toISOString(),
      note: note || "", computed_amount: s.total, status: "ok",
      merged: (merged || []).filter(g => g && g.length > 1),
      totals: { new: s.new, topup: s.topup }, by_platform: s.by_platform,
      lines: lines.map(({ merged: _m, ...l }) => ({ ...l, paid_amount: Math.round(l.amount * k * 100) / 100 })),
    };
  }

  /* Прирост «лучшего результата» клипа за период = доход периода (без двойного счёта площадок). */
  function periodGain(G, d1, d2, addDays, dayKey) {
    let total = 0;
    const byPlat = {};
    for (const x of Object.values(G)) {
      const at = d => Math.max(0, ...x.posts.map(p => viewsAt(p, d, dayKey)));
      const gain = Math.max(0, at(d2) - at(addDays(d1, -1)));
      if (!gain) continue;
      total += gain;
      const lead = x.posts.reduce((a, b) => (viewsAt(b, d2, dayKey) > viewsAt(a, d2, dayKey) ? b : a), x.posts[0]);
      const bp = lead.platform;
      byPlat[bp] = (byPlat[bp] || 0) + gain;
    }
    return { total, byPlat };
  }

  /* Удалённые видео: если за клип ничего не выплачено — убираем совсем (и из денег, и из аналитики).
   * Если выплата уже была — оставляем, чтобы история выплат сходилась. */
  function livePosts(posts, entries, alias) {
    alias = alias || same;
    const postToG = {};
    for (const x of Object.values(groups(posts, [], alias))) for (const p of x.posts) postToG[p.id] = x.key;
    const paid = paidTo(entries || [], postToG, alias);
    return posts.filter(p => !p.deleted_at || (paid[alias(rawKey(p))] || 0) > 0);
  }

  /* Клипы, у которых все видео удалены с площадок и ничего не выплачено — не показываем вообще. */
  function hiddenClips(posts, clips, entries, alias) {
    alias = alias || same;
    const postToG = {};
    for (const x of Object.values(groups(posts, [], alias))) for (const p of x.posts) postToG[p.id] = x.key;
    const paid = paidTo(entries || [], postToG, alias);
    const out = new Set();
    for (const c of clips || []) {
      const ps = (posts || []).filter(p => p.clip_id === c.id);
      if (ps.length && ps.every(p => p.deleted_at) && !((paid[alias(c.id)] || 0) > 0)) out.add(c.id);
    }
    return out;
  }

  /* Ручные пометки владельца (реестр → overrides): исключить клип из статистики и выплат, своё название.
   * Ключ пометки — главный ключ группы после склейки. Возвращает новый объект групп. */
  function applyOverrides(G, overrides, alias) {
    alias = alias || same;
    const ov = {};
    for (const [k, v] of Object.entries(overrides || {})) ov[alias(k)] = { ...(ov[alias(k)] || {}), ...v };
    const out = {};
    for (const [k, x] of Object.entries(G)) {
      const o = ov[k] || {};
      if (o.excluded) continue;
      out[k] = o.label ? { ...x, title: o.label, labeled: true } : x;
    }
    return out;
  }

  root.Money = { viewsAt, aliasMap, groups, paidTo, owed, summarize, makeEntry, periodGain, livePosts, hiddenClips, applyOverrides };
  if (typeof module !== "undefined") module.exports = root.Money;
})(typeof window !== "undefined" ? window : globalThis);
