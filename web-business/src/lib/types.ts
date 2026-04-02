export type UserRole = 'staff' | 'manager' | 'owner';

export interface User {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  first_name: string;
  last_name: string;
}

export interface AuthState {
  user: User | null;
  loading: boolean;
}

export type MessageRole = 'user' | 'assistant';

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
}

export type ModuleStatus = 'live' | 'stale' | 'unavailable';

export interface ModuleContext {
  module: string;
  generated_at: string;
  summary: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
  status: ModuleStatus;
}

export interface ProcessDoc {
  id: string;
  title: string;
  doc_number: string;
  summary: string;
  content: string;
}
