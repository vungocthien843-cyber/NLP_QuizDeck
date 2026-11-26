export interface Me {
  user_id: number;
  email: string | null;
  name: string | null;
  avatar_url: string | null;
  is_admin: boolean;
  csrf_token: string;
}

export interface DocumentInfo {
  id: number;
  filename: string;
  session_no: number | null;
  status: string;
  error: string | null;
  num_chunks: number;
  num_accepted: number;
  num_rejected: number;
  num_slides: number;
  is_shared: boolean;
  is_mine: boolean;
  can_edit: boolean;
  owner_email: string | null;
}

export type Letter = "A" | "B" | "C" | "D";
export type Difficulty = "easy" | "medium" | "hard";

export interface Quota {
  unlimited: boolean;
  max_docs: number;
  used_docs: number;
  max_upload_mb: number;
}

export interface SlideInfo {
  slide_no: number;
  title: string | null;
  notes: string | null;
  width: number | null;
  height: number | null;
}

export interface SlidesOut {
  document_id: number;
  num_slides: number;
  slides: SlideInfo[];
}

export interface QuizQuestion {
  question_id: number;
  position: number;
  bloom_level: string | null;
  stem: string;
  options: Record<Letter, string>;
}

export interface Quiz {
  quiz_id: number;
  num_requested: number;
  num_questions: number;
  questions: QuizQuestion[];
  mode: string;
  difficulty: string | null;
  notice: string | null;
}

export interface AttemptOut {
  attempt_id: number;
  num_correct: number;
  num_questions: number;
  score_10: number;
}

export interface SourceOut {
  chunk_id: number;
  document_id: number;
  session_no: number | null;
  slide_no: number | null;
  slide_end: number | null;
  title: string | null;
  raw_text: string;
  image_url: string | null;
}

export interface Misconception {
  code: string;
  ten: string;
  chan_doan: string;
}

export interface ReviewItem {
  question_id: number;
  stem: string;
  options: Record<Letter, string>;
  chosen: Letter | null;
  answer: Letter;
  is_correct: boolean;
  rationales: Partial<Record<Letter, string>>;
  explanation: string | null;
  bloom_level: string | null;
  sources: SourceOut[];
  evidence: string | null;
  evidence_document_id: number | null;
  evidence_slide_no: number | null;
  misconception: Misconception | null;
}

export interface ReviewOut {
  attempt_id: number;
  score_10: number;
  items: ReviewItem[];
}

export interface ChatCitation {
  n: number;
  chunk_id: number;
  document_id: number;
  session_no: number | null;
  slide_no: number | null;
  slide_end: number | null;
  title: string | null;
  filename: string | null;
}

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  citations: ChatCitation[];
  attach?: AttachedQuestion | null;
  error?: string | null;
  pending?: boolean;
}

export interface AttachedQuestion {
  question_id: number;
  attempt_id: number;
  index: number;
  stem: string;
  chosen: Letter | null;
  answer: Letter;
  is_correct: boolean;
  slide_no: number | null;
}

export interface ConversationInfo {
  conversation_id: number;
  title: string;
  created_at: string;
  n_messages: number;
}

export interface AttemptSummary {
  attempt_id: number;
  quiz_id: number;
  submitted_at: string;
  score_10: number;
  num_questions: number;
  num_correct: number;
  mode: string;
  label: string;
}

export interface Weakness {
  concept: string;
  error_type: string;
  ten: string | null;
  chan_doan: string | null;
  score: number;
  n_seen: number;
}

export interface Profile {
  user_id: number;
  n_attempts: number;
  n_answered: number;
  accuracy: number | null;
  weaknesses: Weakness[];
  by_error_type: Record<string, number>;
  error_type_names: Record<string, string>;
}

export interface ExperimentState {
  active: boolean;
  member: boolean;
  name: string | null;
  step: "1" | "2" | "3" | "done" | null;
  quiz1_id: number | null;
  quiz2_id: number | null;
  practice_n: number | null;
  attempt1_id: number | null;
  practice_quiz_id: number | null;
  attempt2_id: number | null;
  feedback_kinds: Record<string, string[]>;
}

export interface ClassStats {
  n_students: number;
  n_active_7d: number;
  n_attempts: number;
  n_answered: number;
  accuracy: number | null;
  n_documents: number;
  n_questions: number;
  by_document: { document_id: number; filename: string; n_answered: number; accuracy: number | null }[];
  by_error_type: Record<string, number>;
  error_type_names: Record<string, string>;
  attempts_by_day: { day: string; n_attempts: number }[];
}

export interface UserRow {
  user_id: number;
  email: string | null;
  name: string | null;
  avatar_url: string | null;
  is_admin: boolean;
  last_login_at: string | null;
  n_attempts: number;
  avg_score: number | null;
  accuracy: number | null;
  n_own_docs: number;
}

export interface BankQuestion {
  question_id: number;
  stem: string;
  options: Record<Letter, string>;
  answer: Letter;
  explanation: string | null;
  bloom_level: string | null;
  difficulty: string | null;
  concept: string | null;
  status: "accepted" | "rejected";
  reject_reason: string | null;
  times_used: number;
  n_answered: number;
  accuracy: number | null;
  slide_no: number | null;
  error_types: Partial<Record<Letter, string | null>>;
}
