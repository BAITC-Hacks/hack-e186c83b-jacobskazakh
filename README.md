# hack-e186c83b-jacobskazakh
Hackathon team repository for JacobsKazakh

## Run locally

1. Install dependencies: `python -m pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and optionally set `OPENAI_API_KEY` for AI-generated questions. Without a key, the app uses built-in questions.
3. Start: `python -m streamlit run app.py`

The app stores its SQLite database in `challenge_hub.db` by default.
