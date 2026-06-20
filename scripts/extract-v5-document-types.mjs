import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v5/assets/index-CzAuRRTo.js", "utf8");

const marker = 'code:"DT-01"';
const i = s.indexOf(marker);
if (i < 0) throw new Error("Missing DT-01");

let start = s.lastIndexOf("[", i);
let depth = 0;
let end = start;
for (let j = start; j < s.length; j++) {
  if (s[j] === "[") depth++;
  else if (s[j] === "]") {
    depth--;
    if (depth === 0) {
      end = j + 1;
      break;
    }
  }
}

const code = s.slice(start, end);
// eslint-disable-next-line no-eval
const documentTypes = eval(code);

const out = new URL("../frontend/src/lib/v5DocumentTypes.json", import.meta.url);
fs.writeFileSync(out, JSON.stringify(documentTypes, null, 2), "utf8");
console.log("Wrote", documentTypes.length, "document types");
