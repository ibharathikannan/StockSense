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

/** One-year numbers; null when an asset has too little price history. */
export interface AssetRisk {
  volatility_1y: number | null;
  beta: number | null;
  max_drawdown_1y: number | null;
  dividend_yield: number | null;
}

export interface DashboardAsset {
  ticker: string;
  name: string;
  asset_type: string;
  category: string | null;
  sector: string;
  risk: AssetRisk | null;
}

export interface DashboardSuggestion extends DashboardAsset {
  /** 0-1 similarity to the profile, for ordering only; not a forecast. */
  score: number;
  /** Plain-English reasons: content reasons first, the last one is always about risk. */
  reasons: string[];
}

export interface Dashboard {
  risk_level: { key: string; label: string; volatility_limit: number; step: number | null; steps: number };
  interests: { key: string; label: string }[];
  asset_types: string;
  /** Last trading day in the price data behind the risk numbers (YYYY-MM-DD). */
  prices_as_of: string | null;
  watchlist: DashboardAsset[];
  suggestions: DashboardSuggestion[];
}
