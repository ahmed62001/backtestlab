/**
 * Prints the route table + demo test accounts + LAN URL for mobile testing.
 *
 * The route list comes from src/routes/manifest.ts (the single source of truth),
 * so start.sh, the router and docs/ROUTES.md can never go stale relative to each
 * other as long as pages are added only to the manifest.
 *
 * Usage:
 *   node scripts/print-routes.mjs                # human-readable table (dev)
 *   node scripts/print-routes.mjs --markdown     # Markdown table (for docs/ROUTES.md)
 *   node scripts/print-routes.mjs --lan-ip       # prints only the LAN IP (for start.sh)
 */

import { readFileSync, writeFileSync, mkdirSync, unlinkSync } from 'node:fs';
import { transpileModule } from 'typescript';
import { networkInterfaces } from 'node:os';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');

// ---------------------------------------------------------------------------
// Load the manifest (.ts data file) inside plain Node. `typescript` is already a
// devDependency, so we can transpile the manifest on the fly without extra
// tooling. The manifest has no imports, so transpileModule needs no resolution.
// ---------------------------------------------------------------------------
const manifestSrc = readFileSync(path.join(root, 'src', 'routes', 'manifest.ts'), 'utf8');
const { outputText } = transpileModule(manifestSrc, {
  compilerOptions: {
    module: 'es2020',
    target: 'es2020',
    strict: true,
    moduleResolution: 'bundler',
  },
});

const tmpDir = path.join(root, 'node_modules', '.print-routes');
mkdirSync(tmpDir, { recursive: true });
const tmpFile = path.join(tmpDir, `manifest-${process.pid}.mjs`);
writeFileSync(tmpFile, outputText, 'utf8');

const manifest = (await import(`file://${tmpFile}`)).default ??
  (await import(`file://${tmpFile}`));

// Clean up the temp file on exit so node_modules stays tidy.
process.on('exit', () => {
  try {
    unlinkSync(tmpFile);
  } catch {
    // ignore
  }
});

const { ROUTES, APP_NAME, DEMO_CREDENTIALS, LIMIT_REACHED_ACCOUNT } = manifest;

// ---------------------------------------------------------------------------
// URL / network helpers
// ---------------------------------------------------------------------------
const DEV_URL = process.env.DEV_URL || 'http://localhost:5173';

function stripTrailingSlash(url) {
  return url.replace(/\/+$/, '');
}

function portFrom(url) {
  try {
    return new URL(url).port;
  } catch {
    return '5173';
  }
}

function baseUrl() {
  return stripTrailingSlash(DEV_URL);
}

/** First non-loopback IPv4 address (empty string if none). */
function lanIp() {
  const nets = networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const net of nets[name] || []) {
      if (net.family === 'IPv4' && !net.internal) {
        return net.address;
      }
    }
  }
  return '';
}

/** Local network URL for mobile testing (mirrors the dev server port). */
function lanUrl() {
  const port = portFrom(baseUrl());
  const ip = lanIp();
  return ip ? `http://${ip}:${port}` : `http://localhost:${port}`;
}

function buildUrl(routePath) {
  return `${baseUrl()}${routePath}`;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------
const accessLabels = {
  public: 'Public',
  auth: 'Auth',
  app: 'App',
  legal: 'Legal',
  '404': '404',
};

function printPlain() {
  const out = [];

  out.push(`${APP_NAME} — routes`);
  out.push(`Dev:   ${baseUrl()}`);
  out.push(`Mobile: ${lanUrl()}`);
  out.push('');

  const header = '| Path | Access | Title | URL |';
  const divider = '|------|--------|--------|-----|';
  out.push(header);
  out.push(divider);

  for (const r of ROUTES) {
    out.push(
      `| \`${r.path}\` | ${accessLabels[r.access] || r.access} | ${r.title} | ${buildUrl(r.path)} |`
    );
  }

  out.push('');
  out.push('## Demo login (mock)');
  if (DEMO_CREDENTIALS) {
    out.push(`- Email: \`${DEMO_CREDENTIALS.email}\``);
    out.push(`- Password: \`${DEMO_CREDENTIALS.password}\``);
  } else {
    out.push('_No demo credentials defined._');
  }
  out.push('');

  out.push('## Mock limit-reached account');
  if (LIMIT_REACHED_ACCOUNT) {
    out.push('- Exists: yes');
  } else {
    out.push('- Exists: no');
    out.push("  The free daily limit (3 backtests) is enforced per-browser via");
    out.push("  localStorage key `bl_usage`. Any fresh free account hits it after");
    out.push('  3 successful backtests. The mock throws `{ code: "limit" }`.');
  }
  out.push('');

  out.push('## Manual test hints');
  out.push('- Switch language: tap the EN/عربي button in the header.');
  out.push('- Switch theme: tap the sun/moon button in the header.');
  out.push('- Resize to 360px: open the app in a 360px-wide viewport.');
  out.push('- Open /404: navigate to `/404` (or any unknown path).');
  out.push('');

  console.log(out.join('\n'));
}

function printMarkdown() {
  const out = [];

  out.push(`# ${APP_NAME} — routes`);
  out.push('');
  out.push('| Path | Access | Title | URL |');
  out.push('|------|--------|-------|-----|');
  for (const r of ROUTES) {
    out.push(
      `| \`${r.path}\` | ${accessLabels[r.access] || r.access} | ${r.title} | ${buildUrl(r.path)} |`
    );
  }
  out.push('');
  out.push('## Demo login (mock)');
  if (DEMO_CREDENTIALS) {
    out.push(`- Email: \`${DEMO_CREDENTIALS.email}\``);
    out.push(`- Password: \`${DEMO_CREDENTIALS.password}\``);
  } else {
    out.push('_No demo credentials defined._');
  }
  out.push('');
  out.push('## Mock limit-reached account');
  if (LIMIT_REACHED_ACCOUNT) {
    out.push('- Exists: yes');
  } else {
    out.push('- Exists: no');
    out.push("  The free daily limit (3 backtests) is enforced per-browser via");
    out.push("  localStorage key `bl_usage`. Any fresh free account hits it after");
    out.push('  3 successful backtests. The mock throws `{ code: "limit" }`.');
  }
  out.push('');

  console.log(out.join('\n'));
}

if (process.argv.includes('--markdown')) {
  printMarkdown();
} else if (process.argv.includes('--lan-ip')) {
  console.log(lanIp());
} else {
  printPlain();
}

