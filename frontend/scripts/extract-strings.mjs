import fs from "fs";
const s = fs.readFileSync(
  "C:/Users/VISHN/Downloads/Ledgerline v2/assets/index-DV-5q5ey.js",
  "utf8"
);
const texts = [...s.matchAll(/"([A-Za-z][^"]{8,120})"/g)]
  .map((m) => m[1])
  .filter(
    (t) =>
      !t.includes("\\") &&
      !t.startsWith("http") &&
      /[a-z]/.test(t) &&
      /[A-Z ]/.test(t) || t.includes("→") || t.includes("VR")
  );
const uniq = [...new Set(texts)].sort();
console.log(uniq.join("\n"));
