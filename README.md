# StockSense — FastAPI + Next.js + MongoDB Atlas

Setup guide for running the project locally.

```
.
├── backend/     FastAPI API (Python)      → http://localhost:8000
├── frontend/    Next.js web app           → http://localhost:3000
└── data/        Market-data pipeline
```

The database is **MongoDB Atlas** (cloud) — nothing to install locally.

Historical market-data collection is kept separate from the web application's
runtime dependencies. See [`data/README.md`](data/README.md) for the price
downloads and forecasting features, and [section 4](#4-recommender-data-the-assets-collection)
below for the asset catalogue the recommender reads from MongoDB.

## Login accounts

| Account | Email | Password | Role | Can do |
| --- | --- | --- | --- | --- |
| Administrator | `admin@example.com` | `ChangeMe123!` | `admin` | Everything: manage users and roles |
| Normal user | `user@example.com` | `User@12345` | `user` | Sign in, view the dashboard, change own password (no Users / Roles access) |

- The administrator is created automatically on first start from `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` in `backend/.env`. If you changed those, or already changed the password in *My profile*, use your own values.
- The normal user was added manually to the Atlas database; it isn't created automatically on a fresh database. Create more users as the admin under **Users → New user**.
- Anyone can also create their own normal-user account at **/register** (link on the login page). Turn this off with `ALLOW_REGISTRATION=false` in `backend/.env`.
- These are development credentials — change the passwords (*My profile*) or delete the accounts before sharing or deploying.

---

## Prerequisites

| Tool | Version |
| --- | --- |
| Python | 3.11+ (includes `pip` and `venv`) |
| Node.js | 20.9+ (22 LTS recommended) |
| MongoDB Atlas | a cluster (the free M0 tier is enough) |

---

## 1. MongoDB Atlas

Skip the steps you've already done.

1. **Cluster** — create one at <https://cloud.mongodb.com>.
2. **Database user** — *Security → Database Access → Add New Database User* (username + password, role *Read and write to any database*).
3. **Network access** — *Security → Network Access → Add IP Address*. Add your current IP (or `0.0.0.0/0` for development only). Without this the backend can't connect.
4. **Connection string** — *Database → Connect → Drivers*. Copy the `mongodb+srv://…` string and put your password in it.
   If the password contains special characters (`@ : / ? # %`), URL-encode them (e.g. `@` → `%40`).

You don't need to create the database or collections: the backend creates them on first start.

---

## 2. Backend

### Create the virtual environment (once)

```bash
cd backend
python -m venv .venv          # macOS/Linux may need: python3 -m venv .venv
```

### Activate it (every new terminal)

| Shell | Command |
| --- | --- |
| PowerShell (Windows) | `.\.venv\Scripts\Activate.ps1` |
| cmd.exe (Windows) | `.venv\Scripts\activate.bat` |
| Git Bash | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

The prompt now starts with `(.venv)`. Leave with `deactivate`.

> PowerShell says "running scripts is disabled"? Run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
```

Open `backend/.env` and set at least:

```ini
MONGO_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net
MONGO_DB_NAME=stocksense
JWT_SECRET_KEY=<a long random string, 32+ characters>
```

Generate a secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
All options are listed under [Configuration](#configuration).

### Run

```bash
uvicorn app.main:app --reload --port 8000
```

On first start the backend creates the collections and indexes in Atlas, two default roles (`admin`, `user`) and the first administrator.
Check it: <http://localhost:8000/api/health> should return `{"status":"ok"}`. API docs: <http://localhost:8000/docs>.

---

## 3. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000> and sign in with the default login above.

---

## 4. Recommender data: the `assets` collection

The content-based recommender reads a MongoDB **`assets`** collection: one document per
recommendable stock or ETF (90 today: 80 stocks and 10 ETFs; `^VIX` is context only and is
skipped). Each document holds the metadata from `data/asset_universe.csv` (name, type,
category, sector, themes, eligibility flags) plus risk numbers calculated from the daily
prices over the latest year: volatility, beta against SPY, worst drawdown, dividend yield,
and a 0-1 volatility rank.

It is built by two scripts, in this order:

| Script | What it does |
| --- | --- |
| `data/build_asset_profiles.py` | Computes the risk numbers and writes `data/processed/asset_profiles.json` (needs `pandas` + `pyarrow`) |
| `backend/scripts/import_assets.py` | Loads that JSON into MongoDB, matching on ticker, so it is safe to re-run |

**First-time load.** `asset_profiles.json` is included in the repository, so a fresh setup
only needs the import (backend venv active, `backend/.env` configured):

```bash
cd backend
python -m scripts.import_assets
```

**Refresh after the data changes** (from the repository root):

```bash
python3 data/download_historical_prices.py     # 1. new prices (needs yfinance: data/requirements.txt)
python3 data/build_asset_profiles.py           # 2. rebuild the JSON
cd backend && python -m scripts.import_assets  # 3. update MongoDB
```

| What changed | Run |
| --- | --- |
| New prices (`raw/historical_prices.parquet`) | steps 2 and 3 (step 1 first if you have to download them) |
| `asset_universe.csv` (ticker added or edited) | steps 1, 2 and 3 |
| MongoDB copy lost or wrong | step 3 only |

The running site reads MongoDB directly, so no redeploy is needed after a refresh.

### How `asset_profiles.json` is created

`build_asset_profiles.py` reads `data/asset_universe.csv` (metadata: `themes` such as `a|b|c`
become a list, eligibility flags become booleans, `^VIX` is skipped) and
`data/raw/historical_prices.parquet` (daily prices). The risk numbers cover each asset's latest
**252 trading days** (about one year) and use adjusted close prices, so splits and dividends do
not create false jumps:

| Field | Calculation | Meaning |
| --- | --- | --- |
| `volatility_1y` | standard deviation of daily returns x sqrt(252) | how much the price swings (0.13 = calm, 0.80 = very volatile) |
| `beta` | covariance of the asset's and SPY's daily returns / variance of SPY | sensitivity to the market (1.0 = moves with it) |
| `max_drawdown_1y` | worst fall from a running high, as a negative fraction | the biggest loss endured in the window |
| `dividend_yield` | dividends paid in the window / latest close | trailing income yield |
| `volatility_rank` | share of all assets with volatility at or below this one (0-1) | 0 = calmest asset, 1 = most volatile |
| `history_days` | number of daily returns in the window | how much data the numbers rest on |

Assets with fewer than 60 days of history get `null` risk features. `as_of` records the latest
price date used. One resulting document (NVDA):

```json
{
  "ticker": "NVDA", "name": "NVIDIA Corporation", "asset_type": "stock",
  "category": "AI chips and hardware", "sector": "Information Technology",
  "themes": ["artificial_intelligence", "semiconductors", "gpu", "data_centres"],
  "recommendation_eligible": true, "forecast_eligible": true, "history_note": null,
  "as_of": "2026-09-18",
  "risk": {
    "volatility_1y": 0.381541, "beta": 1.927985, "max_drawdown_1y": -0.202144,
    "dividend_yield": 0.002339, "history_days": 252, "volatility_rank": 0.6333
  }
}
```

**Check that it worked.** The build script prints how many profiles it wrote (90) and the
latest price date; the import prints how many documents were inserted and updated. Every
document's `as_of` should equal the latest trading day.

**Limitations**
- Removed tickers are not deleted: if you remove one from `asset_universe.csv`, its document
  stays in MongoDB until you delete it manually.
- It is a snapshot of the past year as of `as_of`, so refresh it regularly.
- One-year beta is noisy (some defensive stocks show a negative beta). Treat `volatility_1y` as
  the main risk signal and `beta` as secondary.
- `FPS` has under a year of history, so its numbers are less reliable (see its `history_days`).
- Do not load `forecast_features.parquet` or the raw price file into MongoDB. They are inputs for
  calculations and model training; only the results are stored in the database.

---

## Configuration

### `backend/.env`

| Variable | Default | Notes |
| --- | --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017` | **Set this to your Atlas connection string** |
| `MONGO_DB_NAME` | `stocksense` | Database created inside your Atlas cluster |
| `JWT_SECRET_KEY` | sample value | **Required, ≥ 32 chars.** Use your own |
| `JWT_EXPIRE_MINUTES` | `60` | Session length |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` / `FIRST_ADMIN_NAME` | `admin@example.com` / `ChangeMe123!` / `Administrator` | Only used when the `users` collection is empty |
| `ALLOW_REGISTRATION` | `true` | Public sign-up at `/register`; `false` = only admins create users |
| `COOKIE_SECURE` | `false` | `true` when served over HTTPS |
| `ENVIRONMENT` | `development` | `production` hides `/docs` and rejects the sample JWT secret |
| `CORS_ORIGINS` | `http://localhost:3000` | Only if a browser calls the API directly |

### `frontend/.env.local` (optional — defaults work for local dev)

Copy `frontend/.env.example` to `frontend/.env.local` only if you need to change something.

| Variable | Default | Notes |
| --- | --- | --- |
| `BACKEND_URL` | `http://localhost:8000` | Where the frontend proxies `/api/*`. Restart `npm run dev` after changing |
| `AUTH_COOKIE_NAME` | `access_token` | Must equal the backend's `COOKIE_NAME` |
| `NEXT_PUBLIC_APP_NAME` | `StockSense` | Shown in the sidebar and on the login page |

---

## Run the tests

```bash
# backend (venv activated)
cd backend
TEST_MONGO_URI="mongodb+srv://<user>:<password>@<cluster>.mongodb.net" pytest -q
# PowerShell:  $env:TEST_MONGO_URI="mongodb+srv://..."; pytest -q

# frontend
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

The backend tests run in a separate database named `stocksense_test` and **drop it before and after every test**.
They never touch `MONGO_DB_NAME`, but do use a dedicated Atlas cluster/user if you can, and never name your real database `stocksense_test`.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Backend exits: `jwt_secret_key … at least 32 characters` | `backend/.env` is missing or has no `JWT_SECRET_KEY` — copy it from `.env.example` |
| `ServerSelectionTimeoutError` / "No servers found" | Your IP isn't in Atlas *Network Access*, or `MONGO_URI` is wrong (still the `localhost` default?) |
| `Authentication failed` (bad auth) | Wrong database user/password in `MONGO_URI`; URL-encode special characters in the password |
| `The DNS query name does not exist` / SRV lookup fails | Use the exact `mongodb+srv://…` string from Atlas; some networks/VPNs block SRV lookups — try another network |
| Login page: "Can't reach the server" | Backend isn't running, or `BACKEND_URL` is wrong |
| Redirected to `/login` in a loop | `AUTH_COOKIE_NAME` (frontend) ≠ `COOKIE_NAME` (backend) |
| Signed in over `http://` but the session is lost | Set `COOKIE_SECURE=false` (it needs HTTPS when `true`) |
| Startup warning "nobody can sign in" | The `users` collection is empty and `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` are not set |
| Forgot the admin password | In Atlas (*Browse Collections*) delete the documents in `users`, then restart the backend — the first admin is created again |
| Port 8000 or 3000 already in use | Stop the other process, or start uvicorn with a different `--port` and set `BACKEND_URL` |

---

## Deploy to Azure (Web App for Containers)

Production runs as **one container** built from the root `Dockerfile` (Next.js on port 3000, proxying `/api/*` to FastAPI inside the same container). It uses the same MongoDB Atlas database.

| | |
| --- | --- |
| URL | <https://stocksense-g13.azurewebsites.net> |
| Web App / resource group | `stocksense-g13` / `mlprojectdocker` (shared Linux B1 plan, Japan East) |
| Image | `mlprojectdocker.azurecr.io/stocksense:latest` |
| Web App settings | `MONGO_URI`, `MONGO_DB_NAME`, `JWT_SECRET_KEY` (separate from local), `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `WEBSITES_PORT=3000` |

**Deploy a new version**

```bash
az acr login -n mlprojectdocker
docker build -t mlprojectdocker.azurecr.io/stocksense:latest .
docker push mlprojectdocker.azurecr.io/stocksense:latest
```

GitHub Actions (`.github/workflows/cicd.yaml`) builds and pushes the same image on every push to `main`, once the repository secrets `ACR_USERNAME` and `ACR_PASSWORD` are set (ACR → *Access keys*).

**After a push, restart the Web App** so it pulls the new image: `az webapp restart -g mlprojectdocker -n stocksense-g13`. An ACR webhook named `stocksense` exists to do this automatically, but it currently fails with 401 because basic-auth publishing is disabled on the Web App. Enabling it (`basicPublishingCredentialsPolicies/scm`) would make the webhook work.

Useful commands:

```bash
az webapp log tail -g mlprojectdocker -n stocksense-g13     # live logs
az webapp restart  -g mlprojectdocker -n stocksense-g13
az webapp config appsettings list -g mlprojectdocker -n stocksense-g13 --query "[].name"
```

Atlas must allow the Web App's outbound IPs (*Network Access*); `0.0.0.0/0` works for development.

---

## Project status and team notes (2026-09-20)

**Done**
- Web app base: FastAPI + Next.js + MongoDB Atlas with login, self-registration (`/register`), users, roles and permissions. Access is enforced by the API on every request, and the frontend only hides what a user cannot use.
- Deployed to Azure as a single container (see above).
- Recommender asset catalogue (`assets` collection, section 4) built from the data pipeline.

**Please**
- Do not change `data/asset_universe.csv` without telling the group: it feeds both the forecasting models and the recommender.
- Keep the large data files out of MongoDB (see section 4).
- Change or remove the demo passwords under *Login accounts* before this repository is shared beyond the team.

**Decisions needed**
- **Onboarding mockup vs. the data.** The mockup has "Real Estate" and "Clean Energy" interest chips, but there are no real-estate assets and only a few clean-energy ones (FSLR, NEE, GRID). Drop or rename the chips, or add tickers?
- **Category data.** XOM and CVX sit under "AI power energy and grid", and AAPL under "AI chips and hardware". Correct them?
- **Macro data.** `raw/macro_indicators` has not been downloaded (it needs a FRED API key). Who owns it?

**Next**
1. Onboarding profile: a `profiles` collection, an API, and the four-step onboarding page from the mockups.
2. Content-based recommender: related and diversifying assets, each with reasons.
3. Discover page.
