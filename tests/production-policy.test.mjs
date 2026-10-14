import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";

const policyPath = new URL("../scripts/check-production-policy.mjs", import.meta.url);
const validSha = "a".repeat(40);

function evaluate(overrides = {}) {
  const result = spawnSync(process.execPath, [fileURLToPath(policyPath)], {
    env: {
      ...process.env,
      DEPLOY_EVENT: "workflow_dispatch",
      DEPLOY_REF: "refs/heads/main",
      MAIN_SHA: validSha,
      REQUESTED_SHA: validSha,
      CONFIRM_PRODUCTION: "DEPLOY",
      AUTOMATIC_DEPLOY_ENABLED: "false",
      PRODUCTION_CUTOVER_ENABLED: "true",
      PORTAL_DISPATCH_ENABLED: "false",
      ...overrides,
    },
    encoding: "utf8",
  });
  return result.status === 0;
}

test("trigger matrix keeps push authorization separate from manual cutover", () => {
  assert.equal(evaluate({ DEPLOY_EVENT: "push", AUTOMATIC_DEPLOY_ENABLED: "false", PRODUCTION_CUTOVER_ENABLED: "true" }), false);
  assert.equal(evaluate({ DEPLOY_EVENT: "push", AUTOMATIC_DEPLOY_ENABLED: "true", PRODUCTION_CUTOVER_ENABLED: "false" }), true);
  assert.equal(evaluate({ DEPLOY_EVENT: "push", DEPLOY_REF: "refs/heads/feature", AUTOMATIC_DEPLOY_ENABLED: "true" }), false);
  assert.equal(evaluate({ DEPLOY_EVENT: "pull_request", AUTOMATIC_DEPLOY_ENABLED: "true", PRODUCTION_CUTOVER_ENABLED: "true", PORTAL_DISPATCH_ENABLED: "true" }), false);
  assert.equal(evaluate({ DEPLOY_EVENT: "workflow_dispatch", PRODUCTION_CUTOVER_ENABLED: "false" }), false);
  assert.equal(evaluate({ DEPLOY_EVENT: "workflow_dispatch", PRODUCTION_CUTOVER_ENABLED: "true" }), true);
  assert.equal(evaluate({ DEPLOY_EVENT: "workflow_dispatch", PRODUCTION_CUTOVER_ENABLED: "false", PORTAL_DISPATCH_ENABLED: "true" }), true);
});

test("wrong branch, stale or invalid SHA, wrong confirmation, and unknown event fail closed", () => {
  assert.equal(evaluate({ DEPLOY_REF: "refs/heads/feature" }), false);
  assert.equal(evaluate({ MAIN_SHA: "b".repeat(40) }), false);
  assert.equal(evaluate({ REQUESTED_SHA: "not-a-sha" }), false);
  assert.equal(evaluate({ CONFIRM_PRODUCTION: "deploy" }), false);
  assert.equal(evaluate({ DEPLOY_EVENT: "pull_request" }), false);
});

test("deploy workflow does not run on PRs or workflow-only pushes", async () => {
  const workflow = await readFile(new URL("../.github/workflows/deploy.yml", import.meta.url), "utf8");
  const pushSection = workflow.match(/  push:\r?\n([\s\S]*?)  workflow_dispatch:/)?.[1] ?? "";
  assert.ok(pushSection.includes("branches: [main]"));
  assert.ok(!pushSection.includes(".github/workflows"));
  assert.ok(!pushSection.includes("docs/**"));
  assert.ok(workflow.includes("github.event_name == 'push' && vars.LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED == 'true'"));
  assert.ok(workflow.includes("github.event_name == 'workflow_dispatch'"));
  assert.ok(workflow.includes("vars.LEDGERLINE_PRODUCTION_CUTOVER_ENABLED == 'true'"));
  assert.ok(workflow.includes("vars.LEDGERLINE_PORTAL_DISPATCH_ENABLED == 'true'"));
  assert.ok(workflow.includes("group: deploy-ledgerline-production"));
  assert.ok(workflow.includes("cancel-in-progress: false"));
});
