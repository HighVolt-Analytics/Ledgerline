import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v5/assets/index-CzAuRRTo.js", "utf8");
const idx = s.indexOf('xI.displayName=tp.displayName');
console.log(s.slice(idx - 800, idx + 1200));
