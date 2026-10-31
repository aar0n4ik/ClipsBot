import { Clip, Post, GroupedClip } from "../types";

export function viewsAt(p: Post, day: string, dayKey?: (d: Date) => string): number {
  const h = p.history || {};
  const keys = Object.keys(h).sort();
  if (!keys.length) return day >= dayOf(p, dayKey) ? (p.views || 0) : 0;
  if (day < keys[0]) return 0;
  let v = 0;
  for (const k of keys) {
    if (k <= day) v = h[k];
    else break;
  }
  return day >= keys[keys.length - 1] ? Math.max(v, p.views || 0) : v;
}

export const dayOf = (p: Post, dayKey?: (d: Date) => string): string =>
  p.create_time && dayKey ? dayKey(new Date(p.create_time * 1000)) : "0000-00-00";

export const rawKey = (p: Post): string => p.clip_id || `ext:${p.platform}:${p.id}`;

export function aliasMap(...lists: (string[][] | undefined)[]): (k: string) => string {
  const parent: Record<string, string> = {};
  const find = (k: string): string => {
    while (parent[k] !== undefined && parent[k] !== k) k = parent[k];
    return k;
  };
  for (const list of lists) {
    for (const grp of list || []) {
      const ks = (grp || []).filter(Boolean);
      for (const k of ks) if (parent[k] === undefined) parent[k] = k;
      for (let i = 1; i < ks.length; i++) {
        const a = find(ks[0]), b = find(ks[i]);
        if (a !== b) {
          if (a < b) parent[b] = a;
          else parent[a] = b;
        }
      }
    }
  }
  return find;
}

export const same = (k: string): string => k;

export function trackedFrom(posts: Post[]): string | null {
  let first: string | null = null;
  for (const p of posts) {
    for (const k of Object.keys(p.history || {})) {
      if (first === null || k < first) first = k;
    }
  }
  return first;
}

export function groups(
  posts: Post[],
  clips: Clip[],
  alias: (k: string) => string = same
): Record<string, GroupedClip> {
  const since = trackedFrom(posts);
  const byClip = Object.fromEntries((clips || []).map(c => [c.id, c]));
  const g: Record<string, GroupedClip> = {};

  for (const p of posts) {
    const key = alias(rawKey(p));
    if (!g[key]) {
      g[key] = {
        key,
        clip: null,
        posts: [],
        raw: new Set<string>(),
        best: p,
        merged: null,
        bestViews: 0,
        title: "",
        created: 0,
        thumb: null,
      };
    }
    const x = g[key];
    x.posts.push(p);
    x.raw.add(rawKey(p));
  }

  for (const x of Object.values(g)) {
    x.best = x.posts.reduce((a, b) => ((b.views || 0) > (a.views || 0) ? b : a), x.posts[0]);
    x.clip = byClip[x.best.clip_id || ""] || x.posts.map(p => byClip[p.clip_id || ""]).find(Boolean) || null;
    x.merged = x.raw.size > 1 ? [...x.raw].sort() : null;
    x.bestViews = x.best.views || 0;
    x.title = (x.clip && (x.clip.overlay || "")) || x.best.title || "Без названия";
    x.created = Math.min(...x.posts.map(p => p.create_time || 9e12));
    x.thumb = (x.clip && x.clip.thumb) || x.posts.find(p => p.thumb)?.thumb?.thumb || null;
    x.preexisting =
      !x.clip &&
      !x.posts.some(p => p.clip_id) &&
      !!since &&
      x.posts.every(
        p => p.create_time && new Date(p.create_time * 1000).toISOString().slice(0, 10) < since
      );
  }
  return g;
}

export function periodGain(
  G: Record<string, GroupedClip>,
  d1: string,
  d2: string,
  addDays: (key: string, n: number) => string,
  dayKey: (d: Date) => string
): { total: number; byPlat: Record<string, number> } {
  let total = 0;
  const byPlat: Record<string, number> = {};
  for (const x of Object.values(G)) {
    if (x.preexisting) continue;
    const at = (d: string) => Math.max(0, ...x.posts.map(p => viewsAt(p, d, dayKey)));
    const gain = Math.max(0, at(d2) - at(addDays(d1, -1)));
    if (!gain) continue;
    total += gain;
    const lead = x.posts.reduce(
      (a, b) => (viewsAt(b, d2, dayKey) > viewsAt(a, d2, dayKey) ? b : a),
      x.posts[0]
    );
    const bp = lead.platform;
    byPlat[bp] = (byPlat[bp] || 0) + gain;
  }
  return { total, byPlat };
}

export function applyOverrides(
  G: Record<string, GroupedClip>,
  overrides: Record<string, { excluded?: boolean; label?: string }>,
  alias: (k: string) => string = same
): Record<string, GroupedClip> {
  const ov: Record<string, { excluded?: boolean; label?: string }> = {};
  for (const [k, v] of Object.entries(overrides || {})) {
    ov[alias(k)] = { ...(ov[alias(k)] || {}), ...v };
  }
  const out: Record<string, GroupedClip> = {};
  for (const [k, x] of Object.entries(G)) {
    const o = ov[k] || {};
    if (o.excluded) continue;
    out[k] = o.label ? { ...x, title: o.label, labeled: true } : x;
  }
  return out;
}
