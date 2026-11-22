export interface User {
  id: string;
  name: string;
  email: string;
  plan: PlanId;
  language: 'ar' | 'en';
  createdAt: string;
}

export type PlanId = 'free' | 'pro';

export interface AuthSession {
  token: string;
  user: User;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface RegisterInput {
  name: string;
  email: string;
  password: string;
}

export interface ForgotInput {
  email: string;
}

export interface ResetInput {
  token: string;
  password: string;
}
