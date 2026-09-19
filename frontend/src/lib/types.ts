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
