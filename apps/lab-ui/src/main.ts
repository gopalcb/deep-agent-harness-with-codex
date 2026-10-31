import { Component, OnDestroy } from "@angular/core";
import { bootstrapApplication } from "@angular/platform-browser";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";

@Component({
  selector: "lab-app",
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: ` <header>
      <div>
        <p class="eyebrow">CODEX ENGINEERING LAB</p>
        <h1>Lab control room</h1>
      </div>
      <span class="mode">{{ mode }} execution</span>
    </header>
    <main>
      <section class="compose" aria-labelledby="request-title">
        <p class="eyebrow">WORKFLOW REQUEST</p>
        <h2 id="request-title">What should change?</h2>
        <p class="muted">
          Plan the work, follow each task, inspect the evidence.
        </p>
        <form (ngSubmit)="start()" #form="ngForm">
          <label for="workflow">Workflow</label
          ><select id="workflow" name="workflow" [(ngModel)]="workflow">
            <option value="direct">Direct · one focused task</option>
            <option value="planned">Planned · implementation and review</option>
          </select>
          <label for="instruction">Engineering request</label
          ><textarea
            id="instruction"
            name="instruction"
            [(ngModel)]="instruction"
            required
            maxlength="32000"
            rows="6"
            placeholder="Describe the change and its acceptance checks"
          ></textarea>
          <details>
            <summary>Visual target and approvals</summary>
            <label for="url">Page URL</label
            ><input
              id="url"
              name="url"
              [(ngModel)]="url"
              type="url"
              placeholder="https://example.test/dashboard"
            /><label for="selector">Element selector</label
            ><input
              id="selector"
              name="selector"
              [(ngModel)]="selector"
              placeholder="#filter-card"
            /><label class="check"
              ><input
                type="checkbox"
                name="sensitive"
                [(ngModel)]="sensitive"
              />
              Require approval before execution</label
            >
          </details>
          <button type="submit" [disabled]="busy || !instruction.trim()">
            {{ busy ? "Starting workflow…" : "Start workflow" }}
          </button>
        </form>
        <p class="note">
          {{
            mode === "demo"
              ? "Local simulation. Tasks exercise the workflow and real fixture checks; no model is called."
              : "Live adapters configured. Results still require verification."
          }}
        </p>
        <details>
          <summary>Live access</summary>
          <form (submit)="$event.preventDefault()">
            <label for="access">Browser access token</label
            ><input
              id="access"
              name="access"
              type="password"
              [(ngModel)]="access"
              autocomplete="off"
            />
            <p class="note">Kept in this page’s memory only.</p>
          </form>
        </details>
      </section>
      <section class="monitor" aria-labelledby="run-title">
        <div class="section-head">
          <div>
            <p class="eyebrow">EXECUTION</p>
            <h2 id="run-title">
              {{ run ? "Workflow " + run.status : "Ready when you are" }}
            </h2>
          </div>
          <button
            class="secondary"
            *ngIf="run && active"
            (click)="action('cancel')"
            [disabled]="busy"
          >
            Cancel run
          </button>
        </div>
        <p role="alert" class="error" *ngIf="error">{{ error }}</p>
        <div class="empty" *ngIf="!run">
          <span class="empty-mark">↳</span>
          <h3>Your execution path appears here</h3>
          <p>
            Choose a workflow and describe a change. Each task will carry its
            own status and verification evidence.
          </p>
        </div>
        <ng-container *ngIf="run"
          ><p class="run-id">{{ run.run_id }}</p>
          <p aria-live="polite" class="status">
            {{ run.status }} · {{ connection }}
          </p>
          <div class="approval" *ngIf="run.status === 'waiting_approval'">
            <h3>Approval required</h3>
            <p>Review the current assignment before allowing execution.</p>
            <pre>{{
              run.approval || run.approval_digest || run.request | json
            }}</pre>
            <button
              (click)="action('approval', { approved: true })"
              [disabled]="busy"
            >
              Approve action</button
            ><button
              class="secondary"
              (click)="action('approval', { approved: false })"
              [disabled]="busy"
            >
              Deny
            </button>
          </div>
          <ol class="tasks">
            <li *ngFor="let task of tasks">
              <div class="task-heading">
                <strong>{{ task.task_id }}</strong
                ><span>{{
                  task.status || result(task.task_id)?.status || "pending"
                }}</span>
              </div>
              <p>
                {{ task.role }}
                <span *ngIf="task.depends_on?.length"
                  >· after {{ task.depends_on.join(", ") }}</span
                >
              </p>
              <p class="note" *ngIf="result(task.task_id)?.thread_id">
                Thread {{ result(task.task_id).thread_id }}
              </p>
              <div
                *ngFor="let check of result(task.task_id)?.checks"
                class="check-result"
              >
                {{ check.id }} · {{ check.status }}
              </div>
              <p class="error" *ngIf="result(task.task_id)?.error">
                {{ result(task.task_id).error }}
              </p>
              <p
                class="note"
                *ngFor="let artifact of result(task.task_id)?.artifacts"
              >
                Artifact: {{ artifact }}
              </p>
            </li>
          </ol>
          <div class="section-head">
            <h3>Event timeline</h3>
            <label class="filter"
              >Agent<select [(ngModel)]="agent">
                <option value="">All agents</option>
                <option *ngFor="let name of agents" [value]="name">
                  {{ name }}
                </option>
              </select></label
            >
          </div>
          <p class="note" *ngIf="!events.length">
            Waiting for the first recorded event.
          </p>
          <ol class="timeline">
            <li *ngFor="let event of filteredEvents">
              <time>{{ event.timestamp | date: "HH:mm:ss" }}</time>
              <div>
                <strong>{{ event.event_type }}</strong>
                <p>{{ event.agent_id }} · {{ event.status }}</p>
                <small *ngIf="event.metadata?.usage"
                  >Reported usage {{ event.metadata.usage | json }}</small
                >
              </div>
            </li>
          </ol>
          <p class="note">
            Python contexts compact at 70% of configured usable capacity. Codex
            and native-agent context occupancy is unavailable; usage counts are
            not occupancy.
          </p>
        </ng-container>
      </section>
    </main>`,
})
class App implements OnDestroy {
  instruction = "Add a filter with API and frontend verification";
  workflow = "direct";
  url = "";
  selector = "";
  sensitive = false;
  access = "";
  mode = "demo";
  busy = false;
  error = "";
  run: any = null;
  events: any[] = [];
  agent = "";
  connection = "connecting";
  private timer: ReturnType<typeof setInterval> | null = null;
  private stream: AbortController | null = null;
  private requestKey = crypto.randomUUID();
  private lastPayload = "";
  constructor() {
    void this.request("/api/config")
      .then((c) => (this.mode = c.mode))
      .catch(
        () =>
          (this.error =
            "Cannot reach the lab. Start both services and reload."),
      );
  }
  get active() {
    return (
      this.run &&
      !["succeeded", "failed", "cancelled", "blocked"].includes(this.run.status)
    );
  }
  get tasks(): any[] {
    const values: any[] = Array.isArray(this.run?.tasks)
      ? this.run.tasks
      : Object.values(this.run?.tasks ?? {});
    return values.map((t) => ({ ...t.assignment, ...t }));
  }
  result(id: string): any {
    return (
      this.run?.results?.[id] ??
      this.tasks.find((t) => t.task_id === id)?.result
    );
  }
  get agents(): string[] {
    return [...new Set(this.events.map((e) => e.agent_id))];
  }
  get filteredEvents() {
    return this.events
      .filter((e) => !this.agent || e.agent_id === this.agent)
      .slice(-200);
  }
  async request(path: string, body?: unknown): Promise<any> {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        ...(this.access ? { Authorization: "Bearer " + this.access } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok)
      throw new Error(
        `Request failed (${response.status}). ${await response.text()}`,
      );
    return response.json();
  }
  async start() {
    this.busy = true;
    this.error = "";
    try {
      const payload = {
        project_id: "lab",
        workflow_id: this.workflow,
        instruction: this.instruction,
        visual_target:
          this.url || this.selector
            ? { url: this.url, selector: this.selector }
            : null,
        risk: this.sensitive ? "sensitive" : "workspace-write",
      };
      const serialized = JSON.stringify(payload);
      if (serialized !== this.lastPayload) {
        this.requestKey = crypto.randomUUID();
        this.lastPayload = serialized;
      }
      this.run = await this.request("/api/runs", {
        ...payload,
        idempotency_key: this.requestKey,
      });
      this.events = [];
      this.watch();
    } catch (e) {
      this.error = String(e);
    } finally {
      this.busy = false;
    }
  }
  async action(name: string, body: unknown = {}) {
    this.busy = true;
    this.error = "";
    try {
      this.run = await this.request(
        `/api/runs/${this.run.run_id}/${name}?project_id=lab`,
        body,
      );
    } catch (e) {
      this.error = String(e);
    } finally {
      this.busy = false;
    }
  }
  watch() {
    if (this.timer) clearInterval(this.timer);
    this.stream?.abort();
    this.stream = new AbortController();
    void this.readEvents(this.stream.signal);
    this.timer = setInterval(() => {
      void this.request(`/api/runs/${this.run.run_id}?project_id=lab`)
        .then((r) => {
          this.run = r;
          if (!this.active && this.timer) {
            clearInterval(this.timer);
            this.timer = null;
          }
        })
        .catch((e) => (this.error = String(e)));
    }, 700);
  }
  async readEvents(signal: AbortSignal) {
    let cursor = 0;
    while (!signal.aborted) {
      try {
        const response = await fetch(
          `/api/runs/${this.run.run_id}/events?project_id=lab&after=${cursor}`,
          {
            signal,
            headers: this.access
              ? { Authorization: "Bearer " + this.access }
              : {},
          },
        );
        if (!response.ok || !response.body)
          throw new Error("Event stream unavailable");
        this.connection = "connected";
        const reader = response.body.getReader(),
          decoder = new TextDecoder();
        let buffer = "";
        try {
          while (!signal.aborted) {
            const part = await reader.read();
            if (part.done) break;
            buffer += decoder.decode(part.value, { stream: true });
            let boundary;
            while ((boundary = buffer.indexOf("\n\n")) >= 0) {
              const block = buffer.slice(0, boundary);
              buffer = buffer.slice(boundary + 2);
              const line = block
                .split("\n")
                .find((l) => l.startsWith("data: "));
              if (line) {
                const event = JSON.parse(line.slice(6));
                cursor = Math.max(cursor, event.sequence);
                if (!this.events.some((e) => e.event_id === event.event_id))
                  this.events = [...this.events.slice(-999), event];
              }
            }
          }
        } finally {
          await reader.cancel();
        }
      } catch {
        if (signal.aborted) return;
        this.connection = "reconnecting";
      }
      await new Promise((done) => setTimeout(done, 1000));
    }
  }
  ngOnDestroy() {
    if (this.timer) clearInterval(this.timer);
    this.stream?.abort();
  }
}
bootstrapApplication(App).catch(console.error);
