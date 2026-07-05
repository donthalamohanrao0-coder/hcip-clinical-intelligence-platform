/** TypeScript types matching the FastAPI backend response models. */

export interface Citation {
  ref_number:      number;
  chunk_id:        string;
  document_id:     string;
  source:          "qdrant" | "elasticsearch" | "neo4j" | "pubmed";
  is_external:     boolean;
  // PubMed-specific
  title?:          string;
  authors?:        string[];
  journal?:        string;
  year?:           string;
  doi?:            string;
  pmid?:           string;
  url?:            string;
  // Internal-specific
  document_type?:  string;
  specialty?:      string;
  section?:        string;
  approval_status?: string;
  citation_score?: number;
}

export interface SafetyFlag {
  flag_type:   string;   // "drug_interaction" | "high_risk_medication" | etc.
  severity:    string;   // "critical" | "high" | "medium" | "low"
  description: string;
  pattern?:    string;
}

export interface QueryResult {
  query_text:          string;
  final_response:      string;
  citations:           Citation[];
  confidence_score:    number;
  safety_flags:        SafetyFlag[];
  requires_escalation: boolean;
  escalation_reason:   string | null;
  cache_hit:           boolean;
  cache_layer:         string | null;
  total_latency_ms:    number;
  errors:              string[];
  trace_id:            string;
  agent_timings:       Record<string, number>;
}

export interface APIResponse<T> {
  success: boolean;
  data:    T;
}

export interface ErrorResponse {
  success: false;
  error:   string;
  detail?: string;
}

export interface KnowledgeBase {
  id:           string;
  label:        string;
  description?: string;
}

export const KNOWLEDGE_BASES: KnowledgeBase[] = [
  { id: "kb-clinical-2024",    label: "Clinical Guidelines 2024",  description: "Evidence-based clinical practice guidelines" },
  { id: "kb-pharmacology",     label: "Pharmacology Reference",    description: "Drug information, interactions, and dosing"  },
  { id: "kb-cardiology",       label: "Cardiology Protocols",      description: "Cardiac care protocols and guidelines"       },
  { id: "kb-oncology",         label: "Oncology Protocols",        description: "Cancer treatment protocols and pathways"     },
  { id: "kb-emergency",        label: "Emergency Medicine",        description: "Emergency care protocols and procedures"     },
];

// Auth & User Management

export type UserRole = 'admin' | 'physician' | 'nurse' | 'pharmacist';

export interface User {
  id:               string;
  name:             string;
  email:            string;
  role:             UserRole;
  organization_id:  string;
  allowed_kb_ids:   string[];
  is_active:        boolean;
  created_at:       string;
  last_login?:      string;
  // api_key is NOT returned to frontend for security
}

export interface AuthSession {
  user:      User;
  token:     string;   // the API key used to call backend
  expiresAt: number;
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin:       'Administrator',
  physician:   'Physician',
  nurse:       'Nurse',
  pharmacist:  'Pharmacist',
};

export const ROLE_COLORS: Record<UserRole, string> = {
  admin:       'bg-purple-100 text-purple-700 border-purple-200',
  physician:   'bg-blue-100 text-blue-700 border-blue-200',
  nurse:       'bg-green-100 text-green-700 border-green-200',
  pharmacist:  'bg-amber-100 text-amber-700 border-amber-200',
};

// Role-based KB access rules
export const ROLE_KB_ACCESS: Record<UserRole, string[]> = {
  admin:       ['kb-clinical-2024', 'kb-pharmacology', 'kb-cardiology', 'kb-oncology', 'kb-emergency'],
  physician:   ['kb-clinical-2024', 'kb-pharmacology', 'kb-cardiology', 'kb-oncology', 'kb-emergency'],
  nurse:       ['kb-clinical-2024', 'kb-emergency'],
  pharmacist:  ['kb-pharmacology', 'kb-clinical-2024'],
};
