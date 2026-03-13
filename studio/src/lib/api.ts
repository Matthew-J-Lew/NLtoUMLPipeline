import type { ProjectSnapshot, ProjectSummary } from "../types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let detail = `Request failed with ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // Ignore JSON parse errors for non-JSON failures.
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export async function fetchProjects(): Promise<ProjectSummary[]> {
  const payload = await request<{ projects: ProjectSummary[] }>("/api/projects");
  return payload.projects;
}

export async function fetchProject(bundleName: string): Promise<ProjectSnapshot> {
  const payload = await request<{ project: ProjectSnapshot }>(`/api/projects/${bundleName}`);
  return payload.project;
}

export async function runPipeline(input: {
  text: string;
  bundle_name: string;
  use_mock: boolean;
  max_repairs: number;
}): Promise<ProjectSnapshot> {
  const payload = await request<{ project: ProjectSnapshot }>("/api/projects/run", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.project;
}

export async function agentEdit(
  bundleName: string,
  input: { request: string; use_mock: boolean; max_repairs: number },
): Promise<ProjectSnapshot> {
  const payload = await request<{ project: ProjectSnapshot }>(`/api/projects/${bundleName}/agent-edit`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.project;
}

export async function roundTrip(bundleName: string, puml: string): Promise<ProjectSnapshot> {
  const payload = await request<{ project: ProjectSnapshot }>(`/api/projects/${bundleName}/roundtrip`, {
    method: "POST",
    body: JSON.stringify({ puml }),
  });
  return payload.project;
}

export async function refine(
  bundleName: string,
  input: { use_mock: boolean; max_iters: number; max_patch_repairs: number },
): Promise<ProjectSnapshot> {
  const payload = await request<{ project: ProjectSnapshot }>(`/api/projects/${bundleName}/refine`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.project;
}


export async function renderPlantUML(puml: string): Promise<{ svg: string; renderer?: string }> {
  const response = await fetch(`${API_BASE}/api/render/plantuml`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ puml }),
  });

  if (!response.ok) {
    let detail = `Request failed with ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // Ignore JSON parse errors for non-JSON failures.
    }
    throw new Error(detail);
  }

  return (await response.json()) as { svg: string; renderer?: string };
}
