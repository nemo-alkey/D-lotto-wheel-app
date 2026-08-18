# NZ Lotto Mobile Frontend

Lightweight mobile-first React frontend for the lotto-wheel FastAPI backend.

## Tech stack

- React 18 + Vite 5 (JavaScript)
- Tailwind CSS 3
- react-router-dom 6
- axios

## Prerequisites

- Node 18+ (developed against Node 22 / npm 12)
- The FastAPI backend running at `http://localhost:8000` (configured in `.env` via `VITE_API_URL`)

## Setup

```bash
npm install
```

## Development

```bash
npm run dev
```

Starts the Vite dev server on http://localhost:5173. It proxies nothing — all API
calls go directly to `VITE_API_URL` (`http://localhost:8000` by default), so the
backend must allow CORS from the dev origin.

## Production build

```bash
npm run build
```

Outputs static assets to `dist/`.

The FastAPI backend serves this build at `/mobile` — run the backend with
`uvicorn api:app --port 8000` and open http://localhost:8000/mobile.
The Vite `base` and the router `basename` are both set to `/mobile/` accordingly.

## API contract

The app talks to these backend endpoints:

- `POST /token`, `POST /register` — auth (JWT stored in `localStorage` as `lotto_token`)
- `GET /predict/ensemble` — home page predictions
- `POST /check` — check a draw against a wheel
- `GET /wheels`, `GET /wheel/{name}` — wheel listing and tickets
- `GET /backtest/bonus_impact` — bonus impact backtest
- `GET /leaderboard` — predictor leaderboard
