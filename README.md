# GasAgent.ai

A cross-platform mobile app (React Native, iOS + Android) with a Python
backend that helps drivers find fuel and charging options, track prices,
and get quick answers from a built-in AI assistant.

This is a **personal portfolio / learning project**, built to practice
full-stack mobile development — a React Native client, a Python API
backend, third-party data integration, and an AI agent with tool-calling.
**It is not intended for production deployment or real-world use.** It
runs on free-tier hosting and free/public data sources, so uptime,
accuracy, and availability aren't guaranteed, and some features may be
rate-limited or occasionally unavailable.

## What it does

- **Gas station search** — find the nearest gas stations by city, postal
  code, or current location, with brand, per-grade pricing (regular,
  midgrade, premium, diesel), distance, and star ratings.
- **EV charging station search** — find nearby EV charging stations, with
  network, connector types, charging speed, and distance.
- **AI chat assistant** — a conversational agent for fuel- and EV-related
  questions, able to pull in live station search results and price
  forecasts as part of its answers rather than just plain text.
- **Price forecasting** — a short-term local gas price outlook, combining
  the current local average with a broader regional pricing trend.
- **Favorites** — save stations from search results, reorder them, and
  refresh their prices later.
- **Shared location** — sharing your location once carries across the
  app's other tabs instead of asking again in each one.

## Tech stack

- **Mobile:** React Native (TypeScript), targeting iOS and Android
- **Backend:** FastAPI (Python), a REST API consumed by the mobile app
- **AI agent:** a large-language-model API with tool-calling, letting the
  assistant invoke the same search/forecast functionality as the rest of
  the app
- **Testing:** pytest (backend), Jest (mobile)

Station, charging, and pricing data come from a mix of free public and
third-party data sources — deliberately not named here, since this
project is just a technical demonstration and isn't affiliated with, or
endorsed by, any of them.

## Project structure

```
gasagent-ai/
  mobile/    React Native (TypeScript) app — iOS and Android
  backend/   FastAPI service — the API layer the mobile app talks to
```

## Getting started

**Prerequisites:** Node.js, Python 3.11+, and either Xcode (iOS) or
Android Studio (Android) set up for React Native development.

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your own free API keys for full functionality
uvicorn app.main:app --reload

# Mobile (in a separate terminal, with the backend running)
cd mobile
npm install
npm run ios       # or: npm run android
```

Some features (EV search, gas price forecasting, the AI assistant) need
their own free API key set in `backend/.env` — see the comments in
`.env.example` for details. The app degrades gracefully without them;
those specific features just won't return results.

Run the test suites with `pytest` (backend) and `npm test` (mobile).
