"""Steps 2-3: candidate generation + offline heuristic scoring.

Design rule: code decides WHERE clips can start/end (real block boundaries only);
scoring (heuristic here, LLM in llm_scorer.py) only decides WHICH ones are good.
"""
import re
from parse import fmt, transcript

MIN_LEN, MAX_LEN = 20.0, 60.0

# ---- lexicons (tuned for this genre: period / noble romance drama) ----
HOOK_WORDS = r"slap|slaps|slapped|strike|struck|shove|shoves|grabs|drags|throws|hurls|collapses|gasps|scream|screams|shatter|blood|bleeding|dead|dies|kill|murder|poison|dagger|sword|knife|arrest|banish|annul|annulment|divorce|pregnan|heir|bastard|traitor|betray|betrayal|lie|lies|liar|truth|secret|reveal|impostor|fraud|duke|prince|king|queen|crown|命|how dare|get out|leave|never|forever|mine|abandon|humiliat|disgrace|shame|beg|kneel|kneels|tears|weeps|proof|confess|swear|oath|curse|ruin|destroy|revenge|vengeance"
RES_WORDS = r"thank you|thanks|goodbye|farewell|forgive me|very well|of course|at last|finally|i promise|rest now|good night|sleep well"
REVEAL_PAT = r"\b(the truth|it was you|i know|you are|you're the|he is|she is|i am the|real |actually|all along|from the start|that child|my son|my daughter|the duke|the king)\b"
HIGH_TONES = r"shock|furious|rage|menac|cold|desperate|trembl|sneer|threat|stunned|horror|fierce|seeth|cruel|broken|sobbing|pleading|defian|gasp|anguish|vicious|icy|stern|command"
ACTION_HITS = r"slap|strike|slam|shove|drag|grab|throw|hurl|collapse|gasp|draws|plunge|burst|kiss|shatter|blood|rips|tears|clutch|stagger|recoil|freez|kneel|faint|snatch|lunge|point|glare|steps forward|rises"
CUE_WORDS = r"cliffhanger|ominous|sting|drone|stinger|lingers|dramatic|crescendo|cut to black|tense|foreboding|suspense"
POS_CUES = r"triumphant|uplifting|hopeful|warm|gentle|romantic|peaceful|tender|joyful|victorious|sunlight|hand-in-hand|embrace|smiles|together"

def _n(x, lo=0.0, hi=10.0): return max(lo, min(hi, x))
def _hits(pat, s, cap=None):
    n = len(re.findall(pat, s.lower()))
    return min(n, cap) if cap else n

def content(ep):
    return [b for b in ep.blocks if b.kind in ("DIALOGUE", "ACTION", "SOUND")]

# ------------------------------------------------------------------ candidates
def boundaries(ep):
    """Legal cut points. Starts = start of a spoken/action beat. Ends = end of a spoken/action beat."""
    beats = [b for b in ep.blocks if b.kind in ("DIALOGUE", "ACTION")]
    spoken = [b for b in ep.blocks if b.kind == "DIALOGUE"]
    straddles = lambda t: any(b.start + 0.15 < t < b.end - 0.15 for b in spoken)   # t falls inside someone's line
    starts = sorted({round(b.start, 2) for b in beats if not straddles(b.start)})
    ends = sorted({round(b.end, 2) for b in beats if not straddles(b.end)})   # cut on a beat, never mid-line or on trailing silence
    return starts, ends

def contiguous_candidates(ep):
    starts, ends = boundaries(ep)
    out = []
    for s in starts:
        for e in ends:
            d = e - s
            if MIN_LEN <= d <= MAX_LEN:
                out.append([(s, e)])
    return out

def stitched_candidates(ep, hook_scores, cliff_scores, top=4):
    """Join ONE opening beat (hook) with a later cliffhanger beat, skipping the middle. Same episode only."""
    starts, ends = boundaries(ep)
    hs = sorted(starts, key=lambda s: -hook_scores.get(s, 0))[:top]
    ce = sorted(ends, key=lambda e: -cliff_scores.get(e, 0))[:top]
    out = []
    for s in hs:
        for a_len in (8, 12, 16):
            ok = [e for e in ends if s + 4 <= e <= s + a_len + 3]
            if not ok: continue
            a_end = max(ok)
            for e in ce:
                for b_len in (14, 20, 28):
                    ok2 = [x for x in starts if e - b_len - 3 <= x <= e - 8 and x >= a_end + 4]
                    if not ok2: continue
                    b_start = min(ok2)
                    tot = (a_end - s) + (e - b_start)
                    if MIN_LEN <= tot <= MAX_LEN:
                        out.append([(s, a_end), (b_start, e)])
    seen, uniq = set(), []
    for c in out:
        k = tuple(c)
        if k not in seen: seen.add(k); uniq.append(c)
    return uniq

# ------------------------------------------------------------------ scoring pieces
def _window_blocks(ep, t0, t1, kinds=("DIALOGUE", "ACTION")):
    return [b for b in ep.blocks if b.kind in kinds and b.end > t0 + 1e-6 and b.start < t1 - 1e-6]

def hook_score(ep, t0):
    bl = _window_blocks(ep, t0, t0 + 3.0)
    if not bl: return 0.5, "silent/camera-only opening", ""
    sc, notes = 0.0, []
    for b in bl:
        if b.kind == "DIALOGUE":
            if "!" in b.text: sc += 1.0; notes.append("exclamation")
            if "?" in b.text: sc += 0.8; notes.append("question")
            h = _hits(HOOK_WORDS, b.text, 3); sc += 0.7 * h
            if h: notes.append(f"{h} charged word(s)")
            if _hits(HIGH_TONES, b.tone): sc += 1.0; notes.append(f"tone '{b.tone}'")
        else:
            h = _hits(ACTION_HITS, b.text, 3); sc += 1.3 * h
            if h: notes.append("physical action")
    first = bl[0]
    if first.kind == "DIALOGUE":
        if first.start - t0 <= 1.5: sc += 0.5
        if len(first.text.split()) < 3: sc -= 1.5; notes.append("opens on a fragment (context-dependent)")
        if re.match(r"^(\.\.\.|…|he|she|they|it|and|but|so|then)\b", first.text.strip().lower()) or first.text.strip().endswith("—"):
            sc -= 2.0; notes.append("opens mid-thought")
    hook_txt = first.text if first.kind == "DIALOGUE" else first.text
    who = f"{first.speaker.title()}: " if first.kind == "DIALOGUE" else "(action) "
    return _n(sc * 1.5), "; ".join(dict.fromkeys(notes)) or "flat opening", who + hook_txt

def cliff_score(ep, t1):
    sc, notes = 0.0, []
    last_beat = max((b.end for b in ep.blocks if b.kind in ("DIALOGUE", "ACTION")), default=ep.duration)
    if last_beat - t1 <= 0.3: sc += 3.0; notes.append("episode-ending cut")
    tail = [b for b in ep.blocks if b.kind == "SOUND" and t1 - 5 <= b.start <= t1 + 0.5]
    if any(_hits(CUE_WORDS, b.text) for b in tail): sc += 1.2; notes.append("ominous sound cue")
    elif any(_hits(POS_CUES, b.text) for b in tail): sc -= 2.0; notes.append("warm/triumphant sound cue (resolved)")
    last = [b for b in _window_blocks(ep, t1 - 6.0, t1 + 0.01) if b.end <= t1 + 0.3]
    last_txt = ""
    if last:
        b = last[-1]; last_txt = (f"{b.speaker.title()}: " if b.kind == "DIALOGUE" else "(action) ") + b.text
        if b.kind == "DIALOGUE":
            if b.text.rstrip().endswith("?"): sc += 2.0; notes.append("ends on a question")
            if "..." in b.text or "…" in b.text or b.text.rstrip().endswith("—"): sc += 1.0; notes.append("trails off")
            if "!" in b.text: sc += 0.8
            if _hits(REVEAL_PAT, b.text): sc += 1.2; notes.append("reveal/accusation phrasing")
            if _hits(HIGH_TONES, b.tone): sc += 0.7
        else:
            h = _hits(ACTION_HITS, b.text, 2); sc += 0.9 * h
            if h: notes.append("ends on physical beat")
            if _hits(POS_CUES, b.text): sc -= 2.0; notes.append("ends on a warm/resolved image")
        h = _hits(HOOK_WORDS, b.text, 2); sc += 0.6 * h
        if _hits(RES_WORDS, b.text): sc -= 2.0; notes.append("sounds resolved")
    return _n(sc * 1.25), "; ".join(dict.fromkeys(notes)) or "neutral ending", last_txt

def standalone_score(ep, t0, t1):
    sc, notes = 3.0, []
    sc_start = [s for s in ep.scenes if abs(s.start - t0) <= 1.0]
    if sc_start or t0 <= 1.0: sc += 2.5; notes.append("opens at scene start (setting established)")
    d = [b for b in _window_blocks(ep, t0, t1) if b.kind == "DIALOGUE"]
    if d:
        if re.match(r"^(he|she|they|it|that|this|and|but|so|then|yes|no)\b", d[0].text.strip().lower()):
            sc -= 1.5; notes.append("first line leans on earlier context")
        if len(d[0].text.split()) >= 5: sc += 0.8
        names = {b.speaker for b in d}
        if len(names) >= 2: sc += 0.7
        if len(names) > 4: sc -= 1.0; notes.append("crowded cast")
    sc -= min(2.0, (ep.num - 1) * 0.08); 
    if ep.num > 6: notes.append("later episode: more backstory assumed")
    return _n(sc), "; ".join(dict.fromkeys(notes)) or "ok"

def length_bonus(total):  # prefer 25-45s; mild
    return 0.5 if 25 <= total <= 45 else 0.0

W = dict(hook=0.35, cliff=0.40, standalone=0.25)

def score_candidate(ep, segs):
    total = sum(e - s for s, e in segs)
    h, hn, hook_txt = hook_score(ep, segs[0][0])
    c, cn, cliff_txt = cliff_score(ep, segs[-1][1])
    s, sn = standalone_score(ep, segs[0][0], segs[0][1])
    if len(segs) > 1: s = _n(s - 0.8); sn += "; stitched cut may confuse"
    final = W["hook"] * h + W["cliff"] * c + W["standalone"] * s + length_bonus(total)
    if len(segs) > 1: final -= 0.8          # stitching is a bonus format; contiguous wins ties
    if s < 2.0: final -= 1.0; sn += "; GATE: weak standalone, demoted"   # brief: must make sense to a new viewer
    return dict(
        episode=ep.num, segments=[dict(start=round(a, 2), end=round(b, 2), start_ts=fmt(a), end_ts=fmt(b)) for a, b in segs],
        total_seconds=round(total, 1), hook_score=round(h, 2), cliffhanger_score=round(c, 2), standalone_score=round(s, 2),
        final_score=round(final, 3), hook=hook_txt, cliffhanger=cliff_txt,
        why=f"Hook: {hn}. Cliffhanger: {cn}. Standalone: {sn}.", scorer="heuristic", kind="stitched" if len(segs) > 1 else "contiguous")

# ------------------------------------------------------------------ selection
def _overlap(a, b):
    tot = 0.0
    for s1, e1 in a:
        for s2, e2 in b:
            tot += max(0.0, min(e1, e2) - max(s1, s2))
    return tot / max(1e-6, min(sum(e - s for s, e in a), sum(e - s for s, e in b)))

def candidates_for_episode(ep, with_stitched=True):
    starts, ends = boundaries(ep)
    cands = [score_candidate(ep, segs) for segs in contiguous_candidates(ep)]
    if with_stitched:
        hs = {s: hook_score(ep, s)[0] for s in starts}
        cs = {e: cliff_score(ep, e)[0] for e in ends}
        cands += [score_candidate(ep, segs) for segs in stitched_candidates(ep, hs, cs)]
    return cands

def pick_top(cands, k=3, max_overlap=0.3):
    """Greedy best-first, dropping near-duplicates (>30% shared footage)."""
    chosen = []
    for c in sorted(cands, key=lambda x: -x["final_score"]):
        segs = [(s["start"], s["end"]) for s in c["segments"]]
        if all(_overlap(segs, [(s["start"], s["end"]) for s in o["segments"]]) <= max_overlap for o in chosen):
            chosen.append(c)
        if len(chosen) >= k: break
    return chosen
