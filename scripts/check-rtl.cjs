// RTL guard: fail on physical-direction Tailwind classes or CSS outside node_modules.
// Logical equivalents required: ms-/me-/ps-/pe-/start-/end-/text-start/text-end/border-s/border-e/rounded-s/rounded-e.
// Opt-out: add `/* rtl-ok: reason */` on the same line (e.g. LTR chart boxes).
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const TARGETS = [path.join(ROOT, 'src'), path.join(ROOT, 'index.html')];
const OPT_OUT = /\/\*\s*rtl-ok\s*:.+?\*\//;
const RULES = [
  { re: /(?<![A-Za-z0-9_-])(ml|mr|pl|pr)-[^/\s"']+/, msg: 'physical spacing (ml-/mr-/pl-/pr-)' },
  { re: /(?<![A-Za-z0-9_-])text-(left|right)(?![A-Za-z0-9_-])/, msg: 'text-left/text-right' },
  { re: /(?<![A-Za-z0-9_-])border-[lr](?![A-Za-z0-9_-])/, msg: 'border-l/border-r' },
  { re: /(?<![A-Za-z0-9_-])rounded-[lr](?![A-Za-z0-9_-])/, msg: 'rounded-l/rounded-r' },
  { re: /(?<![A-Za-z0-9_-])float-(left|right)(?![A-Za-z0-9_-])/, msg: 'float-left/float-right' },
  { re: /(?<![A-Za-z0-9_-])(left|right)-\d+/, msg: 'left-*/right-* positioning' },
  { re: /(?<![A-Za-z0-9_-])start-\d+|(?<![A-Za-z0-9_-])end-\d+/, msg: null, note: 'logical-ok-skip' },
  { re: /\b(margin-left|margin-right|padding-left|padding-right|border-left|border-right)\s*:/, msg: 'physical CSS property' },
  { re: /(?<![a-zA-Z-])float\s*:\s*(left|right)/, msg: 'physical float CSS' },
  { re: /(?<![a-zA-Z-])(left|top|right|bottom)\s*:\s*-?\d/, msg: null, note: 'check-context' },
];
let bad = [];
function checkFile(p) {
  const src = fs.readFileSync(p, 'utf8');
  const rel = path.relative(ROOT, p);
  src.split('\n').forEach((line, i) => {
    if (OPT_OUT.test(line)) return;
    // Skip recharts JS margin objects: `{ top: 8, right: 8, ... }` inside LTR chart boxes.
    if (/margin\s*=\s*\{\{/.test(line)) return;
    for (const r of RULES) {
      if (!r.msg) continue;
      if (r.re.test(line)) {
        // Allow `text-white`, `bg-white` etc: already excluded by regex. Allow `border-line` token.
        if (/border-line/.test(line) && r.msg.includes('border-l')) continue;
        bad.push(`${rel}:${i + 1}: [${r.msg}] ${line.trim().slice(0, 120)}`);
        break;
      }
    }
  });
}
function walk(p) {
  if (!fs.existsSync(p)) return;
  const st = fs.statSync(p);
  if (st.isFile()) { if (/\.(ts|tsx|css|html)$/.test(p)) checkFile(p); return; }
  for (const f of fs.readdirSync(p, { withFileTypes: true })) {
    if (f.name === 'node_modules') continue;
    walk(path.join(p, f.name));
  }
}
TARGETS.forEach(walk);
if (bad.length) {
  console.error('RTL VIOLATIONS (use logical ms-/me-/ps-/pe-/start-/end-/text-start/text-end/border-s/border-e/rounded-s/rounded-e):');
  bad.forEach((b) => console.error(' - ' + b));
  process.exit(1);
}
console.log('check-rtl: OK (no physical-direction classes)');
