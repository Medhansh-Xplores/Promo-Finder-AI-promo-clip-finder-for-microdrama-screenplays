"""CLI: python run.py --input data/episodes --out outputs [--provider heuristic|mock|gemini|groq|openai|anthropic] [--model NAME]"""
import argparse, csv, json, os, time
import parse, engine
from parse import fmt

def pipeline(eps, provider="heuristic", model="", shortlist=6, top=15, max_per_ep=2, stitch=True, log=print):
    t0 = time.time()
    if provider not in ("heuristic", "mock"):
        import llm_scorer; model = model or llm_scorer.DEFAULT_MODELS[provider]
    shortlisted, n_cands, in_ch, out_ch, calls = [], 0, 0, 0, 0
    for ep in eps:
        cands = engine.candidates_for_episode(ep, with_stitched=stitch); n_cands += len(cands)
        sl = engine.pick_top(cands, shortlist)
        if provider != "heuristic":
            import llm_scorer
            sl, usage = llm_scorer.rescore(ep, sl, provider, model, log=log); calls += 1
            in_ch += usage["in_chars"]; out_ch += usage["out_chars"]
        sl.sort(key=lambda c: -c["final_score"])
        for c in sl: c["logline"] = ep.logline
        shortlisted += sl
    ranked, per = [], {}
    for c in sorted(shortlisted, key=lambda c: -c["final_score"]):
        if per.get(c["episode"], 0) >= max_per_ep: continue
        if any(r["episode"] == c["episode"] and r["segments"][0]["start"] == c["segments"][0]["start"] for r in ranked): continue   # same opening = near-duplicate
        ranked.append(c); per[c["episode"]] = per.get(c["episode"], 0) + 1
        if len(ranked) >= top: break
    for i, c in enumerate(ranked, 1):
        comp = {"hook": c["hook_score"], "cliffhanger": c["cliffhanger_score"], "standalone": c["standalone_score"]}
        best = max(comp, key=comp.get)
        c["rank"] = i
        c["rank_reason"] = (f"Ranked #{i} on overall score {c['final_score']}: strongest on {best} ({comp[best]}/10); "
                            f"hook {comp['hook']}, cliffhanger {comp['cliffhanger']}, standalone {comp['standalone']}.")
    src_chars = sum(os.path.getsize(e.path) for e in eps if e.path and os.path.exists(e.path))
    summary = dict(provider=provider, model=model or "n/a", episodes=len(eps), candidate_windows_scored=n_cands, shortlisted=len(shortlisted),
                   ranked=len(ranked), llm_calls=calls, est_input_tokens=in_ch // 4, est_output_tokens=out_ch // 4,
                   source_tokens_approx=src_chars // 4, runtime_sec=round(time.time() - t0, 1))
    return ranked, shortlisted, summary

def write_outputs(out, ranked, shortlisted, summary):
    os.makedirs(out, exist_ok=True)
    json.dump(shortlisted, open(f"{out}/all_shortlisted_promos.json", "w"), indent=2, ensure_ascii=False)
    json.dump(ranked, open(f"{out}/ranked_promos.json", "w"), indent=2, ensure_ascii=False)
    json.dump(summary, open(f"{out}/run_summary.json", "w"), indent=2)
    to_csv(ranked, f"{out}/ranked_promos.csv")

def to_csv(ranked, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["rank", "episode", "format", "segments (start-end, in order)", "total_sec", "hook", "cliffhanger", "why it works / risks", "hook_score", "cliffhanger_score", "standalone_score", "final_score", "scorer"])
        for c in ranked:
            segs = " + ".join(f"{s['start_ts']}-{s['end_ts']}" for s in c["segments"])
            w.writerow([c["rank"], c["episode"], c["kind"], segs, c["total_seconds"], c["hook"], c["cliffhanger"], c["why"] + (" RISK: " + c["risk"] if c.get("risk") else ""), c["hook_score"], c["cliffhanger_score"], c["standalone_score"], c["final_score"], c["scorer"]])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/episodes"); ap.add_argument("--out", default="outputs")
    ap.add_argument("--provider", default=os.environ.get("PROMO_PROVIDER", "heuristic"), help="heuristic | mock | gemini | groq | openai | anthropic | openrouter")
    ap.add_argument("--model", default=os.environ.get("PROMO_MODEL", ""))
    ap.add_argument("--shortlist", type=int, default=6, help="clips per episode sent to the LLM")
    ap.add_argument("--top", type=int, default=15); ap.add_argument("--max-per-ep", type=int, default=2)
    ap.add_argument("--no-stitch", action="store_true")
    a = ap.parse_args()
    eps = parse.load_all(a.input); print(f"parsed {len(eps)} episodes, {sum(len(e.blocks) for e in eps)} blocks", flush=True)
    ranked, sl, summary = pipeline(eps, a.provider, a.model, a.shortlist, a.top, a.max_per_ep, not a.no_stitch)
    write_outputs(a.out, ranked, sl, summary); print(json.dumps(summary, indent=2))

if __name__ == "__main__": main()
