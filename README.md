# Promo Finder (Kuku AI Generalist Assignment, Problem 1)

Reads microdrama screenplays and finds the best 20-60 s promo clips: **hook in the first 3 s -> unresolved cliffhanger -> makes sense to a new viewer.**
Output per promo: episode, start/end of every segment (in order), hook, cliffhanger, one-line why, plus a global ranking.

## Run it
```bash
# 1. put the episode .txt files in data/episodes/   (data/ is git-ignored: the scripts are confidential)
python3 run.py --provider heuristic --out outputs          # offline, free, no key, ~1 s for 50 episodes
python3 validate.py outputs                                 # re-checks every timestamp/quote against the source

# 2. with a model (swap by flag, no code change)
export GEMINI_API_KEY=...   python3 run.py --provider gemini     # free tier works
export GROQ_API_KEY=...     python3 run.py --provider groq
export ANTHROPIC_API_KEY=.. python3 run.py --provider anthropic --model <model-name>
export OPENAI_API_KEY=...   python3 run.py --provider openai
# any other model: add 5 lines to call_llm() in llm_scorer.py

# 3. UI: upload a zip of screenplays, get the ranked list
pip install streamlit && streamlit run app.py
```
`--provider mock` is a plumbing test only (fake "LLM" echoing the heuristic scores). Do not read it as model output.

## How it works
1. `parse.py` (code): screenplay -> timestamped blocks (dialogue / action / sfx / camera).
2. `engine.py` (code): generates every legal window of 20-60 s. Cuts may only land on a spoken/action beat boundary and never inside someone's line. Also builds *stitched* promos (opening hook + a later cliffhanger beat from the same episode, skipping the middle).
3. `engine.py` heuristic scorer (offline): hook / cliffhanger / standalone scores from keyword + structure rules. Used to shortlist 6 clips per episode.
4. `llm_scorer.py` (optional): ONE model call per episode scores only the shortlist and writes the one-line reason. Quoted hook/cliffhanger lines must appear verbatim in the clip or are replaced. Responses are cached on disk so re-runs are free.
5. `run.py`: rank, drop near-duplicates, cap 2 per episode in the global list.
6. `validate.py`: independent checks against the source files.

## Status (honest)
- Tested end to end on the 50-episode pack in heuristic mode. 0 validation failures on 188 shortlisted clips.
- The LLM path is written and plumbing-tested with the mock provider only. It has NOT been run against a live model (no API key was available while building).
- Stitching is within one episode only (no cross-episode joins yet).
- Known failures are listed in the solution doc.
