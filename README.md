# Plain-English Test Runner (Python + Playwright + Claude)

Write a test case in plain English; an LLM agent drives a real browser and reports PASS/FAIL.

## How it works
1. **Observe** - injects JS that tags every visible interactive element with a temporary `data-aid`
   and returns a compact snapshot (role, text, label, placeholder, options) plus visible page text.
2. **Decide** - sends test case + snapshot + action history to the LLM, which replies with ONE JSON action
   (`goto`, `click`, `fill`, `select`, `press`, `wait`, `assert_text`, `assert_no_text`,
   `assert_url_contains`, `finish`).
3. **Act** - Playwright executes the action. Nothing is tied to a specific site.
4. **Verify in code** - assertions are checked against the real page. A test can only PASS if at least one
   assertion ran and all assertions held, so the model can't just claim success.
5. **Report** - console summary, `results/report.json`, `results/final.png`. Exit code 0 = PASS, 1 = FAIL.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
export ANTHROPIC_API_KEY=sk-ant-...                 # Windows: set ANTHROPIC_API_KEY=...
# optional: export LLM_MODEL=<model name>
```

## Usage
```bash
python nl_test_runner.py "Open phptravels.com/demo, open the customer demo, log in as a customer and verify the dashboard is shown" --url https://phptravels.com/demo
python nl_test_runner.py "Log in as a customer with a wrong password and verify an error message is shown" --url https://phptravels.com/demo
python nl_test_runner.py "Go to https://www.saucedemo.com, log in as standard_user with secret_sauce and verify the products page is shown"
```
Flags: `--url`, `--headless`, `--max-steps N` (default 25), `--out DIR`.

## Limits / next steps
iframes aren't snapshotted yet (loop over `page.frames`); add a token budget; cache successful
action sequences for fast replays.
