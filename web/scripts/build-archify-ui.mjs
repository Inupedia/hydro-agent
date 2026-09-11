#!/usr/bin/env node
/**
 * Build the workbench UI as a single Archify HTML document (no Vue pages).
 */
import { copyFileSync, mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webRoot = join(__dirname, "..");
const repoRoot = join(webRoot, "..");
const dist = join(webRoot, "dist");
const diagramSrc = join(webRoot, "public", "diagrams", "hydro-agent-xaj.workflow.html");
const driverSrc = join(webRoot, "public", "workbench-driver.js");
const metaSrc = join(webRoot, "public", "workflow-meta.js");
const jsonSrc = join(repoRoot, "docs", "diagrams", "hydro-agent.v1.workflow.json");

if (!existsSync(diagramSrc)) {
  console.error("Missing Archify diagram:", diagramSrc);
  process.exit(1);
}
if (!existsSync(driverSrc)) {
  console.error("Missing workbench driver:", driverSrc);
  process.exit(1);
}

mkdirSync(dist, { recursive: true });
mkdirSync(join(dist, "diagrams"), { recursive: true });

const diagramHtml = readFileSync(diagramSrc, "utf8");
const injection = `
<script src="/workflow-meta.js"></script>
<script src="/workbench-driver.js" defer></script>
<!-- Hydro-Agent: Archify is the entire frontend; driver syncs live agent focus. -->
`;

let indexHtml = diagramHtml.includes("</body>")
  ? diagramHtml.replace("</body>", `${injection}</body>`)
  : `${diagramHtml}${injection}`;

indexHtml = indexHtml.replace(
  /<title>[^<]*<\/title>/i,
  "<title>Hydro-Agent · Archify Workbench</title>",
);

writeFileSync(join(dist, "index.html"), indexHtml);
copyFileSync(driverSrc, join(dist, "workbench-driver.js"));
if (existsSync(metaSrc)) {
  copyFileSync(metaSrc, join(dist, "workflow-meta.js"));
}
copyFileSync(diagramSrc, join(dist, "diagrams", "hydro-agent-xaj.workflow.html"));
if (existsSync(jsonSrc)) {
  copyFileSync(jsonSrc, join(dist, "diagrams", "hydro-agent-xaj.workflow.json"));
}

console.log("Built Archify-only workbench UI →", dist);
