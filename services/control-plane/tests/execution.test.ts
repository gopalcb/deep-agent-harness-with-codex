import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, mkdirSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { TaskStore } from "../src/store.js";
import {
  DemoTransport,
  ExecutionService,
  ExecutionConfig,
} from "../src/execution.js";
const task = {
  project_id: "lab",
  run_id: "run1",
  task_id: "task1",
  role: "backend",
  workspace_ref: "default",
  instruction: "fixture",
  context_refs: [],
  depends_on: [],
  checks: ["fixture"],
  risk: "workspace-write",
  revision: 1,
  idempotency_key: "once",
};
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "codex-lab-"));
  const config: ExecutionConfig = {
    mode: "demo",
    project: "lab",
    root,
    workspaces: { default: "." },
    checks: {
      fixture: {
        argv: [
          process.execPath,
          "-e",
          "if(!require('fs').existsSync('result.json'))process.exit(1)",
        ],
        timeout_ms: 3000,
      },
    },
  };
  const store = new TaskStore(join(root, "tasks.sqlite"));
  return {
    root,
    store,
    service: new ExecutionService(store, config, new DemoTransport()),
  };
}
test("admission is idempotent, scoped and excludes concurrent writers", async () => {
  const f = fixture();
  try {
    f.service.start(task);
    assert.equal(f.service.start(task).task_id, "task1");
    assert.throws(
      () => f.service.start({ ...task, instruction: "different" }),
      /conflict/,
    );
    assert.throws(
      () =>
        f.service.start({
          ...task,
          task_id: "task2",
          idempotency_key: "other",
        }),
      /leased/,
    );
    assert.throws(() => f.service.get("other", "run1", "task1"), /not found/);
    await f.service.drain();
    const result = f.service.get("lab", "run1", "task1");
    assert.equal(result.status, "succeeded");
    assert.equal(result.checks[0].status, "passed");
    assert.ok(
      f.store.events(JSON.stringify(["lab", "run1", "task1"]), 0).length > 1,
    );
  } finally {
    await f.service.drain();
    f.store.close();
    rmSync(f.root, { recursive: true, force: true });
  }
});
test("failed checks prevent success; resume uses existing thread", async () => {
  const f = fixture();
  try {
    f.service.config.checks.fixture.argv = [
      process.execPath,
      "-e",
      "process.exit(3)",
    ];
    f.service.start(task);
    await f.service.drain();
    const before = f.service.get("lab", "run1", "task1");
    assert.equal(before.status, "failed");
    f.service.config.checks.fixture.argv = [
      process.execPath,
      "-e",
      "process.exit(0)",
    ];
    f.service.resume("lab", "run1", "task1", "repair", "repair1");
    await f.service.drain();
    assert.equal(
      f.service.get("lab", "run1", "task1").thread_id,
      before.thread_id,
    );
    assert.equal(f.service.get("lab", "run1", "task1").status, "succeeded");
    assert.throws(
      () => f.service.resume("lab", "run1", "task1", "changed", "repair1"),
      /conflict/,
    );
  } finally {
    await f.service.drain();
    f.store.close();
    rmSync(f.root, { recursive: true, force: true });
  }
});
test("restart retains unresolved lease and cancellation only finishes after transport", async () => {
  const f = fixture();
  try {
    f.store.admit(task as any, f.root);
    f.store.close();
    f.store = new TaskStore(join(f.root, "tasks.sqlite"));
    assert.equal(
      f.store.get(JSON.stringify(["lab", "run1", "task1"])).result.status,
      "uncertain",
    );
    assert.throws(
      () =>
        f.store.admit(
          { ...task, task_id: "task2", idempotency_key: "other" } as any,
          f.root,
        ),
      /leased/,
    );
  } finally {
    f.store.close();
    rmSync(f.root, { recursive: true, force: true });
  }
});
test("cancel, sensitive denial, unknown checks and symlink containment", async () => {
  const f = fixture();
  const outside = mkdtempSync(join(tmpdir(), "outside-"));
  try {
    assert.throws(
      () => f.service.start({ ...task, risk: "sensitive" }),
      /Sensitive/,
    );
    assert.throws(() => f.service.start({ ...task, checks: [] }), /Invalid/);
    assert.throws(
      () => f.service.start({ ...task, checks: ["arbitrary shell"] }),
      /Unknown/,
    );
    symlinkSync(outside, join(f.root, "escape"));
    f.service.config.workspaces.escape = "escape";
    assert.throws(
      () => f.service.start({ ...task, workspace_ref: "escape" }),
      /escapes/,
    );
    f.service.start(task);
    assert.equal(
      f.service.cancel("lab", "run1", "task1").status,
      "cancel_requested",
    );
    await f.service.drain();
    assert.equal(f.service.get("lab", "run1", "task1").status, "cancelled");
  } finally {
    await f.service.drain();
    f.store.close();
    rmSync(f.root, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});

test("leases reject nested writers in both directions", () => {
  const f = fixture();
  try {
    f.store.admit(task as any, join(f.root, "repo"));
    assert.throws(
      () =>
        f.store.admit(
          { ...task, task_id: "nested", idempotency_key: "nested" } as any,
          join(f.root, "repo", "src"),
        ),
      /leased/,
    );
    assert.throws(
      () =>
        f.store.admit(
          { ...task, task_id: "parent", idempotency_key: "parent" } as any,
          f.root,
        ),
      /leased/,
    );
    assert.ok(
      f.store.admit(
        { ...task, task_id: "separate", idempotency_key: "separate" } as any,
        join(f.root, "repository"),
      ).created,
    );
  } finally {
    f.store.close();
    rmSync(f.root, { recursive: true, force: true });
  }
});

test("workspace .artifacts symlink is ignored by trusted collector", async () => {
  const f = fixture();
  const outside = mkdtempSync(join(tmpdir(), "lab-artifact-outside-"));
  try {
    symlinkSync(outside, join(f.root, ".artifacts"));
    f.service.start(task);
    await f.service.drain();
    assert.equal(f.service.get("lab", "run1", "task1").status, "succeeded");
    assert.equal((await import("node:fs")).readdirSync(outside).length, 0);
  } finally {
    await f.service.drain();
    f.store.close();
    rmSync(f.root, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});

test("live configuration cannot place journal/artifacts inside model workspace", () => {
  const f = fixture();
  try {
    f.service.config.mode = "live";
    assert.throws(() => f.service.start(task), /outside writable workspace/);
  } finally {
    f.store.close();
    rmSync(f.root, { recursive: true, force: true });
  }
});
