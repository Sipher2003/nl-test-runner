# Plain-English Test Runner (Python + Playwright + any LLM)

Write a test case in plain English; an LLM agent drives a real browser and reports **PASS / FAIL**.
Nothing is hard-coded to one website. The default LLM provider is Groq (free tier), but any
OpenAI-compatible API works.

```bash
python nl_test_runner.py "Log in as a customer and verify the dashboard is shown" --url https://phptravels.com/demo
```

## How it works

1. **Observe** - injects JS that tags every visible interactive element with a temporary `data-aid` and builds a
   compact snapshot: url, visible page text, elements (role, text, label, placeholder, options, `required`,
   `invalid` validation message), visible alerts, captcha context and credential blocks.
2. **Decide** - sends test case + notes + action history + snapshot to the LLM, which replies with ONE JSON action:
   `goto`, `click`, `fill`, `select`, `press`, `wait`, `note`, `assert_text`, `assert_no_text`,
   `assert_url_contains`, `finish`.
3. **Act** - Playwright executes the action and follows popups / new tabs.
4. **Verify in code** - assertions are checked against the real page. A test can only PASS if at least one
   assertion ran **on the final page state** and all of those held. A bare `finish(pass)` with no assertions is
   rejected, so the model cannot just claim success.
5. **Report** - console summary, `results/report.json`, `results/final.png`. Exit code 0 = PASS, 1 = FAIL.

## Key behaviours

- **Never guesses credentials.** It uses credentials from the test text or shown on a page. If none are available
  it looks for a "request demo access" form, fills it with realistic details, solves a simple math captcha and
  reads the credentials that appear.
- **Memory.** Credentials and other facts are saved as notes (via the `note` action and automatic capture of
  Email/Password blocks) and sent on every turn, so they survive new tabs.
- **Dialogs.** Acknowledge-style dialogs ("I understand", "Got it", "Accept", "I agree", "OK") are dismissed
  automatically.
- **Feedback to the agent.** Each step reports the current URL, whether the page changed, field read-back
  warnings, and repeat warnings. A run fails after 5 repeats of the same action within 8 steps.
- **Safe navigation.** `goto` only works for hosts mentioned in the test text or `--url`; page loads retry 3 times
  on network errors.
- **Model fallback.** `LLM_MODELS` is tried in order; the runner moves to the next model on daily-quota or
  model-not-found errors. Per-minute limits wait and retry.

## Setup

Requires Python 3.9+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

`requirements.txt`:
```
playwright
openai
```

Set your API key (free key at https://console.groq.com):

```bash
export GROQ_API_KEY=gsk_...                 # Windows PowerShell: $env:GROQ_API_KEY="gsk_..."
```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY` or `LLM_API_KEY` | API key | - |
| `LLM_MODELS` | comma-separated models, tried in order | `openai/gpt-oss-120b,openai/gpt-oss-20b` |
| `LLM_MODEL` | single model (alternative to `LLM_MODELS`) | - |
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |
| `DEMO_NAME`, `DEMO_BUSINESS`, `DEMO_PHONE` | details used if a site requires a demo-access form | Aarav Mehta / Mehta Travel Services / 9820147365 |
| `DEMO_EMAIL` | email for that form | `aarav.mehta.qa@mailinator.com` (set your own; some sites reject disposable domains) |

Other providers: set `LLM_BASE_URL`, `LLM_MODEL(S)` and `LLM_API_KEY` (OpenAI, OpenRouter, Cerebras, a local
Ollama server at `http://localhost:11434/v1`, ...). Check the provider's current model list, since free tiers vary.

## Usage

```bash
python nl_test_runner.py "<plain-English test case>" [--url START_URL] [--headless] [--max-steps N] [--out DIR]
```

| Flag | Purpose |
|---|---|
| `--url` | start page (optional if a URL is in the test text) |
| `--headless` | run without a visible browser |
| `--max-steps N` | cap on agent steps (default 25) |
| `--out DIR` | where `report.json` and `final.png` go (default `results/`) |

PowerShell example:

```powershell
$env:GROQ_API_KEY="gsk_..."
$env:DEMO_EMAIL="your.name@gmail.com"
$env:LLM_MODELS="openai/gpt-oss-120b,openai/gpt-oss-20b"
python nl_test_runner.py "Log in as a customer and verify the dashboard is shown" --url https://phptravels.com/demo
```

## Demo test cases

### Tried on the phptravels demo

| # | Test case | Outcome | Notes |
|---|---|---|---|
| 1 | `Open phptravels.com/demo, open the customer demo, log in as a customer and verify the dashboard is shown` | FAIL | Agent guessed credentials and got "Invalid Credentials". |
| 2 | `On the demo page, request demo access with name Test User, business Test Agency, email test.user@example.com, country India, WhatsApp 9876543210, and submit. When the credentials appear, note the customer email and password, open the customer account, log in with them and verify the customer dashboard is shown` | FAIL | Site rejected placeholder data ("Please enter your real name, not a placeholder", HTTP 422). Captcha was solved correctly; Country is pre-filled. |
| 3 | `Log in as a customer and verify the dashboard is shown` | FAIL | Form and captcha worked; login was blocked by a "Demo Environment" dialog and credentials lost when a new tab opened. |
| 4 | Same as #3, latest version | (add result) | - |

### Suggested cases

```bash
python nl_test_runner.py "Log in as a customer with a wrong password and verify an error message is shown" --url https://phptravels.com/demo
python nl_test_runner.py "Go to https://www.saucedemo.com, log in as standard_user with secret_sauce and verify the products page is shown"
python nl_test_runner.py "Go to https://www.saucedemo.com, log in as locked_out_user with secret_sauce and verify a locked out error is shown"
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `429 ... tokens per day (TPD)` | Daily quota for that model is used up. The runner switches to the next model in `LLM_MODELS`; otherwise wait or use another provider. |
| `429 ... tokens per minute` | Free plans have a small per-minute cap (about 8K tokens on Groq). The runner waits and retries. |
| `404 ... model does not exist` | Model renamed or retired. List current ones: `curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"` |
| `net::ERR_NETWORK_CHANGED` | Network or VPN changed mid-load. Retried automatically; keep the connection stable. |
| Form says "not a placeholder" / rejects the email | Set realistic `DEMO_*` values or your own `DEMO_EMAIL`. |
| Agent keeps repeating one action | Stuck detection fails the run at 5 repeats. Make the test text more specific. |

## Limitations / next steps

- iframes and shadow DOM are not snapshotted yet (loop over `page.frames`).
- An image-based captcha cannot be solved from text; it needs a vision-capable model with screenshots.
- Free tiers have small token caps; add a token budget and cache successful action sequences for fast replays.
- Auto-dismissed dialogs are limited to acknowledge-style buttons so the runner does not click through dialogs a test needs.