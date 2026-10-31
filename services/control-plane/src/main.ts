import "reflect-metadata";
import { Controller, All, Req, Res, Module } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import { Request, Response } from "express";
import { timingSafeEqual } from "node:crypto";
import { mkdirSync, readFileSync, existsSync } from "node:fs";
import { resolve, join, extname } from "node:path";
import { TaskStore } from "./store.js";
import {
  ExecutionService,
  DemoTransport,
  SDKTransport,
  ExecutionConfig,
} from "./execution.js";
import { BoundaryError, scopeKey } from "./contracts.js";

const token = process.env.LAB_INTERNAL_TOKEN;
if (!token || token.length < 16)
  throw new Error("LAB_INTERNAL_TOKEN of at least 16 characters is required");
const mode = process.env.LAB_MODE ?? "demo";
if (!["demo", "live"].includes(mode))
  throw new Error("LAB_MODE must be demo or live");
const data = resolve(process.env.LAB_DATA_DIR ?? ".runtime");
mkdirSync(data, { recursive: true });
const fixture = join(data, "workspace");
mkdirSync(fixture, { recursive: true });
const config: ExecutionConfig =
  mode === "demo"
    ? {
        mode: "demo",
        project: "lab",
        root: fixture,
        workspaces: { default: "." },
        checks: {
          fixture: {
            argv: [
              process.execPath,
              "-e",
              "const fs=require('fs');if(JSON.parse(fs.readFileSync('result.json','utf8')).verified!==true)process.exit(1)",
            ],
            timeout_ms: 5000,
          },
        },
      }
    : JSON.parse(readFileSync(process.env.LAB_EXECUTION_CONFIG ?? "", "utf8"));
if (
  mode === "live" &&
  (!process.env.LAB_BROWSER_TOKEN || config.mode !== "live")
)
  throw new Error(
    "Live mode requires browser token and explicit execution config",
  );
const store = new TaskStore(join(data, "control.sqlite"));
const executor = new ExecutionService(
  store,
  config,
  mode === "demo" ? new DemoTransport() : new SDKTransport(),
);
const python = process.env.LAB_ORCHESTRATOR_URL ?? "http://127.0.0.1:8000";
const ui = resolve(process.env.LAB_UI_DIR ?? "apps/lab-ui/dist/browser");
function matches(actual: string | undefined, expected: string): boolean {
  const a = Buffer.from(actual ?? ""),
    b = Buffer.from(`Bearer ${expected}`);
  return a.length === b.length && timingSafeEqual(a, b);
}

@Controller()
class Gateway {
  @All("{*path}")
  async route(@Req() req: Request, @Res() res: Response): Promise<void> {
    try {
      if (req.path === "/health") {
        res.json({
          status: "ok",
          mode,
          codex: mode === "demo" ? "simulated" : "configured-unverified",
        });
        return;
      }
      if (req.path.startsWith("/internal/")) {
        if (!matches(req.headers.authorization, token!))
          throw new BoundaryError(401, "Service authorization required");
        const match = req.path.match(
          /^\/internal\/v1\/tasks(?:\/([^/]+)(?:\/(resume|cancel|events))?)?$/,
        );
        if (!match) throw new BoundaryError(404, "Route not found");
        const task = match[1],
          action = match[2],
          scope = req.method === "GET" ? req.query : req.body;
        if (req.method === "POST" && !task) {
          res.status(202).json(executor.start(req.body));
          return;
        }
        const project = String(scope.project_id ?? ""),
          run = String(scope.run_id ?? "");
        if (req.method === "GET" && task && !action) {
          res.json(executor.get(project, run, task));
          return;
        }
        if (req.method === "GET" && task && action === "events") {
          res.json(
            store.events(
              scopeKey(project, run, task),
              Number(req.query.after ?? 0),
            ),
          );
          return;
        }
        if (req.method === "POST" && task && action === "cancel") {
          res.json(executor.cancel(project, run, task));
          return;
        }
        if (req.method === "POST" && task && action === "resume") {
          res.json(
            executor.resume(
              project,
              run,
              task,
              req.body.feedback,
              req.body.idempotency_key,
            ),
          );
          return;
        }
        throw new BoundaryError(405, "Method not allowed");
      }
      // Host and Origin checks prevent a remote site from driving the loopback demo.
      if (
        !/^((127\.0\.0\.1)|(localhost))(?::\d+)?$/.test(req.headers.host ?? "")
      )
        throw new BoundaryError(403, "Loopback host required");
      if (
        req.headers.origin &&
        !["http://127.0.0.1:3100", "http://localhost:3100"].includes(
          req.headers.origin,
        )
      )
        throw new BoundaryError(403, "Origin not allowed");
      if (req.path.startsWith("/api/")) {
        if (
          mode === "live" &&
          !matches(req.headers.authorization, process.env.LAB_BROWSER_TOKEN!)
        )
          throw new BoundaryError(401, "Browser authorization required");
        if (req.path === "/api/config") {
          res.json({ mode, project_id: config.project });
          return;
        }
        const target = new URL(
          req.originalUrl.replace(/^\/api\//, "/v1/"),
          python,
        );
        if (
          !/^\/v1\/runs(?:\/[a-zA-Z0-9_-]+(?:\/(advance|approval|cancel|events))?)?$/.test(
            target.pathname,
          )
        )
          throw new BoundaryError(404, "Route not found");
        if (req.body?.project_id && req.body.project_id !== config.project)
          throw new BoundaryError(403, "Project not registered");
        if (
          target.searchParams.has("project_id") &&
          target.searchParams.get("project_id") !== config.project
        )
          throw new BoundaryError(403, "Project not registered");
        if (req.path.endsWith("/events") && req.method === "GET") {
          await this.stream(req, res, target);
          return;
        }
        const response = await fetch(target, {
          method: req.method,
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: ["GET", "HEAD"].includes(req.method)
            ? undefined
            : JSON.stringify(req.body),
          signal: AbortSignal.timeout(30000),
        });
        res
          .status(response.status)
          .type("application/json")
          .send(await response.text());
        return;
      }
      if (req.method !== "GET")
        throw new BoundaryError(405, "Method not allowed");
      const path =
        req.path === "/" ? "index.html" : req.path.replace(/^\//, "");
      if (path.includes("..") || path.includes("\\"))
        throw new BoundaryError(403, "Invalid asset path");
      const file = join(ui, path);
      if (!existsSync(file))
        throw new BoundaryError(404, "UI asset not found; run npm run build");
      const types: Record<string, string> = {
        ".html": "text/html",
        ".js": "application/javascript",
        ".css": "text/css",
        ".ico": "image/x-icon",
      };
      res
        .type(types[extname(file)] ?? "application/octet-stream")
        .send(readFileSync(file));
    } catch (error) {
      const code = error instanceof BoundaryError ? error.status : 502;
      res
        .status(code)
        .json({
          detail:
            error instanceof BoundaryError
              ? error.message
              : "Upstream unavailable; inspect service configuration",
        });
    }
  }
  async stream(req: Request, res: Response, target: URL): Promise<void> {
    let cursor = Number(
      req.headers["last-event-id"] ?? target.searchParams.get("after") ?? 0,
    );
    if (!Number.isSafeInteger(cursor) || cursor < 0)
      throw new BoundaryError(422, "Invalid event cursor");
    // Validate scope before committing SSE headers.
    target.searchParams.set("after", String(cursor));
    let response = await fetch(target, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) {
      res.status(response.status).send(await response.text());
      return;
    }
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.flushHeaders();
    let closed = false;
    req.on("close", () => {
      closed = true;
    });
    while (!closed) {
      const events = (await response.json()) as any[];
      for (const event of events) {
        if (event.sequence > cursor) {
          cursor = event.sequence;
          res.write(`id: ${cursor}\ndata: ${JSON.stringify(event)}\n\n`);
        }
      }
      res.write(": heartbeat\n\n");
      await new Promise((done) => setTimeout(done, 500));
      if (closed) break;
      target.searchParams.set("after", String(cursor));
      try {
        response = await fetch(target, {
          headers: { Authorization: `Bearer ${token}` },
          signal: AbortSignal.timeout(10000),
        });
        if (!response.ok) break;
      } catch {
        break;
      }
    }
    res.end();
  }
}
@Module({ controllers: [Gateway] })
export class ControlPlaneModule {}
const app = await NestFactory.create(ControlPlaneModule, {
  logger: ["error", "warn"],
});
app.enableShutdownHooks();
await app.listen(Number(process.env.PORT ?? 3100), "127.0.0.1");
