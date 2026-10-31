# ClipsBot — Twitch Auto-Clipping & Multi-Platform Publisher

A responsive React + Vite + TypeScript application for monitoring Twitch live streams, automating vertical 9:16 video clipping with AI scoring, coordinating synchronized releases across TikTok, YouTube Shorts, and Instagram Reels, and managing an honest view-based payout ledger.

## Features

- **Pipeline Stages**: Visual monitoring of the 7-stage clipping engine (Idle, Live Recording, Peak Scouting, Speech Transcription, Video Framing Review, 9:16 Montage, Synchronized Publishing).
- **Rhythm & Multi-Platform Sync**: Release cadence following audience peak hours, minimum 2-3 hour spacing, and synchronized 3-way distribution (TikTok inbox drafts, YouTube Shorts, and Instagram Reels).
- **AI Scoring & Selection**: Multi-stage evaluation (Scout audio parsing, transcript scoring 1–10, video freeze & pacing review, critic fact-checking).
- **Clips Management**: Interactive queue filtering (Awaiting publishing, TikTok drafts, Published, Errors, and Rejected candidates with detailed rationale).
- **Analytics & Calibration**: Correlation between AI ratings (7–9) and real view metrics, category breakdowns, title hook effectiveness (+35% number hooks), and 24-hour peak engagement histograms.
- **Fair Payout Ledger**: Anti-double-billing ledger tracking "paid-through" views, growth top-up increments, custom rate per 1,000 views, minimum payout threshold reminders, statement generation (text & CSV), and duplicate clip merging.
- **AI Producer Feed & Brain**: Timeline of hourly scheduling decisions with Producer & Critic thoughts and one-click policy rollbacks.
- **Assistant Help**: Natural language Q&A and setting adjustment suggestions with live configuration diff previews.
- **System Controls & Settings**: Emergency pause controls (all / post only / process only), model switcher (Gemini 4 Argon / Gemini 3.8 Flash), encrypted token storage, and full Russian / English bilingual interface with Light and Dark themes.

## Technology Stack

- **Framework**: React 19, TypeScript
- **Bundler & Dev Server**: Vite
- **Styling**: Tailored CSS tokens matching the original design system with Barlow Condensed, Golos Text, and JetBrains Mono typography
- **Icons**: Lucide React & custom SVG platform logos
- **Security**: Web Crypto API PBKDF2 (600,000 iterations) + AES-GCM 256-bit encryption

## Development

```bash
npm install
npm run dev
```

Build for production:

```bash
npm run build
```
