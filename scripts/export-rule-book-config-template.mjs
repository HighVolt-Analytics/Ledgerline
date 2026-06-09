import { writeFileSync } from "node:fs";
import { createInitialV4RuleBook } from "../frontend/src/lib/v4RuleBookMockData.ts";

function toSnake(key) {
  if (key.includes("_")) return key;
  return key.replace(/[A-Z]/g, (m) => `_${m.toLowerCase()}`);
}

function keysToSnake(obj) {
  if (Array.isArray(obj)) return obj.map(keysToSnake);
  if (obj && typeof obj === "object") {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
      out[toSnake(k)] = keysToSnake(v);
    }
    return out;
  }
  return obj;
}

const data = {
  schema_version: 1,
  ...keysToSnake(createInitialV4RuleBook()),
};

const outPath = new URL("../backend/app/rule_book_config.json", import.meta.url);
writeFileSync(outPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
console.log("Wrote", outPath.pathname);
