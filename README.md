# Plain-English Test Runner

Write a test case in plain English. An LLM agent runs it in a real browser (Playwright), records a video, and reports **PASS** or **FAIL**.

```bash
python nl_test_runner.py "Log in as a customer and verify the dashboard is shown" --url https://phptravels.com/demo
```

## How it works

1. **Observe:** the page's visible interactive elements are tagged with temporary ids and sent to the LLM as a compact snapshot (element text, labels, placeholders, location on the page, validation errors, visible alerts and any credentials shown on the page).
2. **Decide:** the LLM replies with one JSON action: `goto`, `click`, `fill`, `select`, `press`, `wait`, `note`, `assert_text`, `assert_no_text`, `assert_url_contains` or `finish`.
3. **Act:** Playwright performs the action and follows new tabs.
4. **Verify in code:** a test can only PASS if the agent ran assertions on the final page state and every one held. The model cannot declare a pass on its own.
5. **Report:** console summary, `results/report.json`, `results/final.png` and a video of the run (`results/run.mp4`). Exit code is `0` for PASS and `1` for FAIL.

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
pip install -r requirements.txt    # playwright, openai, imageio-ffmpeg
playwright install chromium
```

## Configure the AI model and email

The agent needs an LLM API key. The default provider is Groq, which has a free tier (get a key at https://console.groq.com). Set these in the same terminal you run the tool from; they are lost when the terminal closes.

**Windows PowerShell**
```powershell
$env:GROQ_API_KEY="gsk_your_key_here"
$env:LLM_MODELS="openai/gpt-oss-120b,openai/gpt-oss-20b"
$env:DEMO_EMAIL="your.name@gmail.com"
```

**Windows cmd**
```bat
set GROQ_API_KEY=gsk_your_key_here
set LLM_MODELS=openai/gpt-oss-120b,openai/gpt-oss-20b
set DEMO_EMAIL=your.name@gmail.com
```

**macOS / Linux**
```bash
export GROQ_API_KEY=gsk_your_key_here
export LLM_MODELS="openai/gpt-oss-120b,openai/gpt-oss-20b"
export DEMO_EMAIL="your.name@gmail.com"
```

- `LLM_MODELS` is a comma-separated list. The first model is used, and the next one takes over if the first hits its daily quota.
- `DEMO_EMAIL` is used when a site requires a demo-access form (for example phptravels). **Set it to an address you control.** Some sites email the credentials or reject disposable domains, and the built-in default address has not been verified to work.

### Using a different provider

Any OpenAI-compatible API works. Set the endpoint, key and model:

```powershell
# OpenAI
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_API_KEY="sk-..."
$env:LLM_MODELS="<model name>"

# Local Ollama (no key needed)
$env:LLM_BASE_URL="http://localhost:11434/v1"
$env:LLM_MODELS="<local model name>"
```

Check the provider's current model list, since free tiers and model names change. On Groq, list the models your key can use with:

```bash
curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
```

### All environment variables

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY` or `LLM_API_KEY` | API key | none |
| `LLM_MODELS` | comma-separated models, tried in order | `openai/gpt-oss-120b,openai/gpt-oss-20b` |
| `LLM_MODEL` | single model (alternative to `LLM_MODELS`) | none |
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |
| `DEMO_EMAIL` | email for demo-access forms | `aarav.mehta.qa@mailinator.com` |
| `DEMO_NAME`, `DEMO_BUSINESS`, `DEMO_PHONE` | other demo-form details | Aarav Mehta, Mehta Travel Services, 9820147365 |

## Run

```bash
python nl_test_runner.py "<plain-English test case>" [--url START_URL] [--headless] [--max-steps N] [--out DIR] [--no-video] [--debug]
```

| Option | Purpose |
|---|---|
| `--url` | start page (optional if the URL is in the test text) |
| `--headless` | run without a visible browser |
| `--max-steps N` | cap on agent steps (default 25) |
| `--out DIR` | output folder (default `results/`); use a new folder to keep earlier runs |
| `--no-video` | do not record a video of the run |
| `--debug` | save each step's snapshot and screenshot, and print network POSTs and errors |

Full example (PowerShell):

```powershell
$env:GROQ_API_KEY="gsk_your_key_here"
$env:LLM_MODELS="openai/gpt-oss-120b,openai/gpt-oss-20b"
$env:DEMO_EMAIL="your.name@gmail.com"
python nl_test_runner.py "Log in as a customer and verify the dashboard is shown" --url https://phptravels.com/demo
```

When the run ends, open `results/run.mp4` to watch it.

## Output

| File | Contents |
|---|---|
| `results/report.json` | verdict, reason, assertions, every step, video path |
| `results/final.png` | full-page screenshot of the final state |
| `results/run.mp4` | recording of the browser during the run |
| `results/step_NN_snapshot.json`, `step_NN.png` | per-step data, only with `--debug` |

Tabs opened during a run are recorded separately and joined in order into `run.mp4`. If ffmpeg is unavailable the separate `video_N.webm` files are kept instead.

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
- Video recording was added after the phptravels pass and has only been tested in isolation (joining clips), not across a full live run.

## Limitations

- **Free-tier models are limited and not fully reliable.** On Groq's free plan there is a daily token quota per model and a small per-minute cap. A run can exhaust the daily quota, and the agent sometimes picks the wrong element, repeats actions or takes extra steps. A typical run takes several minutes.
- **Results depend on the model.** The smaller fallback model is less accurate than the larger one.
- **Assertions are only as good as the model's choice.** The code guarantees assertions ran and held, but not that they are the strongest possible check. The test text should state the expected outcome clearly.
- **Captchas:** only simple math captchas that appear as text can be solved. Image-based captchas and bot-protection challenges are not supported.
- **Page structure:** iframes and shadow DOM are not read, so elements inside them are invisible to the agent.
- **Dialog handling is conservative:** only acknowledge-style buttons are clicked automatically, so other blocking dialogs must be handled by the agent.
- **Video covers the browser page only.** It does not show the terminal or the PASS/FAIL line. Joining tabs needs ffmpeg (installed via `imageio-ffmpeg`); without it the per-tab `.webm` files are kept.
- **Sites that need real accounts or real data** (payments, email verification, one-time codes) cannot be tested.
- **The tool may submit forms on live sites.** Do not point it at sites you do not have permission to test.