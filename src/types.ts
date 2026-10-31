export type Platform = "tiktok" | "youtube" | "instagram";

export interface Account {
  id: string;
  name: string;
  platform: Platform;
}

export interface Post {
  id: string;
  platform: Platform;
  account: string;
  title: string;
  create_time: number;
  url: string;
  views: number;
  history?: Record<string, number>;
  clip_id?: string;
  deleted_at?: string | null;
  thumb?: { thumb?: string } | null;
}

export interface TargetDetails {
  hook?: string;
  caption?: string;
  hashtags?: string[];
  title?: string;
  description?: string;
  status?: string;
  asset?: string;
}

export interface PostStatus {
  status: string;
  posted_at?: string;
  url?: string;
  reason?: string;
  by?: string;
  started_at?: string;
}

export interface BrainInfo {
  text?: { score: number; why: string };
  video?: { score: number; moment: string; technical?: { lag: number } };
  critic?: { ok: boolean; reason?: string };
  trimmed_s?: number;
  cuts?: number;
}

export interface Clip {
  id: string;
  channel_id?: string;
  overlay: string;
  category: string;
  score: number;
  duration: number;
  status: string; // ready, drafts, posted, failed, inbox, rejected, used, expired, retry
  created_at?: string;
  what?: string;
  why?: string;
  vod_id?: string;
  vod_time?: number;
  thumb?: string;
  transcript?: string;
  first_comment?: string;
  force_post?: string;
  brain?: BrainInfo;
  targets?: Record<string, TargetDetails>;
  posts?: Record<string, PostStatus>;
}

export interface GroupedClip {
  key: string;
  clip: Clip | null;
  posts: Post[];
  raw: Set<string>;
  best: Post;
  merged: string[] | null;
  bestViews: number;
  title: string;
  created: number;
  thumb: string | null;
  preexisting?: boolean;
  labeled?: boolean;
}

export interface Decision {
  id: string;
  at: string;
  kind: string;
  summary: string;
  reversible?: boolean;
}

export interface ProducerThought {
  who: string;
  agree?: boolean;
  reason: string;
}

export interface ProducerFeedItem {
  at: string;
  action: "post" | "wait" | "adjust";
  clip?: string;
  reason: string;
  by: string;
  released?: string[];
  thoughts?: ProducerThought[];
}

export interface SystemCheck {
  level: "ok" | "warn" | "error" | "paused";
  msg: string;
  at: string;
  run_url?: string;
}

export interface AccountTokenStatus {
  connected: boolean;
  user?: string;
  refresh_expires_at_days?: number;
  expires_at_days?: number;
  error?: string;
  kind?: string;
}

export interface SubscriptionPlan {
  id: "starter" | "pro" | "agency";
  name: string;
  priceMonthly: number;
  priceAnnual: number;
  maxChannels: number;
  clipsPerDay: number;
  maxClipsPerMonth: number;
  quality: string;
  badge?: string;
  features: string[];
}

export interface SubscriptionInfo {
  planId: "starter" | "pro" | "agency";
  status: "active" | "trial" | "past_due";
  billingCycle: "monthly" | "annual";
  renewalDate: string;
  clipsUsedThisMonth: number;
  clipsQuotaThisMonth: number;
  streamsProcessedHours: number;
  paymentMethod: string;
}

export interface InvoiceRecord {
  id: string;
  date: string;
  planName: string;
  amount: number;
  status: "paid" | "pending";
  pdfUrl?: string;
}

export interface StreamerChannel {
  id: string;
  twitchLogin: string;
  displayName: string;
  avatarUrl?: string;
  status: "live" | "offline";
  viewers?: number;
  currentStreamTitle?: string;
  clipsCount: number;
  platforms: {
    tiktok: boolean;
    youtube: boolean;
    instagram: boolean;
  };
}

export interface AppData {
  generated_at: string;
  title: string;
  timezone: string;
  streamer?: {
    login?: string;
    twitch_login?: string;
    display_name?: string;
  };
  subscription: SubscriptionInfo;
  plans: SubscriptionPlan[];
  channels: StreamerChannel[];
  activeChannelId: string;
  invoices: InvoiceRecord[];
  accounts: Account[];
  posting?: {
    timezone: string;
  };
  settings: {
    values: Record<string, any>;
    schema: Record<string, [any, any]>;
  };
  switches: {
    process?: boolean;
    post?: boolean;
    stats?: boolean;
    at?: string;
    note?: string;
  };
  status: {
    live?: {
      is_live?: boolean;
      title?: string;
      started_at?: string;
      viewers?: number;
      vod_missing?: boolean;
    };
    process?: {
      state?: string;
      stage?: string;
      stage_id?: string;
      vod_title?: string;
      vod_id?: string;
      chunk?: string;
      progress?: number;
      updated_at?: string;
      funnel?: {
        peaks?: number;
        scout?: number;
        candidates?: number;
        text_pass?: number;
        video_pass?: number;
        made?: number;
      };
    };
    post?: {
      timezone?: string;
      plan?: {
        today?: string[];
        cap?: number;
        releases_today?: number;
        slots_left?: number;
        up_next?: Array<{
          id: string;
          hook: string;
          score: number;
          expires_in_h?: number;
        }>;
      };
      accounts?: Record<string, {
        state?: string;
        last_post_at?: string;
        cooldown_until?: string;
        last_error?: string;
        today?: { published?: number; drafts?: number };
      }>;
    };
    brain?: {
      last?: {
        action: string;
        reason: string;
        by: string;
      };
      feed?: ProducerFeedItem[];
    };
    funnel?: {
      chunks?: Array<{
        at: string;
        chunk: string;
        candidates?: number;
        text_pass?: number;
        video_pass?: number;
        made?: number;
      }>;
      rejected?: Array<{
        at: string;
        vod_id?: string;
        t: number;
        stage: string;
        score?: number;
        reason?: string;
        what?: string;
      }>;
    };
    health?: Record<string, { state: string; reason?: string }>;
    system?: Record<string, SystemCheck>;
    tokens?: Record<string, AccountTokenStatus>;
    storage?: { assets?: number; bytes?: number };
  };
  policy?: {
    stats?: { with_residual?: number };
    frozen?: boolean;
    evidence?: {
      all?: {
        hook_style?: Record<string, { n: number; mean: number }>;
      };
    };
    hours?: Record<string, number[]>;
  };
  decisions?: Decision[];
  commands?: { results: Record<string, any> };
  clips: Clip[];
  posts: Post[];
  vods?: Array<{
    id: string;
    title: string;
    gaps?: Array<{ start: number; end: number; error?: string }>;
  }>;
}
