# Plain-English Test Runner

Write a test case in plain English. An LLM agent runs it in a real browser (Playwright) and reports **PASS** or **FAIL**.

```bash
python nl_test_runner.py "Log in as a customer and verify the dashboard is shown" --url https://phptravels.com/demo
```

## How it works

1. **Observe:** the page's visible interactive elements are tagged with temporary ids and sent to the LLM as a compact snapshot (element text, labels, placeholders, location on the page, validation errors, visible alerts and any credentials shown on the page).
2. **Decide:** the LLM replies with one JSON action: `goto`, `click`, `fill`, `select`, `press`, `wait`, `note`, `assert_text`, `assert_no_text`, `assert_url_contains` or `finish`.
3. **Act:** Playwright performs the action and follows new tabs.
4. **Verify in code:** a test can only PASS if the agent ran assertions on the final page state and every one held. The model cannot declare a pass on its own.
5. **Report:** console summary, `results/report.json`, `results/final.png`. Exit code is `0` for PASS and `1` for FAIL.

Nothing is specific to one website. Safeguards in the code:

- Credentials must come from the test text, saved notes or the page. On login pages, typing anything else is blocked, as is typing credentials into footer or header fields.
- `goto` is limited to hosts named in the test text or `--url`.
- Acknowledge-style dialogs ("I understand", "Got it", "Accept", "I agree", "OK") are dismissed automatically.
- If a site needs a demo-access form to reveal credentials, the agent fills it with realistic details and solves simple math captchas.
- Stuck loops are detected and failed early; navigation errors are retried.

## Setup

Requires Python 3.9+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt    # playwright, openai
playwright install chromium
```

Set an API key. The default provider is Groq, which has a free tier (key at https://console.groq.com):

```bash
export GROQ_API_KEY=gsk_...        # Windows PowerShell: $env:GROQ_API_KEY="gsk_..."
```

## Run

```bash
python nl_test_runner.py "<plain-English test case>" [--url START_URL] [--headless] [--max-steps N] [--out DIR] [--debug]
```

| Option | Purpose |
|---|---|
| `--url` | start page (optional if the URL is in the test text) |
| `--headless` | run without a visible browser |
| `--max-steps N` | cap on agent steps (default 25) |
| `--out DIR` | output folder (default `results/`) |
| `--debug` | save each step's snapshot and screenshot, and print network POSTs and errors |

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY` or `LLM_API_KEY` | API key | none |
| `LLM_MODELS` | comma-separated models; the next is used when one hits its daily quota | `openai/gpt-oss-120b,openai/gpt-oss-20b` |
| `LLM_MODEL` | single model (alternative to `LLM_MODELS`) | none |
| `LLM_BASE_URL` | any OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |
| `DEMO_EMAIL` | email for sites that require a demo-access form | `aarav.mehta.qa@mailinator.com` |
| `DEMO_NAME`, `DEMO_BUSINESS`, `DEMO_PHONE` | other form details | Aarav Mehta, Mehta Travel Services, 9820147365 |

**Please set `DEMO_EMAIL` to an address you control.** Some sites send credentials by email or reject disposable domains, and the default address has not been verified to work.

Other providers (OpenAI, OpenRouter, a local Ollama server and so on) work by changing `LLM_BASE_URL`, `LLM_MODELS` and `LLM_API_KEY`.

## Example test cases

```bash
python nl_test_runner.py "Log in as a customer and verify the dashboard is shown" --url https://phptravels.com/demo
python nl_test_runner.py "Log in as a customer with a wrong password and verify an error message is shown" --url https://phptravels.com/demo
python nl_test_runner.py "Go to https://www.saucedemo.com, log in as standard_user with secret_sauce and verify the products page is shown"
```

## Test status

- The phptravels customer-login case above has been run to a PASS: the agent submitted the demo-access form, read the customer credentials from the page, logged in, and the runner confirmed the dashboard.
- It took many attempts to get there, and it was a single clean run. LLM behaviour varies between runs, so results are not guaranteed to be repeatable.
- The wrong-password and saucedemo cases are suggestions and have **not** been run.
- No other websites have been tested.

## Limitations

- **Free-tier models are limited and not fully reliable.** On Groq's free plan there is a daily token quota per model and a small per-minute cap. A run can exhaust the daily quota, and the agent sometimes picks the wrong element, repeats actions or takes extra steps. A typical run takes several minutes.
- **Results depend on the model.** The smaller fallback model is less accurate than the larger one.
- **Assertions are only as good as the model's choice.** The code guarantees assertions ran and held, but not that they are the strongest possible check. The test text should state the expected outcome clearly.
- **Captchas:** only simple math captchas that appear as text can be solved. Image-based captchas and bot-protection challenges are not supported.
- **Page structure:** iframes and shadow DOM are not read, so elements inside them are invisible to the agent.
- **Dialog handling is conservative:** only acknowledge-style buttons are clicked automatically, so other blocking dialogs must be handled by the agent.
- **Sites that need real accounts or real data** (payments, email verification, one-time codes) cannot be tested.
- **The tool may submit forms on live sites.** Do not point it at sites you do not have permission to test.