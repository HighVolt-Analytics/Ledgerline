import fs from "fs";
const s = fs.readFileSync(
  "C:/Users/VISHN/Downloads/Ledgerline v2/assets/index-DV-5q5ey.js",
  "utf8"
);
for (const k of ["function Ht(", "function cce(", "const qe=", "function Bq(", "Bq=function"]) {
  const i = s.indexOf(k);
  console.log(k, i);
  if (i >= 0) console.log(s.slice(i, i + 1500), "\n---\n");
}
