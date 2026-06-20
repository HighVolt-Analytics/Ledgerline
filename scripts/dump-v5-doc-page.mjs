import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v5/assets/index-CzAuRRTo.js", "utf8");
const i = s.indexOf('href:"/document-types"');
console.log(s.slice(i - 400, i + 600));
