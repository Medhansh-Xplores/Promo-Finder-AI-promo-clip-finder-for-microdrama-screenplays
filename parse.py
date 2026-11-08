"""Step 1 - Parse screenplays into timestamped blocks. Pure code, no AI.

Every timestamp the tool later outputs comes from here, so it can never be invented by a model.
"""
import re, glob, os
from dataclasses import dataclass, field

TS = r"\((\d+):(\d+\.\d+)\)"
RE_RANGE = re.compile(rf"Start:\s*{TS}\s*\|\s*End:\s*{TS}")
RE_HDR = re.compile(r"^\*\*(.+?):\*\*$")
RE_SCENE = re.compile(r"^SCENE\s+(\d+)")

def to_sec(m, s): return int(m) * 60 + float(s)

def fmt(t):
    """seconds -> mm:ss.s"""
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}"

@dataclass
class Block:
    kind: str            # CAMERA | ACTION | SOUND | DIALOGUE
    speaker: str         # only for DIALOGUE
    tone: str            # emotion tag for DIALOGUE
    start: float
    end: float
    text: str
    scene: int = 0

@dataclass
class Scene:
    idx: int
    heading: str
    start: float = 0.0
    end: float = 0.0

@dataclass
class Episode:
    num: int
    logline: str
    continuity: str
    scenes: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    duration: float = 0.0
    path: str = ""

def parse_episode(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    ep = Episode(num=0, logline="", continuity="", path=path)
    m = re.search(r"episode-(\d+)", os.path.basename(path))
    ep.num = int(m.group(1)) if m else 0
    scene = None
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("EPISODE NUMBER:"):
            mm = re.search(r"(\d+)", ln)
            if mm: ep.num = int(mm.group(1))
        elif ln.startswith("EPISODE LOGLINE:"): ep.logline = ln.split(":", 1)[1].strip()
        elif ln.startswith("CONTINUITY NOTES:"): ep.continuity = ln.split(":", 1)[1].strip()
        elif RE_SCENE.match(ln):
            scene = Scene(idx=int(RE_SCENE.match(ln).group(1)), heading="")
            ep.scenes.append(scene)
        elif ln.startswith("Scene heading:") and scene: scene.heading = ln.split(":", 1)[1].strip()
        elif ln.startswith("Scene start:") and scene:
            a = re.search(r"(\d+):(\d+\.\d+)", ln); scene.start = to_sec(*a.groups())
        elif ln.startswith("Scene end:") and scene:
            a = re.search(r"(\d+):(\d+\.\d+)", ln); scene.end = to_sec(*a.groups())
        else:
            h = RE_HDR.match(ln)
            if h and scene is not None:
                label = h.group(1).strip()
                # find the Start/End line (next non-empty line)
                j = i + 1
                while j < len(lines) and not lines[j].strip(): j += 1
                r = RE_RANGE.search(lines[j]) if j < len(lines) else None
                if r:
                    st = to_sec(r.group(1), r.group(2)); en = to_sec(r.group(3), r.group(4))
                    k = j + 1; body = []
                    while k < len(lines) and lines[k].strip() and not RE_HDR.match(lines[k].strip()):
                        body.append(lines[k].strip()); k += 1
                    text = " ".join(body)
                    base = label.upper().rstrip(": ").strip()
                    tone = ""
                    mm = re.match(r"^(.*?)\s*\((.*)\)\s*$", label)
                    if mm: base, tone = mm.group(1).strip().upper(), mm.group(2).strip()
                    if base == "CAMERA": kind, spk = "CAMERA", ""
                    elif base == "ACTION": kind, spk = "ACTION", ""
                    elif base.startswith("SOUND"): kind, spk = "SOUND", ""
                    else: kind, spk = "DIALOGUE", base
                    ep.blocks.append(Block(kind, spk, tone, st, en, text.strip('"') if kind == "DIALOGUE" else text, scene.idx))
                    i = k - 1
        i += 1
    ep.blocks.sort(key=lambda b: (b.start, b.end))
    ep.duration = max([s.end for s in ep.scenes] + [b.end for b in ep.blocks] + [0])
    return ep

def load_all(folder):
    files = sorted(glob.glob(os.path.join(folder, "episode-*.txt")))
    return [parse_episode(f) for f in files]

def transcript(ep, t0, t1, with_camera=False):
    """Text of the clip window, for display and for the LLM prompt."""
    out = []
    for b in ep.blocks:
        if b.end <= t0 + 1e-6 or b.start >= t1 - 1e-6: continue
        if b.kind == "CAMERA" and not with_camera: continue
        tag = {"ACTION": "[ACTION]", "SOUND": "[SFX]", "CAMERA": "[CAM]"}.get(b.kind, f"{b.speaker} ({b.tone})" if b.tone else b.speaker)
        out.append(f"[{fmt(b.start)}] {tag}: {b.text}")
    return "\n".join(out)

if __name__ == "__main__":
    import sys
    eps = load_all(sys.argv[1] if len(sys.argv) > 1 else "data/episodes")
    print(f"episodes={len(eps)}  blocks={sum(len(e.blocks) for e in eps)}")
    for e in eps[:3] + eps[-2:]:
        d = sum(b.kind == 'DIALOGUE' for b in e.blocks)
        print(f"ep{e.num:02d} dur={fmt(e.duration)} scenes={len(e.scenes)} blocks={len(e.blocks)} dialogue={d}")
