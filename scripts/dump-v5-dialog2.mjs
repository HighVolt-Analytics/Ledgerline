import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v5/assets/index-CzAuRRTo.js", "utf8");
const markers = ["Ww=A.forwardRef", "Gw=", "Vw=", "left-[50%]", "translate-x-[-50%]"];
for (const m of markers) {
  const i = s.indexOf(m);
  console.log("---", m, i, "---");
  if (i >= 0) console.log(s.slice(i, i + 600));
}
