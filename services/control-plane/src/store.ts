import { DatabaseSync } from "node:sqlite";
import { mkdirSync, realpathSync } from "node:fs";
import { dirname, relative, isAbsolute, join } from "node:path";
import { createHash } from "node:crypto";
import { Assignment, Result, BoundaryError, scopeKey } from "./contracts.js";
export function digest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}
/** Transactional admission owns workspace exclusivity even when Python is bypassed. */
export class TaskStore {
  db: DatabaseSync;
  artifactRoot: string;
  constructor(path: string) {
    mkdirSync(dirname(path), { recursive: true });
    this.artifactRoot = join(realpathSync(dirname(path)), "artifacts");
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS tasks (key TEXT PRIMARY KEY, project TEXT, run TEXT, idem TEXT, hash TEXT, workspace TEXT, assignment TEXT, result TEXT, UNIQUE(project,run,idem));
      CREATE TABLE IF NOT EXISTS leases (workspace TEXT PRIMARY KEY, task TEXT UNIQUE);
      CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, payload TEXT);
      CREATE TABLE IF NOT EXISTS resumes (task TEXT, idem TEXT, hash TEXT, PRIMARY KEY(task,idem));`);
    // A restart cannot prove the previous SDK process stopped; retain its lease.
    for (const row of this.db.prepare("SELECT key,result FROM tasks").all() as {
      key: string;
      result: string;
    }[]) {
      const result = JSON.parse(row.result) as Result;
      if (["pending", "running", "cancel_requested"].includes(result.status)) {
        result.status = "uncertain";
        result.error =
          "Owner restarted; reconcile execution before reusing workspace";
        this.save(row.key, result);
      }
    }
  }
  admit(
    task: Assignment,
    workspace: string,
  ): { key: string; result: Result; created: boolean } {
    const key = scopeKey(task.project_id, task.run_id, task.task_id),
      hash = digest(task);
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const existing = this.db
        .prepare(
          "SELECT key,hash,result FROM tasks WHERE key=? OR (project=? AND run=? AND idem=?)",
        )
        .get(key, task.project_id, task.run_id, task.idempotency_key) as
        { key: string; hash: string; result: string } | undefined;
      if (existing) {
        if (existing.hash !== hash)
          throw new BoundaryError(409, "Idempotency or task identity conflict");
        this.db.exec("COMMIT");
        return {
          key: existing.key,
          result: JSON.parse(existing.result),
          created: false,
        };
      }
      if (this.overlaps(workspace))
        throw new BoundaryError(409, "Workspace already leased");
      const result: Result = {
        project_id: task.project_id,
        run_id: task.run_id,
        task_id: task.task_id,
        status: "pending",
        thread_id: null,
        artifacts: [],
        checks: [],
        error: null,
        usage: {},
      };
      this.db
        .prepare("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)")
        .run(
          key,
          task.project_id,
          task.run_id,
          task.idempotency_key,
          hash,
          workspace,
          JSON.stringify(task),
          JSON.stringify(result),
        );
      this.db.prepare("INSERT INTO leases VALUES (?,?)").run(workspace, key);
      this.db.exec("COMMIT");
      return { key, result, created: true };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }
  overlaps(workspace: string): boolean {
    const contains = (parent: string, child: string): boolean => {
      const path = relative(parent, child);
      return path === "" || (!path.startsWith("..") && !isAbsolute(path));
    };
    return (
      this.db.prepare("SELECT workspace FROM leases").all() as {
        workspace: string;
      }[]
    ).some(
      (row) =>
        contains(row.workspace, workspace) ||
        contains(workspace, row.workspace),
    );
  }
  get(key: string): {
    assignment: Assignment;
    result: Result;
    workspace: string;
  } {
    const row = this.db
      .prepare("SELECT assignment,result,workspace FROM tasks WHERE key=?")
      .get(key) as
      { assignment: string; result: string; workspace: string } | undefined;
    if (!row) throw new BoundaryError(404, "Task not found in scope");
    return {
      assignment: JSON.parse(row.assignment),
      result: JSON.parse(row.result),
      workspace: row.workspace,
    };
  }
  save(key: string, result: Result): void {
    this.db
      .prepare("UPDATE tasks SET result=? WHERE key=?")
      .run(JSON.stringify(result), key);
  }
  release(key: string): void {
    this.db.prepare("DELETE FROM leases WHERE task=?").run(key);
  }
  resume(key: string, idem: string, feedback: string): boolean {
    const row = this.get(key);
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const old = this.db
        .prepare("SELECT hash FROM resumes WHERE task=? AND idem=?")
        .get(key, idem) as { hash: string } | undefined;
      if (old) {
        if (old.hash !== digest(feedback))
          throw new BoundaryError(409, "Resume idempotency conflict");
        this.db.exec("COMMIT");
        return false;
      }
      if (!["failed", "succeeded"].includes(row.result.status))
        throw new BoundaryError(
          409,
          "Task cannot resume until execution is reconciled",
        );
      if (this.overlaps(row.workspace))
        throw new BoundaryError(409, "Workspace already leased");
      this.db
        .prepare("INSERT INTO resumes VALUES (?,?,?)")
        .run(key, idem, digest(feedback));
      this.db
        .prepare("INSERT INTO leases VALUES (?,?)")
        .run(row.workspace, key);
      row.result.status = "pending";
      this.save(key, row.result);
      this.db.exec("COMMIT");
      return true;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }
  event(
    key: string,
    type: string,
    metadata: Record<string, unknown> = {},
  ): void {
    const { assignment, result } = this.get(key);
    const payload = {
      event_id: crypto.randomUUID(),
      project_id: assignment.project_id,
      run_id: assignment.run_id,
      workflow_id: "execution",
      node_id: assignment.task_id,
      agent_id: assignment.role,
      codex_thread_id: result.thread_id,
      parent_event_id: null,
      timestamp: new Date().toISOString(),
      event_type: type,
      duration_ms: 0,
      status: result.status,
      metadata,
    };
    this.db
      .prepare("INSERT INTO events(task,payload) VALUES (?,?)")
      .run(key, JSON.stringify(payload));
  }
  events(key: string, after: number): unknown[] {
    this.get(key);
    return (
      this.db
        .prepare(
          "SELECT sequence,payload FROM events WHERE task=? AND sequence>? ORDER BY sequence LIMIT 200",
        )
        .all(key, after) as { sequence: number; payload: string }[]
    ).map((r) => ({ ...JSON.parse(r.payload), sequence: r.sequence }));
  }
  close(): void {
    this.db.close();
  }
}
