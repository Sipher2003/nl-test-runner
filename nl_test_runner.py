#!/usr/bin/env python3
"""Run a plain-English test case in a browser using an LLM-driven agent loop.

Works with any OpenAI-compatible API (Groq by default).
  export GROQ_API_KEY=gsk_...                 (or LLM_API_KEY for other providers)
  export LLM_MODEL=openai/gpt-oss-120b        (optional)
  export LLM_BASE_URL=https://api.groq.com/openai/v1   (optional)
"""
import argparse, json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from openai import OpenAI

MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY") or "none",
    base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
)

ALLOWED = ""  # text of the test case + start URL; goto is only allowed to hosts mentioned here

SNAPSHOT_JS = """() => {
  const clean=s=>(s||'').replace(/\\s+/g,' ').trim();
  const vis=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return s.visibility!=='hidden'&&s.display!=='none'&&r.width>0&&r.height>0;};
  document.querySelectorAll('[data-aid]').forEach(e=>e.removeAttribute('data-aid'));
  const sel='a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=tab],'
           +'[role=menuitem],[role=checkbox],[role=radio],[onclick],summary';
  const out=[];let i=0;
  for(const e of document.querySelectorAll(sel)){
    if(!vis(e))continue;
    const id=++i;e.setAttribute('data-aid',id);
    const type=e.getAttribute('type')||'';
    const o={id,tag:e.tagName.toLowerCase(),type,
      text:clean(e.innerText||'').slice(0,60),
      label:e.labels&&e.labels[0]?clean(e.labels[0].innerText):'',
      aria:e.getAttribute('aria-label')||'',placeholder:e.getAttribute('placeholder')||'',
      name:e.getAttribute('name')||'',href:(e.getAttribute('href')||'').slice(0,80),
      value:(type==='password'&&!e.readOnly&&!e.disabled)?'***':String(e.value||'').slice(0,60)};
    if(e.tagName==='SELECT')o.options=[...e.options].map(x=>clean(x.text)).slice(0,30);
    if(e.checked)o.checked=true;
    if(e.disabled)o.disabled=true;
    if(e.required)o.required=true;
    if(e.willValidate&&!e.checkValidity())o.invalid=(e.validationMessage||'invalid').slice(0,60);
    for(const k in o){if(o[k]===''||o[k]===false)delete o[k];}
    out.push(o);
    if(i>=120)break;
  }
  const credential_blocks=[];
  for(const e of document.querySelectorAll('li,dt,dd,th,td,label,span,div,p,strong,b')){
    if(e.children.length>0||!vis(e))continue;
    const lt=clean(e.innerText||'');
    if(!/^(e-?mail|username|user name|login|password|pass)\\s*:?$/i.test(lt))continue;
    let n=e,t=lt;
    for(let k=0;k<5&&n.parentElement;k++){n=n.parentElement;t=clean(n.innerText||'');
      if(/password/i.test(t)&&/@/.test(t))break;if(t.length>400)break;}
    if(t.length<=400&&!credential_blocks.includes(t))credential_blocks.push(t);
    if(credential_blocks.length>=6)break;
  }
  const alerts=[...document.querySelectorAll('[role=alert],.alert,.error,.text-danger,.invalid-feedback,[class*=error i]')]
    .filter(vis).map(x=>clean(x.innerText)).filter(Boolean).slice(0,5);
  const captcha=[...document.querySelectorAll('input,select')]
    .filter(x=>vis(x)&&/captcha|security|human|robot|verif/i.test((x.name||'')+(x.id||'')+(x.placeholder||'')+(x.className||'')+(x.getAttribute('aria-label')||'')))
    .map(x=>{const c=x.closest('div,fieldset,form');return clean((c&&c.innerText)||'').slice(0,100);}).slice(0,2);
  return {url:location.href,title:document.title,alerts,captcha,credential_blocks,
          page_text:clean(document.body.innerText).slice(0,3500),elements:out};
}"""

DISMISS_JS = """() => {
  const vis=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return s.visibility!=='hidden'&&s.display!=='none'&&r.width>0&&r.height>0;};
  const re=/^(i understand|understand|got it|accept|i agree|agree|allow all|dismiss|no,? thanks|ok|okay)\\b/i;
  const sel='[role=dialog],[role=alertdialog],[aria-modal=true],dialog[open],.modal.show,.modal[style*=block]';
  const boxes=[...document.querySelectorAll(sel)].filter(vis);
  for(const d of document.querySelectorAll('div,section,aside')){
    const s=getComputedStyle(d);
    if(s.position==='fixed'&&vis(d)){const r=d.getBoundingClientRect();
      if(r.width>=innerWidth*0.4&&r.height>=innerHeight*0.3)boxes.push(d);}
  }
  for(const d of boxes){
    for(const b of d.querySelectorAll('button,a,[role=button],input[type=button],input[type=submit]')){
      const t=(b.innerText||b.value||'').replace(/\\s+/g,' ').trim();
      if(vis(b)&&re.test(t)){b.click();return t;}
    }
  }
  return '';
}"""

SYSTEM = """You are a QA automation agent controlling a real browser to execute a test case written in plain English.
Each turn you get the test case, your action history, and a snapshot of the current page
(url, visible text, interactive elements with numeric ids).
Reply with EXACTLY ONE JSON object and nothing else. Allowed actions:
  {"action":"goto","url":"https://..."}
  {"action":"click","id":N}
  {"action":"fill","id":N,"text":"..."}
  {"action":"select","id":N,"option":"visible option text"}
  {"action":"press","key":"Enter"}
  {"action":"wait","ms":1000}
  {"action":"assert_text","text":"text that must be visible on the page"}
  {"action":"assert_no_text","text":"text that must NOT be visible"}
  {"action":"assert_url_contains","text":"substring"}
  {"action":"note","text":"fact to remember, e.g. the customer email and password shown on the page"}
  {"action":"finish","verdict":"pass"|"fail","reason":"short explanation"}
Rules:
- Follow the test case literally. Use any URL or credentials given in the test case; if none are given but the page
  displays demo credentials for the requested role, use those exactly as shown.
- Before finishing with pass you MUST run assert_* actions on the FINAL page state that prove the expected outcome
  described in the test case.
- Choose assertion text you actually saw on the page (e.g. a heading or menu label that proves the expected state).
- NEVER guess or invent credentials. Use only credentials given in the test case or actually shown on a page.
- If credentials are needed but not visible, look for a request-access / demo / sign-up form on the site and fill it
  with these realistic test details: __PROFILE__. Leave a country that is already filled in. Solve any simple math
  captcha, submit, and read the credentials that appear.
- If a form rejects your data as a placeholder or fake, change it to realistic-looking values. Never use words like
  "test", "demo", "example", "abc", or sequential digits in names, businesses, emails or phone numbers.
- As soon as credentials appear on a page, save them with a "note" action BEFORE clicking anything that opens another
  page or tab. Notes are shown to you every turn.
- Fill EVERY field of a form, including dropdowns/selects such as country (use "select"), before submitting.
- For a math captcha, read the numbers from the "captcha" hint or the page text and type the exact sum; never guess.
- If a submit click does nothing ("page did not change"), read "alerts" and any element with "invalid" in the
  snapshot, fix exactly those fields, then submit again. Do not click submit again without changing something.
- Log in with the exact email and password for the requested role from NOTES or "credential_blocks" (Customer
  credentials for a customer login). Never type made-up credentials.
- If a modal/dialog blocks the page, click its acknowledge/close button first.
- Never invent URLs. Only use URLs from the test case, or follow links shown on the page.
- If an assertion fails, do not repeat it. Look at the page text and choose a different check, or fix the cause.
- If a click doesn't change the page, try a different element instead of repeating the same click.
- If login seems to fail (still on the login page, or an error is shown), re-read the credentials shown on the page
  exactly and retype them.
- If the expected outcome clearly does not happen, or you are stuck, finish with verdict "fail".
- Every element id comes only from the latest snapshot; ids change after every page change.
- Output raw JSON only, no markdown fences."""


PROFILE = (f'name "{os.getenv("DEMO_NAME", "Aarav Mehta")}", '
           f'business "{os.getenv("DEMO_BUSINESS", "Mehta Travel Services")}", '
           f'email "{os.getenv("DEMO_EMAIL", "aarav.mehta.qa@mailinator.com")}", '
           f'phone "{os.getenv("DEMO_PHONE", "9820147365")}"')
SYSTEM = SYSTEM.replace("__PROFILE__", PROFILE)


def ask_llm(test, history, snap, notes):
    msg = (f"TEST CASE:\n{test}\n\nACTION HISTORY (most recent last):\n"
           + "\n".join(history[-10:])
           + "\n\nNOTES (saved facts):\n" + ("\n".join(notes) or "(none)")
           + f"\n\nCURRENT PAGE SNAPSHOT:\n{json.dumps(snap, separators=(',',':'))[:7000]}")
    last = ""
    temp = 0
    for _ in range(3):  # retry on malformed JSON or a stray tool call
        try:
          r = client.chat.completions.create(
            model=MODEL, max_tokens=1500, temperature=temp,
            extra_body={"reasoning_effort": "low"},  # remove this line if your provider rejects it
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": msg}],
          )
        except Exception as e:
            if "Tool choice" in str(e) or "tool" in str(e).lower() and "400" in str(e):
                temp = 0.5  # different sample on retry
                continue
            raise
        temp = 0.3
        last = r.choices[0].message.content or ""
        m = re.search(r"\{.*\}", last, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError(f"LLM returned no valid JSON: {last[:200]}")


def dismiss_overlays(page):
    """Click acknowledge-style buttons ("I understand", "Accept", ...) inside blocking dialogs."""
    try:
        t = page.evaluate(DISMISS_JS)
        if t:
            print(f"  (auto-dismissed dialog via '{t}')")
            page.wait_for_timeout(600)
        return t
    except Exception:
        return ""


def goto_with_retry(page, url, tries=3):
    """Navigate, retrying transient network errors (e.g. ERR_NETWORK_CHANGED, wifi/VPN switches)."""
    last = None
    for i in range(tries):
        try:
            return page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            last = e
            print(f"  navigation to {url} failed ({str(e).splitlines()[0][:90]}); retry {i + 1}/{tries}")
            time.sleep(2 * (i + 1))
    raise last


def host_allowed(url):
    host = urlparse(url).netloc.lower().replace("www.", "")
    if not host:
        return True
    base = ".".join(host.split(".")[-2:])
    return host in ALLOWED or base in ALLOWED


def execute(page, a, asserts):
    t = a.get("action")
    warn = ""
    loc = lambda: page.locator(f'[data-aid="{a["id"]}"]').first
    if t == "goto":
        if not host_allowed(a["url"]):
            raise ValueError("goto blocked: host is not in the test case. Use links on the page instead.")
        goto_with_retry(page, a["url"])
    elif t == "click":
        loc().click(timeout=4000)
    elif t == "fill":
        loc().fill(a["text"], timeout=4000)
        try:
            got = loc().input_value(timeout=1500)
            if got != a["text"]:
                warn = f" | WARNING: field shows {got!r} after fill (expected {a['text']!r})"
        except Exception:
            pass
    elif t == "select":
        try:
            loc().select_option(label=a["option"], timeout=4000)
        except Exception:
            loc().select_option(value=a["option"], timeout=4000)
    elif t == "press":
        page.keyboard.press(a["key"])
    elif t == "wait":
        page.wait_for_timeout(min(int(a.get("ms", 1000)), 5000))
    elif t == "assert_text":
        ok = True
        try:
            page.wait_for_function("t=>document.body.innerText.toLowerCase().includes(t.toLowerCase())",
                                   arg=a["text"], timeout=7000)
        except Exception:
            ok = False
        asserts.append((f"text visible: {a['text']!r}", ok))
        return "assertion " + ("PASSED" if ok else "FAILED")
    elif t == "assert_no_text":
        page.wait_for_timeout(1000)
        ok = a["text"].lower() not in page.inner_text("body").lower()
        asserts.append((f"text absent: {a['text']!r}", ok))
        return "assertion " + ("PASSED" if ok else "FAILED")
    elif t == "assert_url_contains":
        try:
            page.wait_for_url(re.compile(re.escape(a["text"])), timeout=7000)
            ok = True
        except Exception:
            ok = False
        asserts.append((f"url contains: {a['text']!r}", ok))
        return "assertion " + ("PASSED" if ok else "FAILED")
    else:
        raise ValueError(f"unknown action {t}")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    return "ok" + warn


def run(test, start_url, headless, max_steps, outdir):
    global ALLOWED
    ALLOWED = (test + " " + (start_url or "")).lower().replace("www.", "")
    outdir.mkdir(parents=True, exist_ok=True)
    history, asserts, log = [], [], []
    notes, recent, repeats, seen_blocks = [], [], 0, set()
    last_action_idx = 0  # asserts made before this index belong to an earlier page state
    verdict, reason = "fail", "Step limit reached without a conclusion"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1366, "height": 850})
        cur = {"page": ctx.new_page()}
        ctx.on("page", lambda pg: cur.update(page=pg))  # follow popups / new tabs
        start_err = None
        if start_url:
            try:
                goto_with_retry(cur["page"], start_url)
            except Exception as e:
                start_err = str(e).splitlines()[0][:200]
                reason = f"Could not open start URL {start_url}: {start_err}"
        for step in range(1, 1 if start_err else max_steps + 1):
            page = cur["page"]
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            dismiss_overlays(page)
            try:
                snap = page.evaluate(SNAPSHOT_JS)
            except Exception:
                page.wait_for_timeout(1000)
                snap = page.evaluate(SNAPSHOT_JS)
            for blk in snap.get("credential_blocks") or []:
                if "@" in blk and re.search("password", blk, re.I) and blk not in seen_blocks:
                    seen_blocks.add(blk)
                    notes.append("Credentials seen on a page: " + blk[:300])
                    notes[:] = notes[-10:]
                    print(f"  (auto-saved credentials: {blk[:110]}...)")
            try:
                a = ask_llm(test, history, snap, notes)
            except Exception as e:
                msg = str(e)
                print(f"  step {step}: LLM ERROR -> {msg[:300]}")
                fatal = any(k in msg for k in ("401", "403", "404", "invalid_api_key",
                                               "model_not_found", "decommissioned",
                                               "tokens per day", "(TPD)"))
                if fatal:
                    verdict, reason = "fail", f"LLM configuration error: {msg[:200]}"
                    break
                time.sleep(8 if "429" in msg or "rate" in msg.lower() else 2)
                history.append(f"{step}. LLM error: {msg[:100]}")
                continue

            if a.get("action") == "note":
                notes.append(str(a.get("text", ""))[:400])
                print(f"  step {step}: NOTE saved -> {notes[-1][:120]}")
                history.append(f"{step}. note saved")
                log.append({"step": step, "action": a, "result": "saved"})
                continue

            if a.get("action") == "finish":
                v = str(a.get("verdict", "fail")).lower()
                final = asserts[last_action_idx:]
                if v == "pass" and not final:
                    # don't accept a bare "pass": make the agent prove it
                    note = "finish(pass) rejected: run assert_* actions on the current page first."
                    print(f"  step {step}: {note}")
                    history.append(f"{step}. {note}")
                    log.append({"step": step, "action": a, "result": note})
                    continue
                verdict, reason = v, a.get("reason", "")
                log.append({"step": step, "action": a})
                break

            try:
                before_url, before_txt = page.url, page.inner_text("body")[:3000]
            except Exception:
                before_url, before_txt = None, None
            try:
                res = execute(page, a, asserts)
            except Exception as e:
                res = f"ERROR: {str(e)[:150]}"
            if not str(a.get("action", "")).startswith("assert_"):
                last_action_idx = len(asserts)
            sig = json.dumps(a, sort_keys=True)
            recent.append(sig)
            repeats = recent[-8:].count(sig)
            if a.get("action") in ("click", "press") and before_txt is not None:
                try:
                    if cur["page"] is page and page.url == before_url and page.inner_text("body")[:3000] == before_txt:
                        res += " | page did not change"
                except Exception:
                    pass
            res += f" | now at {cur['page'].url}"
            if 3 <= repeats < 5:
                res += " | WARNING: same action 3 times with no progress. Do something different or finish with fail."
            if repeats >= 5:
                print(f"  step {step}: stuck repeating {sig}")
                verdict, reason = "fail", "Agent got stuck repeating the same action"
                log.append({"step": step, "action": a, "result": res})
                break
            print(f"  step {step}: {json.dumps(a)} -> {res}")
            history.append(f"{step}. {json.dumps(a)} -> {res}")
            log.append({"step": step, "action": a, "result": res})

        try:
            cur["page"].screenshot(path=str(outdir / "final.png"), full_page=True)
        except Exception:
            pass
        final_url = cur["page"].url
        browser.close()

    # Final verdict is enforced in code: only assertions made on the final page state count.
    final = asserts[last_action_idx:]
    if verdict == "pass":
        if not final:
            verdict, reason = "fail", "No assertions on the final page state"
        elif not all(ok for _, ok in final):
            verdict, reason = "fail", "Assertion failed: " + "; ".join(n for n, ok in final if not ok)
    report = {"test": test, "result": verdict.upper(), "reason": reason, "final_url": final_url,
              "assertions": [{"check": n, "passed": ok} for n, ok in asserts], "steps": log}
    (outdir / "report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("test", help="plain-English test case")
    ap.add_argument("--url", help="optional start URL (or put the URL in the test text)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-steps", type=int, default=25)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    t0 = time.time()
    rep = run(args.test, args.url, args.headless, args.max_steps, Path(args.out))
    print(f"\n=== {rep['result']} === {rep['reason']}")
    for a in rep["assertions"]:
        print(f"  [{'PASS' if a['passed'] else 'FAIL'}] {a['check']}")
    print(f"({time.time()-t0:.0f}s) report: {args.out}/report.json")
    sys.exit(0 if rep["result"] == "PASS" else 1)