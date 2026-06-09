import fs from "fs";

const s = fs.readFileSync("c:/Users/VISHN/OneDrive/Desktop/v4/assets/index-DW9uSTL6.js", "utf8");
for (const name of ["im", "Mde", "om", "$p", "TS", "Lp"]) {
  const idx = s.indexOf(`${name}="`);
  if (idx >= 0) {
    const end = s.indexOf('"', idx + name.length + 2);
    console.log(name, s.slice(idx, end + 1));
  }
}
