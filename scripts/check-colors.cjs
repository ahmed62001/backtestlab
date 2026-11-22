// Binding Rule 2 guard: no hex/rgb literals outside tokens + chart theme + css.
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..', 'src');
const ALLOW = new Set([
  'lib/tokens.ts',
  'lib/chartTheme.ts',
  'styles/globals.css',
]);
const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(/;
let bad = [];
function walk(dir) {
  for (const f of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, f.name);
    if (f.isDirectory()) { walk(p); continue; }
    if (!/\.(ts|tsx|css)$/.test(f.name)) continue;
    const rel = path.relative(ROOT, p);
    if (ALLOW.has(rel)) continue;
    const src = fs.readFileSync(p, 'utf8');
    src.split('\n').forEach((line, i) => {
      if (COLOR_RE.test(line)) bad.push(rel + ':' + (i + 1) + ': ' + line.trim().slice(0, 100));
    });
  }
}
walk(ROOT);
if (bad.length) {
  console.error('COLOR LITERALS FOUND outside tokens/chartTheme/globals.css:');
  bad.forEach((b) => console.error(' - ' + b));
  process.exit(1);
}
console.log('check-colors: OK (no literals outside allowlist)');
