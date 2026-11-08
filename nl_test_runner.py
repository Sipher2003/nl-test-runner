#!/usr/bin/env python3
"""Run a plain-English test case in a browser using an LLM-driven agent loop."""
import argparse, json, os, re, sys, time
from pathlib import Path
import anthropic
from playwright.sync_api import sync_playwright

MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
client = anthropic.Anthropic()

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
      value:type==='password'?'***':String(e.value||'').slice(0,40)};
    if(e.tagName==='SELECT')o.options=[...e.options].map(x=>clean(x.text)).slice(0,30);
    if(e.checked)o.checked=true;
    if(e.disabled)o.disabled=true;
    out.push(o);
    if(i>=120)break;
  }
  return {url:location.href,title:document.title,
          page_text:clean(document.body.innerText).slice(0,1800),elements:out};
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
  {"action":"finish","verdict":"pass"|"fail","reason":"short explanation"}
Rules:
- Follow the test case literally. Use any URL or credentials given in the test case; if none are given but the page
  displays demo credentials for the requested role, use those.
- Before finishing with pass you MUST run assert_* actions that prove the expected outcome described in the test case.
- Choose assertion text you actually saw on the page (e.g. a heading or menu label that proves the expected state).
- If the expected outcome clearly does not happen, or you are stuck, finish with verdict "fail".
- Every element id comes only from the latest snapshot; ids change after every page change.
- Output raw JSON only, no markdown fences."""


def ask_llm(test, history, snap):
    msg = (f"TEST CASE:\n{test}\n\nACTION HISTORY (most recent last):\n"
           + "\n".join(history[-15:]) + f"\n\nCURRENT PAGE SNAPSHOT:\n{json.dumps(snap)[:14000]}")
    r = client.messages.create(model=MODEL, max_tokens=400, system=SYSTEM,
                               messages=[{"role": "user", "content": msg}])
    txt = r.content[0].text
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError(f"LLM returned no JSON: {txt[:200]}")
    return json.loads(m.group(0))


def execute(page, a, asserts):
    t = a.get("action")
    loc = lambda: page.locator(f'[data-aid="{a["id"]}"]').first
    if t == "goto":
        page.goto(a["url"], wait_until="domcontentloaded", timeout=45000)
    elif t == "click":
        loc().click(timeout=8000)
    elif t == "fill":
        loc().fill(a["text"], timeout=8000)
    elif t == "select":
        try:
            loc().select_option(label=a["option"], timeout=5000)
        except Exception:
            loc().select_option(value=a["option"], timeout=5000)
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
    return "ok"


def run(test, start_url, headless, max_steps, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    history, asserts, log = [], [], []
    verdict, reason = "fail", "Step limit reached without a conclusion"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1366, "height": 850})
        cur = {"page": ctx.new_page()}
        ctx.on("page", lambda pg: cur.update(page=pg))  # follow popups / new tabs
        if start_url:
            cur["page"].goto(start_url, wait_until="domcontentloaded", timeout=45000)
        for step in range(1, max_steps + 1):
            page = cur["page"]
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            try:
                snap = page.evaluate(SNAPSHOT_JS)
            except Exception:
                page.wait_for_timeout(1000)
                snap = page.evaluate(SNAPSHOT_JS)
            try:
                a = ask_llm(test, history, snap)
            except Exception as e:
                history.append(f"{step}. LLM error: {e}")
                continue
            if a.get("action") == "finish":
                verdict, reason = a.get("verdict", "fail"), a.get("reason", "")
                log.append({"step": step, "action": a})
                break
            try:
                res = execute(page, a, asserts)
            except Exception as e:
                res = f"ERROR: {str(e)[:150]}"
            print(f"  step {step}: {json.dumps(a)} -> {res}")
            history.append(f"{step}. {json.dumps(a)} -> {res}")
            log.append({"step": step, "action": a, "result": res})
        shot = outdir / "final.png"
        try:
            cur["page"].screenshot(path=str(shot), full_page=True)
        except Exception:
            pass
        final_url = cur["page"].url
        browser.close()

    # Final verdict is enforced in code, not trusted from the LLM.
    if verdict == "pass":
        if not asserts:
            verdict, reason = "fail", "LLM claimed pass but ran no verifiable assertions"
        elif not all(ok for _, ok in asserts):
            verdict, reason = "fail", "Assertion failed: " + "; ".join(n for n, ok in asserts if not ok)
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
