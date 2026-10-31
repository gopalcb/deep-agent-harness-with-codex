import { Codex } from "@openai/codex-sdk";
import {
  mkdirSync,
  realpathSync,
  writeFileSync,
  lstatSync,
  existsSync,
} from "node:fs";
import { join, resolve, relative, isAbsolute } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import {
  Assignment,
  assignmentSchema,
  BoundaryError,
  Result,
  scopeKey,
} from "./contracts.js";
import { TaskStore } from "./store.js";
const exec = promisify(execFile);
export type Check = { argv: string[]; timeout_ms: number };
export type ExecutionConfig = {
  mode: "demo" | "live";
  project: string;
  root: string;
  workspaces: Record<string, string>;
  checks: Record<string, Check>;
};
export interface Transport {
  run(
    task: Assignment,
    workspace: string,
    threadId: string | null,
    signal: AbortSignal,
    onEvent: (event: any) => void,
  ): Promise<void>;
}
/** Only this transport constructs Codex threads; Python never owns the SDK. */
export class SDKTransport implements Transport {
  private codex = new Codex();
  async run(
    task: Assignment,
    workspace: string,
    threadId: string | null,
    signal: AbortSignal,
    onEvent: (event: any) => void,
  ): Promise<void> {
    const options = {
      workingDirectory: workspace,
      sandboxMode:
        task.risk === "read-only"
          ? ("read-only" as const)
          : ("workspace-write" as const),
      approvalPolicy: "never" as const,
      networkAccessEnabled: false,
    };
    const thread = threadId
      ? this.codex.resumeThread(threadId, options)
      : this.codex.startThread(options);
    const stream = await thread.runStreamed(task.instruction, { signal });
    for await (const event of stream.events) onEvent(event);
  }
}
export class DemoTransport implements Transport {
  async run(
    task: Assignment,
    workspace: string,
    threadId: string | null,
    signal: AbortSignal,
    onEvent: (event: any) => void,
  ): Promise<void> {
    onEvent({
      type: "thread.started",
      thread_id: threadId ?? `demo-${crypto.randomUUID()}`,
    });
    await new Promise<void>((done, reject) => {
      const timer = setTimeout(done, 80);
      signal.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          reject(new Error("aborted"));
        },
        { once: true },
      );
    });
    if (signal.aborted) throw new Error("aborted");
    writeFileSync(
      join(workspace, "result.json"),
      JSON.stringify({ verified: true, task: task.task_id }),
    );
    onEvent({ type: "item.completed", item: { type: "file_change" } });
    onEvent({
      type: "turn.completed",
      usage: { input_tokens: 0, output_tokens: 0, cached_input_tokens: 0 },
    });
  }
}
export class ExecutionService {
  active = new Map<string, AbortController>();
  jobs = new Set<Promise<void>>();
  constructor(
    public store: TaskStore,
    public config: ExecutionConfig,
    public transport: Transport,
  ) {}
  workspace(ref: string): string {
    const configured = this.config.workspaces[ref];
    if (!configured)
      throw new BoundaryError(403, "Workspace is not registered");
    const root = realpathSync(this.config.root),
      path = realpathSync(resolve(root, configured)),
      rel = relative(root, path);
    if (rel.startsWith("..") || isAbsolute(rel))
      throw new BoundaryError(403, "Workspace escapes approved root");
    const dataRelative = relative(path, this.store.artifactRoot);
    if (
      this.config.mode === "live" &&
      (dataRelative === "" ||
        (!dataRelative.startsWith("..") && !isAbsolute(dataRelative)))
    ) {
      throw new BoundaryError(
        403,
        "Execution data must be outside writable workspace",
      );
    }
    return path;
  }
  start(payload: unknown): Result {
    const parsed = assignmentSchema.safeParse(payload);
    if (!parsed.success)
      throw new BoundaryError(422, "Invalid task assignment");
    const task = parsed.data;
    if (task.project_id !== this.config.project)
      throw new BoundaryError(403, "Project is not registered");
    if (task.risk === "sensitive")
      throw new BoundaryError(
        403,
        "Sensitive operations require an external approved executor; not supported by this coding adapter",
      );
    for (const check of task.checks)
      if (!this.config.checks[check])
        throw new BoundaryError(422, "Unknown verification check");
    const admitted = this.store.admit(task, this.workspace(task.workspace_ref));
    if (admitted.created) this.launch(admitted.key);
    return admitted.result;
  }
  launch(key: string, feedback?: string): void {
    const job = this.execute(key, feedback);
    this.jobs.add(job);
    void job.finally(() => this.jobs.delete(job));
  }
  async execute(key: string, feedback?: string): Promise<void> {
    const { assignment, workspace, result } = this.store.get(key),
      controller = new AbortController();
    this.active.set(key, controller);
    result.status = "running";
    result.error = null;
    result.checks = [];
    this.store.save(key, result);
    this.store.event(key, "agent.delegated");
    let completed = false,
      failed = false;
    try {
      await this.transport.run(
        { ...assignment, instruction: feedback ?? assignment.instruction },
        workspace,
        result.thread_id,
        controller.signal,
        (event) => {
          if (event.type === "thread.started")
            result.thread_id = event.thread_id;
          if (event.type === "turn.completed") {
            completed = true;
            result.usage = event.usage ?? {};
          }
          if (event.type === "turn.failed" || event.type === "error")
            failed = true;
          this.store.save(key, result);
          // No prompt, tool arguments, command output, or SDK error text enters the event log.
          this.store.event(key, "codex.item", {
            sdk_type: event.type,
            item_type: event.item?.type ?? null,
            usage: event.type === "turn.completed" ? event.usage : undefined,
          });
        },
      );
      if (controller.signal.aborted) {
        result.status = "cancelled";
      } else if (!completed || failed) {
        result.status = "failed";
        result.error = "Codex turn did not complete successfully";
      } else {
        for (const id of assignment.checks) {
          const check = this.config.checks[id];
          try {
            await exec(check.argv[0], check.argv.slice(1), {
              cwd: workspace,
              timeout: check.timeout_ms,
              maxBuffer: 1024 * 1024,
              signal: controller.signal,
            });
            result.checks.push({ id, status: "passed", exit_code: 0 });
          } catch (error: any) {
            result.checks.push({
              id,
              status: "failed",
              exit_code: typeof error.code === "number" ? error.code : null,
            });
          }
        }
        result.status = controller.signal.aborted
          ? "cancelled"
          : result.checks.length > 0 &&
              result.checks.every((c) => c.status === "passed")
            ? "succeeded"
            : "failed";
        if (result.status === "failed")
          result.error = "Registered verification failed";
        const artifactDir = join(
          this.store.artifactRoot,
          assignment.run_id,
          assignment.task_id,
        );
        const relativeArtifact = relative(this.store.artifactRoot, artifactDir);
        let component = this.store.artifactRoot;
        for (const part of ["", ...relativeArtifact.split("/")]) {
          component = join(component, part);
          if (existsSync(component) && lstatSync(component).isSymbolicLink()) {
            throw new BoundaryError(403, "Artifact symlink rejected");
          }
          mkdirSync(component, { recursive: true });
        }
        try {
          const diff = await exec(
            "git",
            ["diff", "--no-ext-diff", "--binary"],
            { cwd: workspace, maxBuffer: 2 * 1024 * 1024, timeout: 10000 },
          );
          const artifactFile = join(
            artifactDir,
            `changes-${crypto.randomUUID()}.diff`,
          );
          writeFileSync(artifactFile, diff.stdout, { flag: "wx" });
          result.artifacts.push(
            relative(this.store.artifactRoot, artifactFile),
          );
        } catch {
          /* Non-Git demo fixtures explicitly carry no diff evidence. */
        }
      }
    } catch {
      result.status = controller.signal.aborted ? "cancelled" : "uncertain";
      result.error = controller.signal.aborted
        ? "Execution stream terminated after cancellation"
        : "Transport interrupted; reconcile before retry";
    } finally {
      this.active.delete(key);
      this.store.save(key, result);
      this.store.event(key, "node.completed", { checks: result.checks });
      if (["succeeded", "failed", "cancelled"].includes(result.status))
        this.store.release(key);
    }
  }
  get(project: string, run: string, task: string): Result {
    return this.store.get(scopeKey(project, run, task)).result;
  }
  cancel(project: string, run: string, task: string): Result {
    const key = scopeKey(project, run, task),
      row = this.store.get(key);
    if (["succeeded", "failed", "cancelled"].includes(row.result.status))
      return row.result;
    const controller = this.active.get(key);
    row.result.status = controller ? "cancel_requested" : "uncertain";
    this.store.save(key, row.result);
    controller?.abort();
    return row.result;
  }
  resume(
    project: string,
    run: string,
    task: string,
    feedback: string,
    idem: string,
  ): Result {
    if (!feedback?.trim() || !idem?.trim())
      throw new BoundaryError(422, "Feedback and idempotency key required");
    const key = scopeKey(project, run, task);
    if (this.store.resume(key, idem, feedback)) this.launch(key, feedback);
    return this.store.get(key).result;
  }
  async drain(): Promise<void> {
    await Promise.all(this.jobs);
  }
}
