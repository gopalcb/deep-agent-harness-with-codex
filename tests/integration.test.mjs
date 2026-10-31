import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { randomBytes } from "node:crypto";
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
test(
  "real HTTP graph → NestJS → fixture checks, approvals and replay",
  { timeout: 45000 },
  async () => {
    const data = mkdtempSync(join(tmpdir(), "lab-integration-"));
    const token = randomBytes(32).toString("hex");
    const env = {
      ...process.env,
      LAB_MODE: "demo",
      LAB_INTERNAL_TOKEN: token,
      LAB_DATA_DIR: data,
      PORT: "13100",
      CODEX_BASE_URL: "http://127.0.0.1:13100",
      LAB_ORCHESTRATOR_URL: "http://127.0.0.1:18000",
      LAB_UI_DIR: resolve("apps/lab-ui/dist/browser"),
      LANGSMITH_TRACING: "false",
    };
    const children = [
      spawn(
        "uv",
        [
          "run",
          "--project",
          "services/agent-orchestrator",
          "uvicorn",
          "orchestrator.api:app",
          "--host",
          "127.0.0.1",
          "--port",
          "18000",
        ],
        { env, stdio: ["ignore", "pipe", "pipe"] },
      ),
      spawn(process.execPath, ["services/control-plane/dist/main.js"], {
        env,
        stdio: ["ignore", "pipe", "pipe"],
      }),
    ];
    let diagnostic = "";
    for (const child of children) {
      child.stdout.on(
        "data",
        (b) => (diagnostic = (diagnostic + b).slice(-4000)),
      );
      child.stderr.on(
        "data",
        (b) => (diagnostic = (diagnostic + b).slice(-4000)),
      );
    }
    async function request(path, body) {
      const response = await fetch("http://127.0.0.1:13100" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      assert.ok(response.ok, await response.clone().text());
      return response.json();
    }
    try {
      let ready = false;
      for (let i = 0; i < 100; i++) {
        try {
          const responses = await Promise.all([
            fetch("http://127.0.0.1:13100/health"),
            fetch("http://127.0.0.1:18000/health"),
          ]);
          if (responses.every((r) => r.ok)) {
            ready = true;
            break;
          }
        } catch {}
        await pause(150);
      }
      assert.ok(ready, diagnostic);
      assert.equal(
        (
          await fetch(
            "http://127.0.0.1:13100/internal/v1/tasks/a?project_id=lab&run_id=r",
          )
        ).status,
        401,
      );
      assert.equal(
        (
          await fetch("http://127.0.0.1:13100/api/runs", {
            method: "POST",
            headers: {
              Origin: "https://attacker.test",
              "Content-Type": "application/json",
            },
            body: "{}",
          })
        ).status,
        403,
      );
      assert.match(
        await (await fetch("http://127.0.0.1:13100/")).text(),
        /lab-app/,
      );
      for (const workflow_id of ["direct", "planned"]) {
        let run = await request("/api/runs", {
          project_id: "lab",
          instruction: "Build and verify fixture",
          workflow_id,
          idempotency_key: workflow_id,
          risk: "workspace-write",
        });
        const id = run.run_id;
        for (
          let i = 0;
          i < 100 && !["succeeded", "failed", "blocked"].includes(run.status);
          i++
        ) {
          await pause(100);
          run = await request(`/api/runs/${id}?project_id=lab`);
        }
        assert.equal(run.status, "succeeded", JSON.stringify(run));
        const replay = await fetch(
          `http://127.0.0.1:18000/v1/runs/${id}/events?project_id=lab`,
          { headers: { Authorization: "Bearer " + token } },
        );
        const events = await replay.json();
        assert.ok(events.length > 2);
        assert.equal(
          new Set(events.map((e) => e.event_id)).size,
          events.length,
        );
        const repeat = await request("/api/runs", {
          project_id: "lab",
          instruction: "Build and verify fixture",
          workflow_id,
          idempotency_key: workflow_id,
          risk: "workspace-write",
        });
        assert.equal(repeat.run_id, id);
      }
      let gated = await request("/api/runs", {
        project_id: "lab",
        instruction: "Protected example",
        workflow_id: "direct",
        idempotency_key: "gated",
        risk: "sensitive",
      });
      for (let i = 0; i < 30 && gated.status !== "waiting_approval"; i++) {
        await pause(100);
        gated = await request(`/api/runs/${gated.run_id}?project_id=lab`);
      }
      assert.equal(gated.status, "waiting_approval");
      const denied = await request(
        `/api/runs/${gated.run_id}/approval?project_id=lab`,
        { approved: false },
      );
      assert.ok(["cancelled", "blocked", "failed"].includes(denied.status));
    } finally {
      for (const child of children) child.kill("SIGTERM");
      await Promise.all(
        children.map(
          (child) =>
            new Promise((done) => {
              if (child.exitCode !== null) return done();
              const timer = setTimeout(() => {
                child.kill("SIGKILL");
                done();
              }, 3000);
              child.once("exit", () => {
                clearTimeout(timer);
                done();
              });
            }),
        ),
      );
      rmSync(data, { recursive: true, force: true });
    }
  },
);
