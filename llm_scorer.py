"""Step 3b - LLM re-scoring of the heuristic shortlist. Provider-agnostic: swap with --provider/--model or env vars.

Cost control: the LLM never sees all ~18,600 windows. Code shortlists K clips per episode; ONE call per episode.
Safety: the model only scores clips whose timestamps came from the parser. It cannot invent timestamps,
and quoted hook/cliffhanger lines must appear verbatim in the clip (checked in code) or they are replaced.
"""
import os, json, re, hashlib, urllib.request, urllib.error
from parse import transcript, fmt
from engine import W

SYSTEM = """You are a short-drama promo editor for TikTok/Reels/YouTube Shorts. You judge candidate clips cut from one episode of a vertical microdrama.
A great promo (20-60s): (1) HOOK - in the FIRST 3 SECONDS something makes a scrolling viewer stop (slap, reveal, shocking line, threat);
(2) CLIFFHANGER - it cuts at an UNRESOLVED moment so the viewer must know what happens next;
(3) STANDALONE - someone who has never seen the show understands who is fighting about what.
Be a harsh grader: most clips are 3-6 out of 10. 8+ is rare. Penalise: hooks that need earlier context, endings that resolve the tension, clips that are just talking with no stakes.
Return ONLY a JSON array, no prose, no markdown fences."""

def build_prompt(ep, shortlist):
    parts = [f"EPISODE {ep.num}\nLOGLINE: {ep.logline}\nCONTINUITY NOTES (what earlier episodes established; a new viewer would NOT know this): {ep.continuity}\n"]
    for i, c in enumerate(shortlist):
        segs = c["segments"]
        body = []
        for j, sg in enumerate(segs):
            if j: body.append("--- CUT (skipped footage) ---")
            body.append(transcript(ep, sg["start"], sg["end"]))
        parts.append(f"CLIP id={i} ({c['total_seconds']}s)\n" + "\n".join(body))
    parts.append('For EVERY clip return an object: {"id":int,"hook_score":0-10,"hook_line":"verbatim text from first 3s","cliffhanger_score":0-10,"cliffhanger_line":"verbatim last line/action","standalone_score":0-10,"why":"<=25 words on why it works or fails","risk":"<=15 words: what could go wrong"}')
    return "\n\n".join(parts)

# ---------------------------------------------------------------- providers (plain HTTP, no SDK needed)
def _post(url, headers, payload, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} from provider: {e.read().decode()[:300]}")

def call_llm(provider, model, system, user):
    p = provider.lower()
    if p == "anthropic":
        r = _post("https://api.anthropic.com/v1/messages", {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                  {"model": model, "max_tokens": 3000, "system": system, "messages": [{"role": "user", "content": user}]})
        return "".join(b.get("text", "") for b in r["content"])
    if p in ("openai", "groq", "openrouter"):
        base = {"openai": "https://api.openai.com/v1", "groq": "https://api.groq.com/openai/v1", "openrouter": "https://openrouter.ai/api/v1"}[p]
        key = os.environ[{"openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[p]]
        r = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"},
                  {"model": model, "temperature": 0, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        return r["choices"][0]["message"]["content"]
    if p == "gemini":
        key = os.environ["GEMINI_API_KEY"]
        r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}", {},
                  {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})
        return r["candidates"][0]["content"]["parts"][0]["text"]
    raise ValueError(f"unknown provider {provider}")

DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini", "groq": "llama-3.3-70b-versatile", "gemini": "gemini-2.0-flash", "openrouter": "google/gemini-2.0-flash-001"}

def _mock(ep, shortlist):
    """PLUMBING TEST ONLY. Echoes heuristic scores as fake 'LLM' JSON so the pipeline can be tested with no API key."""
    out = []
    for i, c in enumerate(shortlist):
        out.append({"id": i, "hook_score": c["hook_score"], "hook_line": c["hook"].split(": ", 1)[-1][:60],
                    "cliffhanger_score": c["cliffhanger_score"], "cliffhanger_line": c["cliffhanger"].split(": ", 1)[-1][:60],
                    "standalone_score": c["standalone_score"], "why": "[MOCK] " + c["why"][:80], "risk": "mock"})
    return json.dumps(out)

# ---------------------------------------------------------------- parse + validate
def _extract_json(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try: return json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.S)
        if m: return json.loads(m.group(0))
        raise

def _norm(s): return re.sub(r"\W+", " ", s.lower()).strip()

def rescore(ep, shortlist, provider, model, cache_dir="cache", log=None):
    """Returns shortlist with LLM scores merged in. Falls back to heuristic scores for a clip if its data is invalid."""
    prompt = build_prompt(ep, shortlist)
    key = hashlib.sha256((provider + model + SYSTEM + prompt).encode()).hexdigest()[:20]
    os.makedirs(cache_dir, exist_ok=True); cp = os.path.join(cache_dir, key + ".json")
    if os.path.exists(cp): raw = open(cp).read()
    else:
        raw = _mock(ep, shortlist) if provider == "mock" else call_llm(provider, model, SYSTEM, prompt)
        open(cp, "w").write(raw)
    try: arr = _extract_json(raw)
    except Exception as e:
        if log: log(f"  ep{ep.num}: unparseable model output, kept heuristic scores ({e})")
        return shortlist, {"in_chars": len(SYSTEM) + len(prompt), "out_chars": len(raw)}
    by_id = {int(o.get("id", -1)): o for o in arr if isinstance(o, dict)}
    for i, c in enumerate(shortlist):
        o = by_id.get(i)
        if not o: continue
        try:
            h, cl, st = [max(0.0, min(10.0, float(o[k]))) for k in ("hook_score", "cliffhanger_score", "standalone_score")]
        except Exception:
            continue
        clip_text = _norm(" ".join(transcript(ep, s["start"], s["end"]) for s in c["segments"]))
        flags = []
        for field, src in (("hook_line", "hook"), ("cliffhanger_line", "cliffhanger")):
            q = _norm(str(o.get(field, "")))
            if q and q in clip_text: c[src] = str(o[field])
            else: flags.append(f"{field} not found verbatim in clip -> kept parser text")
        llm_final = W["hook"] * h + W["cliff"] * cl + W["standalone"] * st
        c.update(hook_score=round(h, 2), cliffhanger_score=round(cl, 2), standalone_score=round(st, 2),
                 final_score=round(0.85 * llm_final + 0.15 * c["final_score"], 3),
                 why=str(o.get("why", c["why"])), risk=str(o.get("risk", "")),
                 scorer=f"{provider}:{model}", flags=flags)
    return shortlist, {"in_chars": len(SYSTEM) + len(prompt), "out_chars": len(raw)}
