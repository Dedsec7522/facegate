// Types mirroring backend/app/schemas/common.py and the ad-hoc JSON endpoints.

export type Role = 'admin' | 'hr' | 'employee'

export interface User {
  id: string
  email: string
  username: string | null
  role: Role
  mfa_enabled: boolean
  employee_id: string | null
  employee_name: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Department {
  id: string
  name: string
  code: string
  employee_count: number
}

export interface Employee {
  id: string
  employee_code: string
  first_name: string
  last_name: string
  email: string
  job_title: string | null
  department_id: string | null
  department_name: string | null
  status: 'active' | 'inactive'
  pin_fallback_enabled: boolean
  enrolled: boolean
  enrolment_at: string | null
  has_account: boolean
  created_at: string
}

export interface EnrolmentRecord {
  id: string
  status: 'active' | 'superseded' | 'revoked'
  created_at: string
  revoked_at: string | null
  template_count: number
  quality_score: number | null
  liveness_score: number | null
  consent_version: string
  model_version: string
  created_by: string | null
  has_thumbnail: boolean
}

export type AttendanceAction = 'check_in' | 'check_out'
export type AttendanceMethod = 'face' | 'pin' | 'manual'

export interface AttendanceEvent {
  id: string
  employee_id: string
  employee_name: string | null
  employee_code: string | null
  department_name: string | null
  action: AttendanceAction
  method: AttendanceMethod
  occurred_at: string
  attendance_date: string
  match_score: number | null
  liveness_score: number | null
  voided: boolean
}

export type DayStatus = 'present' | 'late' | 'missing_checkout' | 'absent' | 'corrected'

export interface AttendanceDay {
  id: string
  employee_id: string
  employee_name: string | null
  employee_code: string | null
  department_name: string | null
  attendance_date: string
  first_in: string | null
  last_out: string | null
  worked_minutes: number
  late_minutes: number
  early_leave_minutes: number
  status: DayStatus
  is_open: boolean
}

export interface TodayBoard {
  summary: { date: string; total: number; present: number; late: number; absent: number; on_site: number; missing_checkout: number }
  items: Array<{
    employee_id: string; name: string; code: string; department: string | null; status: DayStatus; is_open: boolean
    first_in: string | null; last_out: string | null; worked_minutes: number; late_minutes: number
  }>
}

export interface Dashboard {
  date: string
  kpis: { employees: number; enrolled: number; present_today: number; late_today: number; on_site_now: number; absent_today: number; attendance_rate: number }
  trend: Array<{ date: string; present: number; late: number; absent: number; avg_hours: number }>
  departments: Array<{ id: string; name: string; headcount: number; present_today: number }>
  verification_7d: Record<string, number> & { total: number }
  engine: { index_templates: number; index_employees: number; workers: number }
}

export interface VerificationAttempt {
  id: string
  outcome: string
  reason: string | null
  employee_id: string | null
  employee_name: string | null
  match_score: number | null
  second_score: number | null
  liveness_score: number | null
  challenge: string | null
  frames: number
  duration_ms: number | null
  ip: string | null
  created_at: string
  purpose: string
}

export interface Correction {
  id: string
  employee_id: string
  attendance_date: string | null
  event_id: string | null
  kind: 'add' | 'void' | 'adjust'
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  reason: string
  created_by: string
  created_at: string
}

export interface OrgSettings {
  timezone: string
  day_start: string
  work_start: string
  work_end: string
  late_grace_minutes: number
  duplicate_scan_seconds: number
  auto_close_after_hours: number
  match_accept_threshold: number
  pad_live_threshold: number
  require_challenge: boolean
  kiosk_liveness: 'advisory' | 'passive' | 'strict'
  portal_liveness: 'advisory' | 'passive' | 'strict'
  consent_version: string
}

export interface AuditEntry {
  id: number
  actor_email: string | null
  action: string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown> | null
  ip: string | null
  created_at: string
}

export interface ReportSummary {
  from: string
  to: string
  working_days: number
  active_employees: number
  totals: { present_days: number; late_days: number; worked_hours: number; missing_checkouts: number }
  per_employee: Array<{ employee_id: string; name: string; code: string; department: string | null; days_present: number; days_late: number; worked_minutes: number; late_minutes: number; missing_checkouts: number }>
  per_day: Array<{ date: string; present: number; late: number; worked_minutes: number; missing_checkouts: number }>
}

// ---- verification stream messages -------------------------------------------------------
export interface VerifySession {
  session_id: string
  nonce: string
  purpose: 'attendance' | 'enrolment'
  challenge: 'turn_left' | 'turn_right' | null
  challenge_text: string | null
  ttl_seconds: number
  poses: string[] | null
  required_poses?: string[] | null
  bound?: boolean
  ws_token?: string
  employee?: { id: string; name: string; code: string }
}

export interface FrameFeedback {
  state: 'no_face' | 'multiple_faces' | 'quality' | 'ok' | 'collecting' | 'identified' | 'rejected' | 'busy' | 'throttled' | 'error' | 'complete' | 'saved' | 'restarted'
  frame?: number
  face?: { box: [number, number, number, number]; landmarks: [number, number][]; score: number } | null
  faces?: number
  issues?: string[]
  guidance?: string
  quality?: number | null
  timings_ms?: Record<string, number>
  liveness?: { frames: number; needed?: number; score: number; passed: boolean }
  challenge?: { name: string | null; state: 'pending' | 'turned' | 'passed' | 'failed'; text: string }
  yaw?: number
  pitch?: number
  embeddings?: number
  // terminal
  reason?: string
  message?: string
  employee?: { id: string; name: string; code: string; department: string | null }
  token?: string
  today?: { first_in: string | null; last_out: string | null; worked_minutes: number } | null
  next?: { next: AttendanceAction; last_event: { id: string; action: AttendanceAction; occurred_at: string; method: AttendanceMethod } | null; attendance_date: string }
  match_score?: number | null
  liveness_score?: number
  attempt_id?: string
  // enrolment
  poses?: { captured: string[]; target: string | null; text: string; just_captured?: string; required_done?: boolean }
  pose_ok?: boolean
  enrolment_id?: string
  template_count?: number
  quality_score?: number
  detail?: Record<string, unknown>
}
