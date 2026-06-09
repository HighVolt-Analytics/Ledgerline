import fs from "fs";

const s = fs.readFileSync("C:/Users/VISHN/OneDrive/Desktop/v4/assets/index-DW9uSTL6.js", "utf8");

function extractArray(marker) {
  const i = s.indexOf(marker);
  if (i < 0) throw new Error(`Missing ${marker}`);
  let depth = 0;
  let started = false;
  let j = i + marker.length - 1;
  for (; j < s.length; j++) {
    if (s[j] === "[") {
      depth++;
      started = true;
    } else if (s[j] === "]") {
      depth--;
      if (started && depth === 0) {
        j++;
        break;
      }
    }
  }
  const code = s.slice(i + marker.length - 1, j);
  // eslint-disable-next-line no-eval
  return eval(code);
}

function extractObject(marker) {
  const i = s.indexOf(marker);
  if (i < 0) throw new Error(`Missing ${marker}`);
  let depth = 0;
  let started = false;
  let j = i + marker.indexOf("{");
  for (; j < s.length; j++) {
    if (s[j] === "{") {
      depth++;
      started = true;
    } else if (s[j] === "}") {
      depth--;
      if (started && depth === 0) {
        j++;
        break;
      }
    }
  }
  const code = s.slice(i + marker.indexOf("{"), j);
  // eslint-disable-next-line no-eval
  return eval(`(${code})`);
}

const data = {
  expenses: extractArray("IW=["),
  budgets: extractArray("Ud=["),
  categories: extractArray("DW=["),
  channels: extractArray("$W=["),
  purchases: extractArray("LW=["),
  payments: extractArray("BW=["),
  wallet: extractObject("yA={balance:"),
  ledgerInvoices: extractArray("FI=["),
  ledgerBills: extractArray("BI=["),
  ledgerExpenses: extractArray("qI=["),
  ledgerPurchases: extractArray("VI=["),
  ledgerPayments: extractArray("zI=["),
  exportHistory: extractArray("qW=["),
  auditEvents: extractArray("VW=["),
};

const out = new URL("../frontend/src/lib/v4MockData.json", import.meta.url);
fs.writeFileSync(out, JSON.stringify(data, null, 2), "utf8");
console.log(
  "Wrote v4MockData.json",
  Object.fromEntries(Object.entries(data).map(([k, v]) => [k, Array.isArray(v) ? v.length : "obj"]))
);
