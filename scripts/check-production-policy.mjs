const env = process.env;
const fullSha = /^[0-9a-f]{40}$/;

function fail(message) {
  console.error(message);
  process.exitCode = 1;
}

if (env.DEPLOY_REF !== "refs/heads/main") {
  fail("Production releases are restricted to the main branch.");
} else if (env.MAIN_SHA !== env.REQUESTED_SHA || !fullSha.test(env.REQUESTED_SHA ?? "")) {
  fail("The requested release must be the exact current main commit.");
} else if (env.DEPLOY_EVENT === "push") {
  if (env.AUTOMATIC_DEPLOY_ENABLED !== "true") {
    fail("Automatic production deployment is disabled.");
  }
} else if (env.DEPLOY_EVENT === "workflow_dispatch") {
  if (env.CONFIRM_PRODUCTION !== "DEPLOY") {
    fail("Manual production dispatch requires the exact DEPLOY confirmation.");
  } else if (
    env.PRODUCTION_CUTOVER_ENABLED !== "true" &&
    env.PORTAL_DISPATCH_ENABLED !== "true"
  ) {
    fail("Manual production dispatch requires the migration cutover or portal dispatch gate.");
  }
} else {
  fail("This event is not an authorized production deployment trigger.");
}

if (process.exitCode !== 1) console.log("Production authorization checks passed.");
