# BacktestLab — routes

| Path | Access | Title | URL |
|------|--------|-------|-----|
| `/` | Public | Dashboard | http://localhost:5173/ |
| `/pricing` | Public | Pricing | http://localhost:5173/pricing |
| `/login` | Auth | Log in | http://localhost:5173/login |
| `/register` | Auth | Sign up | http://localhost:5173/register |
| `/forgot` | Auth | Forgot password | http://localhost:5173/forgot |
| `/reset` | Auth | Reset password | http://localhost:5173/reset |
| `/app` | App | Dashboard | http://localhost:5173/app |
| `/app/new` | App | New backtest | http://localhost:5173/app/new |
| `/app/results/:id` | App | Backtest results | http://localhost:5173/app/results/:id |
| `/app/history` | App | History | http://localhost:5173/app/history |
| `/app/compare` | App | Compare | http://localhost:5173/app/compare |
| `/app/templates` | App | Templates | http://localhost:5173/app/templates |
| `/app/settings` | App | Settings | http://localhost:5173/app/settings |
| `/app/billing` | App | Billing | http://localhost:5173/app/billing |
| `/app/help` | App | Help | http://localhost:5173/app/help |
| `/terms` | Legal | Terms of Service | http://localhost:5173/terms |
| `/privacy` | Legal | Privacy Policy | http://localhost:5173/privacy |
| `/risk` | Legal | Risk Disclosure | http://localhost:5173/risk |
| `*` | 404 | 404 — Not Found | http://localhost:5173* |

## Demo login (mock)
- Email: `demo@backtestlab.app`
- Password: `demo-pass-1234`

## Mock limit-reached account
- Exists: no
  The free daily limit (3 backtests) is enforced per-browser via
  localStorage key `bl_usage`. Any fresh free account hits it after
  3 successful backtests. The mock throws `{ code: "limit" }`.

