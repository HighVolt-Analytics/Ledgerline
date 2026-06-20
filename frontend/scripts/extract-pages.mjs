import fs from "fs";
const s = fs.readFileSync(
  "C:/Users/VISHN/Downloads/Ledgerline v2/assets/index-DV-5q5ey.js",
  "utf8"
);
const keys = [
  'title:"Upload"',
  'title:"Approvals"',
  'title:"Vendors"',
  'title:"Rule Book"',
  'title:"Reconciliation"',
  'title:"Integrations"',
  'title:"Reports"',
  'title:"Settings"',
  "Captured invoices",
  "Approval workflow",
  "Kanban board",
];
for (const k of keys) {
  const i = s.indexOf(k);
  console.log("\n===", k, "===", i);
  if (i >= 0) console.log(s.slice(i, i + 2000));
}
