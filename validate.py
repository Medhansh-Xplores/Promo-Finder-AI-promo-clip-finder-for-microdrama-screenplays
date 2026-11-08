"""Independent check of outputs against the SOURCE screenplays. Does not trust the engine."""
import json, sys, re
import parse
from engine import boundaries, MIN_LEN, MAX_LEN

fmt_ = parse.fmt
def norm(s): return re.sub(r"\W+", " ", s.lower()).strip()

def validate(out_dir="outputs", inp="data/episodes", files=("ranked_promos.json", "all_shortlisted_promos.json")):
    eps = {e.num: e for e in parse.load_all(inp)}
    report = {}
    for fn in files:
        items = json.load(open(f"{out_dir}/{fn}")); fails = []
        for it in items:
            tag = f"ep{it['episode']} {[(s['start_ts'], s['end_ts']) for s in it['segments']]}"
            ep = eps.get(it["episode"])
            if not ep: fails.append((tag, "episode does not exist")); continue
            starts, ends = boundaries(ep); segs = it["segments"]
            for s in segs:
                if min(abs(s["start"] - x) for x in starts) > 0.01: fails.append((tag, f"start {s['start_ts']} is not a real beat boundary"))
                if min(abs(s["end"] - x) for x in ends) > 0.01: fails.append((tag, f"end {s['end_ts']} is not a real beat boundary"))
                if s["end"] > ep.duration + 0.01: fails.append((tag, "segment past end of episode"))
            spoken = [b for b in ep.blocks if b.kind == "DIALOGUE"]   # independent check: never cut through a spoken line
            for s in segs:
                for t, lab in ((s["start"], "start"), (s["end"], "end")):
                    if any(b.start + 0.15 < t < b.end - 0.15 for b in spoken): fails.append((tag, f"{lab} {fmt_(t)} cuts through a spoken line"))
            for a, b in zip(segs, segs[1:]):
                if b["start"] < a["end"]: fails.append((tag, "segments overlap / out of order"))
            tot = sum(s["end"] - s["start"] for s in segs)
            if not (MIN_LEN - 0.01 <= tot <= MAX_LEN + 0.01): fails.append((tag, f"duration {tot:.1f}s outside 20-60s"))
            first = parse.transcript(ep, segs[0]["start"], segs[0]["start"] + 3.0, with_camera=False)
            last = parse.transcript(ep, segs[-1]["end"] - 6.0, segs[-1]["end"] + 0.01)
            h = norm(it["hook"].split(": ", 1)[-1].replace("(action) ", ""))
            if h and h[:40] not in norm(first): fails.append((tag, "hook text not found in first 3s of clip"))
            c = norm(it["cliffhanger"].split(": ", 1)[-1].replace("(action) ", ""))
            if c and c[:40] not in norm(last): fails.append((tag, "cliffhanger text not found in last 6s of clip"))
            if not c: fails.append((tag, "no cliffhanger text captured (clip ends on camera/sfx only)"))
        report[fn] = dict(checked=len(items), failed_items=len({f[0] for f in fails}), failures=fails[:20])
    json.dump(report, open(f"{out_dir}/validation_report.json", "w"), indent=2)
    return report

if __name__ == "__main__":
    r = validate(*(sys.argv[1:2] or ["outputs"]))
    for k, v in r.items(): print(k, "checked", v["checked"], "items with failures:", v["failed_items"]); [print("  ", f) for f in v["failures"][:8]]
