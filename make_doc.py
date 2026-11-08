import json
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

S = json.load(open("outputs/run_summary.json")); S["est_input_tokens"] = json.load(open("outputs/prompt_size_check.json"))["measured_input_tokens_approx"]; R = json.load(open("outputs/ranked_promos.json"))
V = json.load(open("outputs/validation_report.json"))["all_shortlisted_promos.json"]
body = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=11.5, spaceAfter=2)
h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13, leading=15, spaceAfter=1)
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10, leading=12, spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#1f3a5f"))
sm = ParagraphStyle("s", parent=body, fontSize=8, leading=9.8)
bul = ParagraphStyle("bl", parent=body, leftIndent=9, bulletIndent=0)
P = lambda t, s=body: Paragraph(t, s)
B = lambda t: Paragraph(t, bul, bulletText="-")

def cut(s, n): s = s.replace("&", "&amp;").replace("<", "&lt;"); return s if len(s) <= n else s[:n - 1].rstrip() + "..."
rows = [[P("<b>#</b>", sm), P("<b>Ep / segments</b>", sm), P("<b>Hook (first 3 s)</b>", sm), P("<b>Cliffhanger (last line)</b>", sm), P("<b>H / C / S</b>", sm)]]
for c in R[:5]:
    seg = " + ".join(f"{s['start_ts']}-{s['end_ts']}" for s in c["segments"])
    rows.append([P(str(c["rank"]), sm), P(f"Ep {c['episode']}<br/>{seg} ({c['total_seconds']}s)", sm), P(cut(c["hook"], 80), sm), P(cut(c["cliffhanger"], 80), sm),
                 P(f"{c['hook_score']} / {c['cliffhanger_score']} / {c['standalone_score']}", sm)])
t = Table(rows, colWidths=[7*mm, 36*mm, 52*mm, 52*mm, 22*mm])
t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                       ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))

st = []
st += [P("Promo Finder: finding hook-to-cliffhanger promos in microdrama screenplays", h1),
       P("Kuku AI Generalist Assignment, <b>Problem 1</b> &nbsp;|&nbsp; Pendem Medhansh &nbsp;|&nbsp; ME23BTECH11046 &nbsp;|&nbsp; Mechanical Engineering &nbsp;|&nbsp; Show: <i>I Married a Broken Soldier. He was a Duke</i> (50 episodes)", sm)]
st += [P("1. Why this problem, and scope", h2),
       P("I picked Problem 1 because the output can be <b>checked against the source</b>: every start/end must be a real timestamp, every quoted line must exist, every clip must be 20-60 s. Problem 2 risks invented law and is hard to verify; Problem 3 needs me to prove a problem exists before building. "
         "Scope: screenplay text only (no video, audio or engagement data). I find the clips and cut points; no editing, music or overlays.")]
st += [P("2. Assumptions (the brief was silent)", h2),
       B("Timestamps <font face='Courier'>mm:ss.ff</font> are minutes:seconds with a decimal. A promo = 20-60 s <b>total</b> across all its segments."),
       B("Cuts land only on a spoken/action beat boundary and <b>never inside someone's line</b> (an editor would never cut mid-sentence)."),
       B("Hook = the first 3 s of the clip. Weights: hook 0.35, cliffhanger 0.40, standalone 0.25 (my judgement: the cliffhanger is what earns the next click). Standalone below 2/10 is demoted."),
       B("Stitching (opening hook + a later cliffhanger beat, skipping the middle) is allowed <b>within one episode only</b>; cross-episode joins are not built. Global list capped at 2 promos per episode."),
       B("I assumed an episode-ending cut is usually a cliffhanger (true of this show's design). That assumption caused a bad pick (see section 5).")]
st += [P("3. How it works: what is code, what is AI, where a human sits", h2),
       B("<b>Code (no AI): parse + candidates.</b> Screenplay -> timestamped blocks -> every legal window (%s windows scored across 50 episodes in about %s s). Because only code chooses timestamps, a model <b>cannot invent one</b>." % (f"{S['candidate_windows_scored']:,}", S['runtime_sec'])),
       B("<b>Code: offline heuristic scorer</b> (keywords + structure) ranks windows and shortlists 6 clips per episode (%d clips). Free, instant, no key." % S["shortlisted"]),
       B("<b>AI (optional, built, not yet run live): one model call per episode</b> scores only the shortlist, writes the hook / cliffhanger / one-line reason and flags risks. Quoted lines must appear verbatim in the clip or are replaced. The model is a flag (<font face='Courier'>--provider gemini|groq|openai|anthropic --model X</font>); responses are cached."),
       B("<b>Human:</b> an editor reviews the ranked top 15 per show and accepts/rejects; their choices become the test set and few-shot examples.")]
st += [P("4. Result on the full pack, top 5 (full list: outputs/ranked_promos.csv)", h2), t,
       P("Why #1 first: Ep 15 opens on a physical shove and a woman crying over crushed herbs, the hero arrives, and it cuts on a villain's challenge ('You want to fight us, veteran?') so the fight is unresolved. #2 (Ep 2) starts at the episode's first second, which makes it the most standalone clip in the list (7/10): a public rejection that ends on a question. "
         "H/C/S = hook / cliffhanger / standalone, 0-10. Scores are harsh by design: the best clip scores 6.2.", sm)]
st += [P("5. How I checked quality, and where it picks badly", h2),
       B("<b>Automated (validate.py, independent of the engine):</b> every start/end is a real beat boundary, no cut through a spoken line, duration 20-60 s, hook and cliffhanger text found in the right part of the clip. <b>%d/%d shortlisted clips pass</b> (it caught two real bugs while I built it)." % (S["shortlisted"] - V["failed_items"], S["shortlisted"])),
       B("<b>Manual:</b> I read the top 5 in full, #7-#10 as head/tail excerpts, and 3 random low-ranked clips. I did <b>not</b> have editor-picked promos, so I cannot report precision; that is the first thing I would add."),
       B("<b>Fixed after reading:</b> (a) Ep 4 ranked #2 but ends with the couple walking into the sunlight under a triumphant swell (resolved, not a cliffhanger); cause: episode-end bonus plus 'swell' counted as ominous. (b) A clip started 0.4 s inside a spoken line. (c) A fragment ('They have been--') scored a perfect hook."),
       B("<b>Still wrong:</b> (1) Ep 16 (#5) ends on a soft romantic gaze; the real cliffhanger ('Gerald paid us!') is 20 s earlier, and the scorer was lured by the script's own 'cliffhanger hold' sound note. (2) The heuristic reads words, not images: Ep 42's Duke-reveal entrance scores hook 0.0 and sits in the bottom 20%; the Ep 18 fire scene is underrated (lexicon gaps). (3) 'Standalone' is a weak proxy: Ep 11 and Ep 46 lean on earlier plot. (4) #1 and #10 are two halves of one Ep 15 scene; a stitched version may beat both. (5) <b>The LLM stage has not been run against a live model</b> (no key); only its plumbing was tested with a mock. Expect it to fix (2)-(3), not guaranteed.")]
st += [P("6. Scale to every show", h2),
       B("<b>Cost per 50-episode show:</b> heuristic is free (~1 s). LLM stage measured at ~%s input tokens (one call per episode, shortlist only) plus roughly 25-30K output tokens (my estimate). At list prices I remember (verify before relying): about $0.02 on a flash-class model, about $0.6 on a mid-tier one. Weekly new shows are therefore cheap; the cost that matters is editor time, which drops from watching 50 episodes to reviewing 15 clips." % f"{S['est_input_tokens'] // 1000}K"),
       B("<b>Where it breaks at volume:</b> the keyword lists are tuned to period romance in English. Other genres/languages need different lists, so for them I would widen the shortlist (12+ per episode) or sample windows at a fixed stride, letting the LLM do more of the work. Add: video/audio cues (shot cuts, loudness), cross-episode stitching, and measuring real promo watch-through to re-tune the weights.")]
st += [P("7. AI tools used, and one place they got it wrong", h2),
       P("<b>Tools:</b> Claude (planning, code, drafting this doc), Python standard library, Streamlit for the viewer. <b>Wrong:</b> Claude's first scoring version confidently ranked the Ep 4 happy wedding exit #2 as a 'cliffhanger'. I only caught it by reading the actual clip transcript, not by trusting the score. The fix (warm/resolved cues, no mid-line cuts) is in the code, and the lesson is why the validator and a manual read exist.")]
SimpleDocTemplate("Solution_Doc_Promo_Finder.pdf", pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=11*mm, bottomMargin=10*mm, title="Promo Finder - Solution Doc").build(st)
