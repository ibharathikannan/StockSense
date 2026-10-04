# StockSense

**Explainable stock research for beginner investors.** StockSense helps new investors discover US stocks and ETFs that match their interests and risk level, and explains *why* with plain-English reasons. It is a research and learning tool: it never gives buy or sell instructions.

- **Live site:** https://stocksense-g13.azurewebsites.net
- **Stack:** FastAPI (Python) · Next.js (React) · PostgreSQL (Azure Database for PostgreSQL) · deployed on Azure

## Project structure

| Folder | What it is |
| --- | --- |
| [`backend/`](backend/) | FastAPI API: login and registration, users and roles, investor profile, asset search. Runs on port 8000. |
| [`frontend/`](frontend/) | Next.js web app: sign-in, profile (onboarding), account settings, admin pages. Runs on port 3000. |
| [`data/`](data/README.md) | Offline prices/macro features, asset catalogue, SEC/news collection, and local text preparation. See [`data/README.md`](data/README.md). |

## Login accounts

| Account | Email | Password | Access |
| --- | --- | --- | --- |
| Administrator | `admin@example.com` | `ChangeMe123!` | Everything, including Users and Roles |
| Normal user | `user@example.com` | `User@12345` | Profile and account settings only |

Anyone can also create a normal account at **/register**. These are development passwords: change them (*Account settings*) before sharing the project.

## Run it locally

You need **Python 3.11+**, **Node.js 20.9+**, and a **PostgreSQL** database (the team's Azure server, or a local one). Run the backend and the frontend in two terminals.

**1. Backend** (http://localhost:8000)

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # PowerShell: Copy-Item .env.example .env
```

Open `backend/.env` and set the database connection and a secret:

```ini
POSTGRES_HOST=stocksensedb.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<the server's password>
POSTGRES_SSLMODE=require
JWT_SECRET_KEY=<any random string, 32+ characters>
```

The tables are created automatically when the API starts. Load the stock catalogue once, then start the server:

```bash
python -m scripts.import_assets
uvicorn app.main:app --reload --port 8000
```

**2. Frontend** (http://localhost:3000)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and sign in with one of the accounts above. The first sign-in for a new user goes to the **Profile** page to choose a risk level, interests and tickers to follow.

> The Azure PostgreSQL server's firewall must allow your IP address (*Networking* in the portal), or the backend cannot connect.

To run the backend tests you need a PostgreSQL server you can throw data away on — they drop and recreate a database named `stocksense_test`. A local Docker container is easiest:

```bash
docker run -d --name stocksense-pg -e POSTGRES_PASSWORD=localdev -p 5432:5432 postgres:16
TEST_POSTGRES_PASSWORD=localdev pytest -q        # from backend/; also TEST_POSTGRES_HOST / _PORT / _USER / _SSLMODE
```

**Moving data from the old MongoDB database:** `python -m scripts.migrate_from_mongo` copies roles, users and profiles (see the script's docstring; assets come from `scripts.import_assets`).

## Shared market and document data

Local Parquet datasets and prepared SEC/news text can be imported into Azure
PostgreSQL as queryable tables, with an optional archive of original files.
See [the shared-data guide](data/SHARED_DATA.md) for setup, import and verification.
MongoDB continues to serve the web application. Keep local originals and
committed baselines until the PostgreSQL migration is verified. Embedding
creation and RAG retrieval remain separate future work.

## Deployment

The app runs on Azure as a single container built from the root `Dockerfile`, using the same PostgreSQL database. The web app needs the `POSTGRES_*` settings above as App Service application settings, and the PostgreSQL firewall must allow Azure services. After pushing a new image to the registry, restart the web app:

```bash
az webapp restart -g mlprojectdocker -n stocksense-g13
```
