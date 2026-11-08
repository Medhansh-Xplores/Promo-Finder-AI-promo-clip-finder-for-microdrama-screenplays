"""Streamlit viewer: upload a zip (or .txt files) of episode screenplays -> ranked promos.
Screenplays are never stored in the repo; they only live in this session's temp folder."""
import io, os, tempfile, zipfile, json
import streamlit as st
import parse, run

st.set_page_config(page_title="Promo Finder", layout="wide")
st.title("Promo Finder")
st.caption("Finds 20-60s promo clips (hook -> cliffhanger -> makes sense alone) from microdrama screenplays. Every timestamp comes from the parsed script, never from a model.")

with st.sidebar:
    provider = st.selectbox("Scorer", ["heuristic", "gemini", "groq", "openai", "anthropic", "openrouter", "mock"], help="heuristic = offline, free, no key. mock = plumbing test only.")
    model = st.text_input("Model (blank = default)", "")
    key = st.text_input("API key (kept in this session only)", type="password") if provider not in ("heuristic", "mock") else ""
    shortlist = st.slider("Clips per episode sent to the LLM", 3, 10, 6)
    top = st.slider("Ranked list size", 5, 30, 15)
    stitch = st.checkbox("Allow stitched promos (hook + later cliffhanger, same episode)", True)
    if key:
        os.environ[{"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[provider]] = key

up = st.file_uploader("Episode screenplays (.zip or several .txt)", type=["zip", "txt"], accept_multiple_files=True)
if up and st.button("Find promos", type="primary"):
    tmp = tempfile.mkdtemp()
    for f in up:
        if f.name.endswith(".zip"):
            zipfile.ZipFile(io.BytesIO(f.read())).extractall(tmp)
        else:
            open(os.path.join(tmp, f.name), "wb").write(f.read())
    paths = [os.path.join(d, x) for d, _, fs in os.walk(tmp) for x in fs if x.endswith(".txt")]
    eps = sorted((parse.parse_episode(p) for p in paths), key=lambda e: e.num)
    with st.spinner(f"Scoring {len(eps)} episodes..."):
        try:
            ranked, shortlisted, summary = run.pipeline(eps, provider, model, shortlist, top, 2, stitch, log=st.warning)
        except Exception as e:
            st.error(f"Run failed: {e}"); st.stop()
    st.session_state.update(eps={e.num: e for e in eps}, ranked=ranked, summary=summary)

if "ranked" in st.session_state:
    eps, ranked, summary = st.session_state["eps"], st.session_state["ranked"], st.session_state["summary"]
    st.subheader("Run summary"); st.json(summary, expanded=False)
    tmpcsv = os.path.join(tempfile.mkdtemp(), "ranked_promos.csv"); run.to_csv(ranked, tmpcsv)
    c1, c2 = st.columns(2)
    c1.download_button("Download CSV", open(tmpcsv, "rb").read(), "ranked_promos.csv")
    c2.download_button("Download JSON", json.dumps(ranked, indent=2, ensure_ascii=False), "ranked_promos.json")
    st.subheader("Ranked promos (post #1 first)")
    for c in ranked:
        segs = " + ".join(f"{s['start_ts']}-{s['end_ts']}" for s in c["segments"])
        with st.expander(f"#{c['rank']}  Ep {c['episode']}  |  {segs}  |  {c['total_seconds']}s  |  score {c['final_score']}  |  {c['kind']}"):
            st.markdown(f"**Hook:** {c['hook']}  \n**Cliffhanger:** {c['cliffhanger']}  \n**Why:** {c['why']}" + (f"  \n**Risk:** {c['risk']}" if c.get("risk") else ""))
            st.caption(c["rank_reason"] + f"  Scorer: {c['scorer']}")
            ep = eps[c["episode"]]
            for j, sg in enumerate(c["segments"]):
                if j: st.markdown("`--- CUT (skipped footage) ---`")
                st.code(parse.transcript(ep, sg["start"], sg["end"]), language=None)
