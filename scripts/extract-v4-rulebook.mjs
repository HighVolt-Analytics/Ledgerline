import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v4/assets/index-DW9uSTL6.js", "utf8");

function sliceFrom(needle, len = 4000) {
  const i = s.indexOf(needle);
  if (i < 0) return null;
  return s.slice(i, i + len);
}

const out = {
  routing: sliceFrom("kM=[", 2000),
  legacyMg: sliceFrom("function mg()", 2500),
  legacyPg: sliceFrom("function pg(", 1500),
  emailRules: sliceFrom("function Z9()", 5000),
  purchaseRules: sliceFrom("function eW()", 3000),
  expenseRules: sliceFrom("function rW()", 4000),
  teamRules: sliceFrom("function iW()", 3000),
  vendorMasters: sliceFrom("function sW()", 3000),
  vendorDetection: sliceFrom("function Of()", 800),
  employees: sliceFrom("function cW()", 2000),
  purchaseTab: sliceFrom("function rfe()", 3500),
  expensesTab: sliceFrom("function nfe()", 3500),
  teamTab: sliceFrom("function afe()", 3500),
  vendorsTab: sliceFrom("function Pfe()", 3500),
  employeesTab: sliceFrom("function Cfe()", 3500),
  liveEval: sliceFrom("function $de()", 4000),
};

fs.writeFileSync(
  "c:/Users/VISHN/OneDrive/Desktop/Email_to_Acc_proj/scripts/v4-rulebook-extract.txt",
  Object.entries(out)
    .map(([k, v]) => `\n\n======== ${k} ========\n${v ?? "NOT FOUND"}`)
    .join(""),
  "utf8"
);
console.log("written", Object.keys(out).length, "sections");
