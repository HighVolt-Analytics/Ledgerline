import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v5/assets/index-CzAuRRTo.js", "utf8");
const idx = s.indexOf("Wae");
console.log("Wae at", idx);
const routeIdx = s.indexOf("document-types");
console.log("document-types at", routeIdx, s.slice(routeIdx - 100, routeIdx + 200));
const catalogueIdx = s.indexOf("catalogue");
console.log("catalogue at", catalogueIdx, s.slice(catalogueIdx - 100, catalogueIdx + 200));
