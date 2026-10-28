# Auto-clipping albert1million → TikTok, YouTube Shorts, Instagram Reels

The bot watches Twitch streams on its own, finds the moments that land, edits vertical clips in a consistent house template, builds a tailored version for each platform, posts at the hours that pay off, learns from real view counts, keeps an eye on account health, and maintains an honest payout ledger. All of it runs on free GitHub.

```
Twitch ─(10 min)─► 1·Watch ─► 2·Process ─► versions for TikTok / Shorts / Reels ─► 3·Post (hourly)
                                  │                                                   │
                                  └────► data branch ◄── 4·Stats (hourly) ◄───────────┘
                                         policy · decisions · health      5·Doctor (daily)
                                              │
                                  dashboard on GitHub Pages (password-encrypted)
```

Legitimate methods only: no view inflation, no bots, no bought traffic, no working around platform rules. A ban wipes everything out, so every rule below is there to keep the accounts alive for the long haul.

---

## v6: rhythm, sync, subtitles

**All three or none.**
- A new clip ships only when every enabled platform is ready. Each one is checked before upload: token alive, limits healthy. If one fails, the clip ships nowhere.
- If a platform is cooling off after an error, the others wait too, however long it takes. There are no "skip it after 2, 3 or 12 hours" timers.
- If a platform still rejects the upload, the bot catches it up once the platform recovers. No new releases go out until the platforms are level again, so the clip count stays identical everywhere.
- A TikTok draft counts as posted.

**A firm daily cap, best clips first.**
- A schedule is built at the start of the day: N slots (5 by default, 6 on a hot streak) at the audience's best hours, with a 2 h gap.
- Each slot takes the best clip in the queue. Mediocre clips don't take a morning slot away from the evening's top moment.
- Clips don't burn. Anything that doesn't fit today goes to the next slots — a top moment is never lost. Age only nudges priority down: yesterday's 9 still beats today's 7.
- A strong clip from a live stream can claim the next slot early. Anything below the threshold never ships at all.
- The AI producer picks which clip goes in a slot, but not how many or when.

**Smart length, no switches.**
- Usually 15–45 s.
- Over a minute only when nearly all of it holds up: a story with a hook, development, a build. Those go through a separate strict check — the model rewatches the video and decides whether the length is earned. If it sags anywhere, it trims or cuts the dead air.
- There's no hard 59 s or 90 s ceiling. The limit is 175 s (the platform cap).

**Subtitles and copy match what was actually said.**
- For every finalist the AI listens to the audio and cross-checks it against the recognized words. It fixes recognition errors only (lookalike words, slang, names, brands, numbers), going on the audio, the sense of the sentence, and chat.
- The fix propagates to the subtitles, the hook, the title and the captions.
- There's no hand-written word list in the config. Past corrections accumulate in `glossary.json` and come back as a hint to the proofreader and to Whisper next time. No blind find-and-replace: every call is made against the audio of that specific clip.
- **English speech** is written in English, with the translation in quotes on the line below.

**New style.**
- Subtitles are plain white text with a black outline near the bottom edge of the video: no colored word highlighting, no "pops", no all-caps, phrases of up to 7 words.
- The title is white with an outline too, smaller and unanimated.

## v5: the engine (October 2026)

The design and the dashboard are unchanged — the engine was rebuilt.

**AI.** The native Gemini API instead of an OpenAI-compatible shim:
- **JSON-schema responses** (structured output): a malformed or truncated AI response is now physically impossible.
- **No `temperature` on Gemini 3+/4**: Google explicitly requires dropping it when moving to Gemini 3 (below 1.0 the model loops and dulls). v4 sent 0.1–0.3 on every request.
- **Thinking levels** per task: the director thinks at `high`, the scout and producer at `medium`, copy and the critic at `low`.
- **Cloud speech-to-text** via `gemini-3.5-transcribe` with word-level timestamps: every window of a chunk is transcribed in parallel in seconds. Whisper on CPU stays as the per-window fallback and doesn't even load if the cloud handled it.
- **Limits tracked per key × model**, with the backoff taken from Google's `RetryInfo`: a used-up daily quota on `gemini-4-argon` no longer disables the key for flash. If a model disappears or is renamed, the next one in the chain takes over, ending at the `gemini-flash-latest` alias. If a model rejects some API field, that field is dropped automatically and the request is retried.
- **Second opinion**: for a clip sitting right on the threshold, the director takes an independent second look; the result is the average, rounded down.
- Every 3 hours a "doctor" checks each key and the presence of the models from settings (dashboard → Settings → System → "AI").

**Speed.** Audio, chat and viewer clips download at the same time, candidates are transcribed in one go, scout batches and director viewings run in parallel, and the sources for selected clips are fetched ahead of time while the previous one renders. A purpose-built HLS downloader pulls recording segments over 12 connections (yt-dlp reads them one at a time) and understands the fMP4/HEVC recordings that made v4 fall over. Stream chunks are **1 hour** instead of 2, so a clip from a live stream ships twice as fast.

**Accuracy.** Fixed an audio shift: trimming "before the input" on a concatenated TS moved the start by ~0.2 s and dropped ~1 s off the end of the chunk, which left subtitles trailing slightly behind. The cut is now sample-accurate (covered by a test). The same moment appearing in two overlapping chunks no longer becomes two clips.

**Reliability.**
- **No data loss between workflows.** The `data` branch merges three-way by JSON key. Previously watch and process wrote `status/system.json` at the same time and one silently clobbered the other.
- **No duplicates after a crash.** A clip is marked "uploading" before the upload starts. If the runner dies mid-publish, the bot doesn't blindly repost: stats will find the video, and if it isn't there, a "Retry" appears in the dashboard.
- **Release to all platforms at once** (in parallel, not one after another). YouTube resumes from where the transfer broke rather than starting over.
- Statuses sync no more than once every 45 s. The `data` branch is squashed into a single commit weekly, so the repository doesn't balloon over the months.
- The schedule is protected against GitHub's auto-disable after 60 days of silence. Actions are updated for Node 24 (Node 20 was removed from runners on 2026-09-23) and dependencies are installed by `uv`. Every run writes a short report to the Summary tab.
- PBKDF2 at 600,000 iterations (the OWASP recommendation), dashboard-compatible. Removed the OAuth code being interpolated straight into a shell script.

## What's inside (v4: the "brain")

### Selection: four heads that argue
1. **Scout** — Gemini listens to the **entire** hour-long stream chunk end to end (audio plus a per-minute table of chat reactions) and flags moments that chat spikes and loudness peaks miss: stories, quiet punchlines.
2. **Screener** — scores each candidate from the Whisper transcript on a hard, calibrated 1–10 scale (what happens to this clip in a stranger's feed; "7 — they watch it through, 8 — they forward it, 9 — once a week"). Weak material is cut before the expensive checks.
3. **Director** — Gemini **watches the video** of a finalist: is the moment actually there, are there lags or freezes (plus a technical `freezedetect` pass — a frozen recording is discarded without spending AI), where to start and end, which pauses to cut, and honest titles and copy per platform.
4. **Critic** — a separate model checks that the title describes what actually happens. If it disagrees, it rewrites the title or kills the clip.

The default threshold is **7/10 after the video viewing**, at most 2 clips per hour of stream (usually 0–1). Every rejection is logged with its reason: dashboard → Clips → "Passed on".

**The bar floats with the backlog.** A stream runs 5–10 hours, but only a handful of releases go out per day. Taking the same number from every hour yields two dozen clips a day against a cap of four, and half of them just sit there. So: while fewer than `quality.reserve_target` (8) are ready, the bar is normal; from eight, +1 point; above `quality.reserve_max` (16), +2 — meaning only material stronger than what's already queued gets edited. No compute is spent on clips that won't ship anyway.

### Editing
- One video for all platforms (one render, one file); only the copy differs.
- **No cold open**: the clip starts at the start of the moment, with no fragments of the payoff up front.
- Pauses and silence are cut: gaps longer than 1.2 s by Whisper's word timings, plus stretches the director flagged from the video; joins get a micro audio fade, so no clicks.
- **The camera behaves like the original**: one framing for the whole clip, no moves. A shift (once, static) happens only if it's enabled in settings and the streamer is consistently off to the edge of frame.

### Publishing: one release across every platform
- A clip goes to TikTok, Shorts and Reels **at the same time** (TikTok without API audit goes to drafts in the inbox for a minute — you have to hit "Post").
- **The AI producer** sees the full picture every hour (the queue, the scores, how many slots and active hours remain, how the latest videos are landing, whether a stream is live) and decides whether to post now or wait, and what. A second AI critic reviews the decision. The AI cannot break the hard rules: the gap between releases (3 h), the daily cap (4 on a stream day, 2 without), and clips rated ≥ 7 only.
- **There are no forbidden hours.** The day's slots are laid out purely by audience activity — the bot doesn't go quiet at night just because it's night.
- Weak clips never ship, and neither does filler.
- **Clips don't burn.** Anything that doesn't fit in a day sits in reserve waiting for a slot; age only nudges priority down (−0.12 points per day), so yesterday's 9 still beats today's 7. Each clip has its own shelf life, set by the screener in the `shelf` field: `now` — tied to an event, good for a week; `weeks` — 45 days; `forever` — timing doesn't matter, it keeps indefinitely (the default). An expired clip isn't deleted but marked `expired`: it stays in the history and the dashboard and simply stops entering the queue.
- **On a day without a stream** the bot doesn't rest — it posts from reserve, just less (2 instead of 4): a steady rhythm beats a burst after silence. Strong clips aren't wasted doing it, since the queue is ranked by score, so an empty day ships what's been sitting rather than the best of the fresh material.
- **Hot streak**: if a recent video is pulling numbers several times above normal, the bot doesn't sit on it and gets +1 release for the day.
- **"Cooldown" is gone.** It compared new videos against old ones (from May) and throttled posting on a perfectly healthy channel by itself. Platforms judge each video on its own and don't penalize frequency at normal quality; a view dip on a small channel is noise and quality, not a ban. A platform is paused only on direct signals from the platform itself (spam/limit/block).

### Why it works this way (the data)
- Buffer, 11.4M TikTok posts: the more often you post, the higher the chance of a hit (p90 climbs from 3.7k to 14.4k), while the median barely moves — volume helps only if the videos aren't weak. Hence "quality ≥ 7 first, then volume".
- Buffer, 100k+ accounts: consistency (every week) is worth up to +450% engagement — hence daily releases at similar hours, including on days without a stream.
- TikTok advises staying at **4 videos a day or fewer** and spreading them across the day rather than posting several within an hour: videos from one account that go out back to back steal each other's first impressions. Hence the cap of 4 and the 3-hour gap. "Consistency beats volume": 3 videos a week every week beats 10 in one week and three weeks of silence — hence the reserve and the no-stream days, rather than a burst on stream day and nothing after.
- YouTube (1 October 2026) and Instagram (2026) throttle reach on reuploads that add nothing of their own. The added value here is the selection, the edit with pauses removed, the honest hook, the subtitles and the house template; it works best when the channel belongs to the streamer (YouTube explicitly exempts a creator's own content).

### Dashboard
Tabs: **Overview** (the day's timeline of releases and plan, money, platforms, the clipping pipeline with its funnel), **Clips** (waiting, TikTok drafts, shipped, errors, "passed on" with reasons; "post now", "don't post"), **Analytics** (AI score against real views, topics, platforms, title style, hours, a clip table), **Brain** (how and why the producer decided, behavior changes), **Management** (rate and payout threshold, the payout ledger with partial payments, adjustments and record edits, video flags: duplicate / own title / exclude), **Settings** (a "Stop" button: everything / posting only / analysis only; every bot parameter; the GitHub key once for all devices; system).
Anything that changes data goes through a confirmation dialog spelling out exactly what will change; stopping the bot and changing the rate also require typing a confirmation word.

### Money
A clip is paid once, on the platform where it did best; growth after a payout is topped up for the increment only; double payment is impossible ("paid through" is tracked per clip). Duplicates are merged permanently and counted as one clip. The rate and threshold live in the dashboard (stored encrypted in `ledger.enc`); `MONEY_CONFIG` is no longer needed.

---

## Setup

### 1. Repository and GitHub
1. A **public** repository (`clips`, say); upload every file from the archive. Actions are free with no minute cap on public repositories; secrets stay hidden, and the dashboard data and the ledger are encrypted.
2. Settings → Actions → General → Workflow permissions → **Read and write** → Save.
3. Settings → Pages → *Deploy from a branch* → `main`, folder `/docs`.

### 2. Twitch
dev.twitch.tv/console → Register Your Application (Redirect `http://localhost`, Confidential) → Client ID and Client Secret. The streamer has to turn on "Store past broadcasts", and the recordings must be publicly visible.

### 3. TikTok
developers.tiktok.com → Connect an app → Login Kit + Content Posting API (enable Direct Post) → scopes `user.info.basic, video.upload, video.publish, video.list` → Redirect URI: `https://<user>.github.io/clips/callback.html` → Terms and Privacy: `…/terms.html`, `…/privacy.html` (put the domain verification file in `docs/`). Until the audit clears, run in `inbox` mode (drafts) or Sandbox.

### 4. YouTube Shorts — manual steps (10 minutes)
1. console.cloud.google.com → new project → APIs & Services → **Enable APIs**: *YouTube Data API v3* and *YouTube Analytics API*.
2. **OAuth consent screen** → External → name, your email, domain `<user>.github.io`, links to privacy and terms → scopes `youtube.upload`, `youtube.readonly`, `yt-analytics.readonly`.
3. **Important:** Publishing status → **Publish app → In production**. In Testing mode Google revokes access every 7 days. You don't need Google verification for your own channel: signing in will warn that "the app isn't verified" → *Advanced → Go to …*.
4. Credentials → Create OAuth client ID → *Web application* → Authorized redirect URI: `https://<user>.github.io/clips/callback.html` → Client ID and Client Secret.
5. API uploads are capped at 100 videos a day (a separate quota), and videos go out publicly.

### 5. Instagram Reels — manual steps (15 minutes)
1. The Instagram account must be **professional** (Settings → Account type → Business or Creator).
2. developers.facebook.com → Create app → type *Business* → add the **Instagram** product → *API setup with Instagram login*.
3. Business login settings → Redirect URL: `https://<user>.github.io/clips/callback.html` → copy the **Instagram app ID** and **Instagram app secret**.
4. App roles → Roles → Add people → **Instagram Tester** → your account. Then in Instagram: Settings → Apps and websites → Tester invites → accept. As long as you only publish to your own accounts, Meta app review isn't required (development mode).
5. The limit is 100 posts a day. Instagram pulls the video from a GitHub Release URL (which is why the repository is public).

### 6. Secrets and variables (Settings → Secrets and variables → Actions)
**Secrets:** `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `IG_CLIENT_ID`, `IG_CLIENT_SECRET`, `DASHBOARD_PASSWORD`, `TOKEN_KEY` (a random string of 40+ characters), and the Gemini keys `GEMINI_API_KEY_*` (the names come from `config.yaml` → `llm.providers`; each one has to be listed in the env of the process, post and doctor workflows).

**Variables:** `OAUTH_REDIRECT_URI` = `https://<user>.github.io/clips/callback.html`. The rate and the payout threshold are set in the dashboard.

`docs/app-config.js` → `tiktokClientKey`, `youtubeClientId`, `instagramClientId` (not secrets).

### 7. Connect the accounts
`https://<user>.github.io/clips/connect.html` → pick a platform → sign in → copy the code → Actions → **"0 · Connect account"** → Run workflow (platform, `tt_main` / `yt_main` / `ig_main`, code). The code lives for a few minutes. A platform can be connected later: the bot will start building versions for it on its own.

### 8. Start it
Actions → **"1 · Watch Twitch"** → Run workflow. Everything runs on schedule from there. In the dashboard (Settings) add a GitHub key (fine-grained token, this repository only, Contents and Actions: Read and write) — once; after that it's stored in the repository, encrypted with the dashboard password.

---

## What stays manual (5 minutes a day, and it shows)
- TikTok in `inbox` mode: open the draft → add a quiet trending sound if you like → "Post". The copy is ready to paste from the clip card.
- The first comment (written for you, in the card) and replies to comments in the first hour.
- Keep a link to twitch.tv/albert1million in the profiles. Don't change the handle or avatar often.
- Don't delete or reupload anything.
- Apply for the TikTok Content Posting API audit once everything is running: after that it's `posting.tiktok.mode: direct` and the whole thing is hands-off.

Nobody can guarantee a clip goes viral — the algorithms are closed. The bot covers everything that is under our control, and gets sharper every day about what works for your audience specifically.

## Layout
```
config.yaml           — settings (many are starting values; the bot tunes itself from there)
assets/twitch-logo.png — logo for the badge (cleaned up)
clipper/
  pipeline.py brain.py signals.py transcribe.py judge.py render.py framing.py logo.py audio.py qa.py — selection and editing
  llm.py — the AI engine (native Gemini, schemas, limits, fallbacks) · schemas.py — JSON response schemas
  twitch.py — Helix API + the parallel HLS downloader · store.py — the data branch with merging
  settings.py — settings and switches from the dashboard
  platforms/ (tiktok, youtube, instagram) — publishing and stats
  poster.py — when and what to post · stats.py — views, doctor
  learn.py — learning and the post cap · health.py — early warning, system · decisions.py — log and rollbacks
docs/                 — dashboard (index.html + money.js), account connection, privacy/terms
tests/                — python tests/test_core.py · test_v3.py · test_v4.py · test_v5.py · node tests/test_money.js
```
