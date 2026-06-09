import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v4/assets/index-DW9uSTL6.js", "utf8");

const start = s.indexOf('title:"Document Matrix",subtitle:"Pipeline stage status, anomaly detection');
const fnStart = s.lastIndexOf("function ", start - 500);
console.log(s.slice(fnStart, start + 12000));
