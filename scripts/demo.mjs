import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { resolve } from "node:path";
const env = {
  ...process.env,
  LAB_MODE: "demo",
  LAB_INTERNAL_TOKEN: randomBytes(32).toString("hex"),
  LAB_DATA_DIR: resolve(".runtime"),
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
      "8000",
    ],
    { env, stdio: "inherit" },
  ),
  spawn(process.execPath, ["services/control-plane/dist/main.js"], {
    env,
    stdio: "inherit",
  }),
];
let stopped = false;
function stop() {
  if (stopped) return;
  stopped = true;
  for (const child of children) child.kill("SIGTERM");
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
for (const child of children) {
  child.on("error", (error) => {
    console.error(error.message);
    stop();
    process.exitCode = 1;
  });
  child.on("exit", (code) => {
    if (!stopped) {
      stop();
      process.exitCode = code ?? 1;
    }
  });
}
console.log(
  "Credential-free lab: http://127.0.0.1:3100 · Ctrl+C stops both owned services.",
);
