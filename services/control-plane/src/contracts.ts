import { z } from "zod";
const id = z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/);
export const assignmentSchema = z
  .object({
    project_id: id,
    run_id: id,
    task_id: id,
    role: z.string().default("backend"),
    workspace_ref: z.string().default("default"),
    instruction: z.string().min(1).max(32000),
    context_refs: z.array(z.string()).default([]),
    depends_on: z.array(z.string()).default([]),
    checks: z.array(z.string()).min(1),
    risk: z.enum(["workspace-write", "read-only", "sensitive"]),
    revision: z.number().int().positive().default(1),
    idempotency_key: z.string().min(1).max(160),
  })
  .strict();
export type Assignment = z.infer<typeof assignmentSchema>;
export type Result = {
  project_id: string;
  run_id: string;
  task_id: string;
  status: string;
  thread_id: string | null;
  artifacts: string[];
  checks: { id: string; status: string; exit_code: number | null }[];
  error: string | null;
  usage: Record<string, number>;
};
export class BoundaryError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export function scopeKey(project: string, run: string, task: string): string {
  return JSON.stringify([project, run, task]);
}
