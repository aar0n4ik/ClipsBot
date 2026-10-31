import { AppData, Clip, Post, Platform, SubscriptionPlan, StreamerChannel, InvoiceRecord } from "../types";

export function createDemoData(): AppData {
  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const now = Date.now();
  const day = 864e5;
  const TZ = "America/Chicago";
  const dayKey = (d: Date) =>
    new Intl.DateTimeFormat("en-CA", {
      timeZone: TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(d);

  const hooks: [string, string][] = [
    ["Штраф $200 за 5 минут парковки", "money"],
    ["Клиентка оставила $100 чаевых", "emotional"],
    ["Автопилот повёз не туда", "road"],
    ["Школьник просит совет", "chat"],
    ["Ты вообще откуда, бро?", "america"],
    ["Собака не отдавала пакет", "funny"],
    ["Ресторан забыл ползаказа", "customer"],
    ["Бездомные живут лучше нас?", "america"],
  ];

  const channels: StreamerChannel[] = [
    {
      id: "ch_albert",
      twitchLogin: "albert1million",
      displayName: "albert1million",
      status: "live",
      viewers: 1840,
      currentStreamTitle: "Доставка по ЛА на Тесле",
      clipsCount: 84,
      platforms: { tiktok: true, youtube: true, instagram: true },
    },
    {
      id: "ch_buster",
      twitchLogin: "buster",
      displayName: "Buster",
      status: "offline",
      viewers: 0,
      clipsCount: 45,
      platforms: { tiktok: true, youtube: true, instagram: false },
    },
    {
      id: "ch_evelone",
      twitchLogin: "evelone192",
      displayName: "Evelone192",
      status: "live",
      viewers: 3250,
      currentStreamTitle: "Мафия со стримерами / Ночной стрим",
      clipsCount: 68,
      platforms: { tiktok: true, youtube: true, instagram: true },
    },
  ];

  const plans: SubscriptionPlan[] = [
    {
      id: "starter",
      name: "Starter",
      priceMonthly: 29,
      priceAnnual: 24,
      maxChannels: 1,
      clipsPerDay: 2,
      maxClipsPerMonth: 60,
      quality: "1080p 30fps",
      features: [
        "1 Twitch стримерский канал",
        "До 2 клипов в день (60 / месяц)",
        "Автовыкладка в TikTok и YouTube Shorts",
        "Умная обрезка пауз и тишины",
        "Стандартные субтитры с обводкой",
      ],
    },
    {
      id: "pro",
      name: "Pro Streamer",
      badge: "Популярный",
      priceMonthly: 79,
      priceAnnual: 64,
      maxChannels: 2,
      clipsPerDay: 5,
      maxClipsPerMonth: 150,
      quality: "1080p 60fps HQ",
      features: [
        "До 2 Twitch каналов",
        "До 5 клипов в день (150 / месяц)",
        "Синхронно в TikTok, Shorts и Reels",
        "ИИ-Режиссёр Gemini 4 (проверка на лаги)",
        "Генератор цепляющих хуков и 1-го коммента",
        "Приоритетный рендеринг без очереди",
        "Поддержка 24/7",
      ],
    },
    {
      id: "agency",
      name: "Agency & Studio",
      priceMonthly: 199,
      priceAnnual: 159,
      maxChannels: 5,
      clipsPerDay: 15,
      maxClipsPerMonth: 400,
      quality: "1080p / 4K Source Parsing",
      features: [
        "До 5 стримеров / каналов",
        "До 15 клипов в день (400 / месяц)",
        "Все платформы + черновики",
        "Кастомные шаблоны оверлея и шрифты",
        "Выделенный серверный инстанс",
        "API вебхуки и автосинхронизация",
        "Персональный менеджер",
      ],
    },
  ];

  const subscription = {
    planId: "pro" as const,
    status: "active" as const,
    billingCycle: "monthly" as const,
    renewalDate: new Date(Date.now() + 18 * 864e5).toISOString().slice(0, 10),
    clipsUsedThisMonth: 84,
    clipsQuotaThisMonth: 150,
    streamsProcessedHours: 52,
    paymentMethod: "Visa •••• 4242",
  };

  const invoices: InvoiceRecord[] = [
    {
      id: "inv_2026_10",
      date: new Date(Date.now() - 12 * 864e5).toISOString().slice(0, 10),
      planName: "Pro Streamer (Monthly)",
      amount: 79,
      status: "paid",
    },
    {
      id: "inv_2026_09",
      date: new Date(Date.now() - 42 * 864e5).toISOString().slice(0, 10),
      planName: "Pro Streamer (Monthly)",
      amount: 79,
      status: "paid",
    },
    {
      id: "inv_2026_08",
      date: new Date(Date.now() - 72 * 864e5).toISOString().slice(0, 10),
      planName: "Starter Plan (Monthly)",
      amount: 29,
      status: "paid",
    },
  ];

  const accounts = [
    { id: "tt_main", name: "TikTok", platform: "tiktok" as Platform },
    { id: "yt_main", name: "YouTube Shorts", platform: "youtube" as Platform },
    { id: "ig_main", name: "Instagram Reels", platform: "instagram" as Platform },
  ];

  const posts: Post[] = [];
  const clips: Clip[] = [];

  for (let i = 0; i < 30; i++) {
    const age = i * 0.5 + rnd() * 0.3;
    const created = now - age * day;
    const [title, cat] = hooks[i % hooks.length];
    const id = "c" + i;
    const score = 7 + Math.round(rnd() * 2);
    const viral = rnd() < 0.1 ? 15 : rnd() < 0.3 ? 3 : 1;
    const targets: Record<string, any> = {};
    const cposts: Record<string, any> = {};

    const platforms: [Platform, number][] = [
      ["tiktok", 1],
      ["youtube", 0.8 + rnd()],
      ["instagram", 0.4 + rnd() * 0.5],
    ];

    for (const [p, mult] of platforms) {
      const pa = age;
      const final = Math.round((700 + rnd() * 4000) * viral * mult * (score - 5) / 2);
      const history: Record<string, number> = {};
      for (let d = 0; d <= Math.ceil(pa) + 1; d++) {
        const t = created + d * day;
        if (t > now + day) break;
        history[dayKey(new Date(Math.min(t, now)))] = Math.round(
          final * (1 - Math.exp(-Math.min(pa, d + 0.5) * 1.3))
        );
      }
      posts.push({
        id: p + i,
        platform: p,
        account: p.slice(0, 2) + "_main",
        title,
        create_time: Math.floor(created / 1000),
        url: "#",
        views: Object.values(history).pop() || 0,
        history,
        clip_id: id,
      });
      targets[p] = { hook: title, status: "used" };
      cposts[p] = {
        status: p === "tiktok" && i === 0 ? "inbox" : "posted",
        posted_at: new Date(created).toISOString(),
        url: "#",
        reason: "лучший час по плану",
        by: "ИИ-продюсер",
      };
    }

    clips.push({
      id,
      overlay: title,
      category: cat,
      score,
      duration: Math.round(14 + rnd() * 26),
      status: i === 0 ? "inbox" : "posted",
      created_at: new Date(created - 36e5).toISOString(),
      vod_id: "1",
      vod_time: 1200 + i * 180,
      targets,
      posts: cposts,
      what: "Стример реагирует на ситуацию на заказе",
      why: "понятная ситуация, есть развязка",
      first_comment: "А как бы вы поступили в такой ситуации? Пишите в комменты 👇",
      brain: {
        text: { score: score - 1, why: "понятная ситуация, есть развязка" },
        video: { score, moment: "реакция на сумму", technical: { lag: 0 } },
        critic: { ok: true },
        cuts: 2,
        trimmed_s: 3.4,
      },
    });
  }

  // Ready clips waiting in queue
  const readyList: [string, string, number][] = [
    ["Чат заказал пиццу… клиенту", "chat", 9],
    ["Охрана не пустила в лифт", "customer", 8],
    ["Обед в Санта-Монике за $40", "money", 7],
  ];

  readyList.forEach(([ov, cat, sc], k) => {
    clips.push({
      id: "q" + k,
      overlay: ov,
      category: cat,
      score: sc,
      duration: 18 + k * 4,
      status: "ready",
      created_at: new Date(now - (k + 1) * 50 * 6e4).toISOString(),
      vod_id: "1",
      vod_time: 2400 + k * 300,
      what: "Стример спорит с охранником у входа, тот не пускает с заказом",
      why: "конфликт с понятной ставкой",
      first_comment: "Курьерские будни в Калифорнии 📦 Что думаете?",
      brain: {
        text: { score: sc - 1, why: "конфликт с понятной ставкой" },
        video: {
          score: sc,
          moment: "охранник разворачивает к служебному входу",
          technical: { lag: 0 },
        },
        critic: { ok: true },
        trimmed_s: 4.2,
        cuts: 3,
      },
      targets: Object.fromEntries(
        ["tiktok", "youtube", "instagram"].map(p => [
          p,
          {
            hook: ov,
            caption: "курьер в америке",
            hashtags: ["#доставкавсша"],
            title: ov,
            description: "",
            status: "ready",
            asset: "demo.mp4",
          },
        ])
      ),
      posts: {},
    });
  });

  const ago_ = (m: number) => new Date(now - m * 6e4).toISOString();
  const tzA = "Europe/Moscow";

  return {
    generated_at: ago_(3),
    title: "ClipsBot — SaaS Автонарезки стримов",
    timezone: TZ,
    streamer: {
      login: "albert1million",
      twitch_login: "albert1million",
      display_name: "albert1million",
    },
    subscription,
    plans,
    channels,
    activeChannelId: "ch_albert",
    invoices,
    accounts,
    posting: { timezone: tzA },
    settings: {
      values: {
        "quality.make_min": 7,
        "quality.post_min": 7,
        "quality.max_per_chunk": 2,
        "quality.exceptional": 9,
        "quality.reserve_target": 8,
        "quality.reserve_max": 16,
        "ai.scout_audio": true,
        "ai.video_review": true,
        "ai.video_model": "gemini-4-argon",
        "ai.planner": true,
        "ai.planner_model": "gemini-4-argon",
        "clips.min_seconds": 10,
        "clips.max_seconds": 59,
        "clips.trim_silence": true,
        "clips.trim_gap_seconds": 4,
        "clips.follow_subject": false,
        "posting.daily_max": 4,
        "posting.offday_max": 2,
        "posting.daily_min": 1,
        "posting.min_gap_minutes": 180,
        "posting.hot_now": true,
        "platforms.tiktok": true,
        "platforms.youtube": true,
        "platforms.instagram": true,
      },
      schema: {
        "quality.make_min": [7, [5, 10]],
        "quality.post_min": [7, [5, 10]],
        "quality.max_per_chunk": [2, [1, 10]],
        "quality.exceptional": [9, [7, 10]],
        "quality.reserve_target": [8, [0, 60]],
        "quality.reserve_max": [16, [1, 120]],
        "ai.scout_audio": [true, "bool"],
        "ai.video_review": [true, "bool"],
        "ai.video_model": ["gemini-4-argon", ["gemini-4-argon", "gemini-3.8-flash"]],
        "ai.planner": [true, "bool"],
        "ai.planner_model": ["gemini-4-argon", ["gemini-4-argon", "gemini-3.8-flash"]],
        "clips.min_seconds": [10, [6, 30]],
        "clips.max_seconds": [59, [20, 90]],
        "clips.trim_silence": [true, "bool"],
        "clips.trim_gap_seconds": [4, [1, 10]],
        "clips.follow_subject": [false, "bool"],
        "posting.daily_max": [4, [0, 12]],
        "posting.offday_max": [2, [0, 12]],
        "posting.daily_min": [1, [0, 6]],
        "posting.min_gap_minutes": [180, [20, 600]],
        "posting.hot_now": [true, "bool"],
        "platforms.tiktok": [true, "bool"],
        "platforms.youtube": [true, "bool"],
        "platforms.instagram": [true, "bool"],
      },
    },
    switches: {},
    status: {
      live: {
        is_live: true,
        title: "Доставка по ЛА на Тесле",
        started_at: ago_(202),
        viewers: 1840,
      },
      process: {
        state: "running",
        stage: "ИИ смотрит видео финалиста 2/4",
        stage_id: "video",
        vod_title: "Доставка по ЛА на Тесле",
        vod_id: "1",
        chunk: "2:00:00–4:00:00",
        progress: 66,
        updated_at: ago_(2),
        funnel: {
          peaks: 12,
          scout: 4,
          candidates: 15,
          text_pass: 4,
          video_pass: 1,
          made: 0,
        },
      },
      post: {
        timezone: tzA,
        plan: {
          today: ["16:07", "19:07", "21:30"],
          cap: 4,
          releases_today: 2,
          slots_left: 2,
          up_next: [
            { id: "q0", hook: "Чат заказал пиццу… клиенту", score: 9, expires_in_h: 34 },
          ],
        },
        accounts: {
          tt_main: {
            state: "готова",
            last_post_at: ago_(130),
            today: { published: 1, drafts: 1 },
          },
          yt_main: {
            state: "готова",
            last_post_at: ago_(130),
            today: { published: 2 },
          },
          ig_main: {
            state: "отдыхает до 18:00 UTC: Instagram: API access blocked",
            last_post_at: ago_(500),
            today: { published: 1 },
            last_error: "API access blocked [blocked]",
          },
        },
      },
      brain: {
        last: {
          action: "wait",
          reason: "Жду 19:07: вечерний пик аудитории, а у клипа с эфира ещё 34 часа жизни.",
          by: "ИИ-продюсер",
        },
        feed: [
          {
            at: ago_(130),
            action: "post",
            clip: "c0",
            reason: "Сильный клип с эфира, пауза прошла, вечер — выкладываю сразу.",
            by: "ИИ-продюсер",
            released: ["tiktok", "youtube", "instagram"],
            thoughts: [
              { who: "продюсер", reason: "свежак 9/10" },
              { who: "критик", agree: true, reason: "согласен" },
            ],
          },
          {
            at: ago_(70),
            action: "wait",
            reason: "После прошлого релиза прошло 60 мин из 90.",
            by: "правила",
          },
          {
            at: ago_(10),
            action: "wait",
            reason: "Жду 19:07: вечерний пик аудитории.",
            by: "ИИ-продюсер",
            thoughts: [
              { who: "продюсер", reason: "до пика 2 часа" },
              { who: "критик", agree: true, reason: "ок" },
            ],
          },
        ],
      },
      funnel: {
        chunks: [
          {
            at: ago_(90),
            chunk: "0:00:00–2:00:00",
            candidates: 16,
            text_pass: 5,
            video_pass: 2,
            made: 2,
          },
        ],
        rejected: [
          {
            at: ago_(80),
            vod_id: "1",
            t: 3123,
            stage: "видео",
            score: 5,
            reason: "после просмотра видео оценка 5: обычный разговор о маршруте",
            what: "едет и комментирует дорогу",
          },
          {
            at: ago_(81),
            vod_id: "1",
            t: 4100,
            stage: "видео",
            score: 7,
            reason: "лаги: картинка замирает на 8 с",
            what: "зависание видеопотока",
          },
          {
            at: ago_(82),
            vod_id: "1",
            t: 5200,
            stage: "критик",
            score: 7,
            reason: "в ролике нет грабителя — это доставка Grubhub",
            what: "кликбейтный заголовок не подтвердился",
          },
          {
            at: ago_(83),
            vod_id: "1",
            t: 6000,
            stage: "текст",
            score: 3,
            reason: "чтение доната без сути и драматургии",
            what: "донат на 50 рублей",
          },
        ],
      },
      health: {},
      system: {
        watch: { level: "ok", msg: "эфир идёт", at: ago_(4) },
        process: { level: "ok", msg: "обработано кусков: 1", at: ago_(70) },
        post: { level: "ok", msg: "жду: вечерний пик", at: ago_(10) },
        stats: { level: "ok", msg: "статистика собрана", at: ago_(20) },
        doctor: { level: "ok", msg: "ключи и модели в норме", at: ago_(60) },
      },
      tokens: {
        tt_main: { connected: true, user: "albert1million", refresh_expires_at_days: 340 },
        yt_main: { connected: true, user: "albert1million" },
        ig_main: { connected: true, user: "@albert1million.clips", expires_at_days: 52 },
      },
      storage: { assets: 3, bytes: 64e6 },
    },
    policy: {
      stats: { with_residual: 40 },
      frozen: false,
      evidence: {
        all: {
          hook_style: {
            tease: { n: 10, mean: -0.05 },
            conflict: { n: 9, mean: 0.02 },
            number: { n: 11, mean: 0.35 },
            quote: { n: 8, mean: -0.1 },
          },
        },
      },
      hours: {
        youtube: [
          0.2, 0.12, 0.06, 0.04, 0.04, 0.07, 0.18, 0.4, 0.55, 0.5, 0.48, 0.52,
          0.66, 0.7, 0.62, 0.58, 0.63, 0.78, 0.92, 1, 0.97, 0.9, 0.74, 0.44,
        ],
      },
    },
    decisions: [
      {
        id: "d2",
        at: ago_(60 * 24 * 3),
        kind: "arms",
        summary: "Все площадки: стиль хука «цифра» заходит лучше (+35% к норме, n=11, уверенность 88%) — его доля 25% → 46%",
        reversible: true,
      },
      {
        id: "d1",
        at: ago_(60 * 30),
        kind: "health",
        summary: "yt_main: «остывание» → «норма». всё в норме",
        reversible: false,
      },
    ],
    commands: { results: {} },
    clips,
    posts,
    vods: [{ id: "1", title: "Доставка по ЛА" }],
  };
}
