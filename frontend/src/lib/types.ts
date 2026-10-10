// Mirrors the FastAPI response schemas (backend/app/schemas/*).

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
  last_login_at: string | null;
}

export interface CurrentUser extends User {
  permissions: string[];
}

export interface Role {
  name: string;
  description: string | null;
  permissions: string[];
  is_system: boolean;
  user_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface RoleOption {
  name: string;
  description: string | null;
}

export interface Permission {
  key: string;
  description: string;
  group: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: CurrentUser;
}

export interface RiskLevelOption {
  key: string;
  label: string;
  description: string;
}

export interface InterestOption {
  key: string;
  label: string;
  /** Recommendable assets behind this interest. */
  asset_count: number;
}

export interface AssetTypeOption {
  key: string;
  label: string;
}

export interface ProfileOptions {
  risk_levels: RiskLevelOption[];
  interests: InterestOption[];
  asset_types: AssetTypeOption[];
  max_followed: number;
}

export interface Profile {
  risk_level: string;
  interests: string[];
  asset_types: string;
  followed_tickers: string[];
  completed_at: string;
  updated_at: string;
}

export interface AssetSummary {
  ticker: string;
  name: string;
  asset_type: string;
  sector: string;
}

// --- Recommendations (backend/app/schemas/recommendations.py) ---------------

export type Stance = "EXPLORE" | "MONITOR" | "CAUTION";

export interface Forecast {
  return_10d: number | null;
  lower: number | null;
  upper: number | null;
  model_version: string | null;
  basis: string;
}

export interface NewsSignal {
  score: number | null;
  relevance: number | null;
  recency_hours: number | null;
  source: string | null;
  article_count: number;
}

export interface Signal {
  baseline_stance: Stance;
  news_aware_stance: Stance;
  provisional: boolean;
  decision_trace: string[];
  news_signal: NewsSignal;
  risk_profile: string;
}

export interface Citation {
  title: string;
  source_type: string;
  published_at: string | null;
  source_url: string | null;
}

export interface Evidence {
  title: string;
  source_type: string;
  published_at: string | null;
  source_url: string | null;
  snippet: string;
}

export interface Explanation {
  text: string;
  citations: Citation[];
  abstained: boolean;
  caveats: string[];
}

export interface RecommendationSnapshot {
  ticker: string;
  name: string;
  sector: string;
  asset_type: string;
  as_of: string | null;
  forecast: Forecast;
  signal: Signal;
  evidence: Evidence[];
  explanation: Explanation;
}

export interface DiversificationNote {
  sector_exposure: Record<string, number>;
  dominant_sector: string | null;
  concentrated: boolean;
  warning: string | null;
  diversifying_tickers: string[];
}

export interface DiscoveryResponse {
  candidates: RecommendationSnapshot[];
  diversification: DiversificationNote;
}
