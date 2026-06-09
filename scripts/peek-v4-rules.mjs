import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v4/assets/index-DW9uSTL6.js", "utf8");

// Tab definitions
const tabIdx = s.indexOf("Efe=[");
if (tabIdx >= 0) console.log("TABS:\n", s.slice(tabIdx, tabIdx + 800));

// Find ruleBook structure in store
const rbIdx = s.indexOf("ruleBook:");
if (rbIdx >= 0) console.log("\nRULEBOOK STORE:\n", s.slice(rbIdx, rbIdx + 3000));

// Email capture tab component - search for distinctive strings
for (const needle of [
  "Email capture",
  "emailCapture",
  "emailRules",
  "Purchase rules",
  "Expense rules",
  "Team expense",
  "Vendor rules",
  "Employee rules",
  "category rule",
  "Legacy cascade",
  "Six coordinated",
  "function Qde",
  "function Gde",
]) {
  const i = s.indexOf(needle);
  if (i >= 0) console.log(`\n=== ${needle} @ ${i} ===\n`, s.slice(i, i + 2500));
}
