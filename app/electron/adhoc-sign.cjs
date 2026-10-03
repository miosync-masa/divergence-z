// electron-builder afterSign hook: Apple の証明書が無いときに ad-hoc 署名（自己署名）だけ付ける。
// 署名が全く無いアプリは Apple シリコンの Mac で「壊れている」と表示されて開けないため。
// 正式な Developer ID 署名・公証を入れたら、このフックは不要になる。
const { execFileSync } = require("node:child_process");
const path = require("node:path");

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== "darwin") return;
  if (process.env.CSC_LINK || process.env.CSC_NAME) return; // 本物の署名をする場合は何もしない
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  console.log(`  • ad-hoc signing ${app}`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", app], { stdio: "inherit" });
  execFileSync("codesign", ["--verify", "--deep", "--strict", app], { stdio: "inherit" });
};
