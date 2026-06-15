export interface CurrentUser {
  username: string;
  role: 'user' | 'admin';
}

export interface UserInfo {
  username: string;
  role: string;
  created_at: string;
}

export interface AuthForm {
  username: string;
  password: string;
  role: string;
  admin_code: string;
  remember_me: boolean;
}
