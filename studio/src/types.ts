export type Diagnostic = {
  severity?: string;
  message?: string;
  path?: string;
  code?: string;
};

export type ValidationReport = {
  ok?: boolean;
  diagnostics?: Diagnostic[];
  patches?: Array<Record<string, unknown>>;
};

export type Transition = {
  from: string;
  to: string;
  triggers?: Array<Record<string, unknown>>;
  guards?: Array<Record<string, unknown>>;
  actions?: Array<Record<string, unknown>>;
};

export type State = {
  id: string;
  label?: string;
};

export type IR = {
  version?: string;
  devices?: Array<Record<string, unknown>>;
  stateMachine?: {
    initial?: string;
    states?: State[];
    transitions?: Transition[];
  };
};

export type Revision = {
  kind?: string;
  dir?: string;
  created_at?: string;
  diff_against?: string;
  source_puml?: string;
  ok?: boolean;
  iterations?: number;
  stop_reason?: string;
};

export type ProjectSummary = {
  bundle_name: string;
  updated_at?: string | null;
  revision_count: number;
  ok?: boolean | null;
  states: number;
  transitions: number;
};

export type ProjectSnapshot = {
  bundle_name: string;
  exists: boolean;
  paths: Record<string, string>;
  summary: {
    updated_at?: string;
    revision_count?: number;
    current_pointer?: string;
    states?: number;
    transitions?: number;
    ok?: boolean | null;
    diagnostic_counts?: Record<string, number>;
  };
  current: {
    ir?: IR | null;
    validation?: ValidationReport | null;
    puml?: string | null;
    diff?: Record<string, unknown> | null;
  };
  baseline: {
    ir?: IR | null;
    validation?: ValidationReport | null;
    puml?: string | null;
  };
  revisions: Revision[];
  manifest: Record<string, unknown>;
};
