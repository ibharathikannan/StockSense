# StockSense

**Explainable stock research for beginner investors.** StockSense helps new investors discover US stocks and ETFs that match their interests and risk level, and explains *why* with plain-English reasons. It is a research and learning tool: it never gives buy or sell instructions.

- **Live site:** https://stocksense-g13.azurewebsites.net
- **Stack:** FastAPI (Python) · Next.js (React) · MongoDB Atlas · deployed on Azure

## Project structure

| Folder | What it is |
| --- | --- |
| [`backend/`](backend/) | FastAPI API: login and registration, users and roles, investor profile, asset search. Runs on port 8000. |
| [`frontend/`](frontend/) | Next.js web app: sign-in, profile (onboarding), account settings, admin pages. Runs on port 3000. |
| [`data/`](data/README.md) | Offline market-data pipeline: downloads prices, builds forecasting features and the asset catalogue. See [`data/README.md`](data/README.md). |

## Login accounts

| Account | Email | Password | Access |
| --- | --- | --- | --- |
| Administrator | `admin@example.com` | `ChangeMe123!` | Everything, including Users and Roles |
| Normal user | `user@example.com` | `User@12345` | Profile and account settings only |

Anyone can also create a normal account at **/register**. These are development passwords: change them (*Account settings*) before sharing the project.

## Run it locally

You need **Python 3.11+**, **Node.js 20.9+**, and a **MongoDB Atlas** cluster (the free tier is enough). Run the backend and the frontend in two terminals.

**1. Backend** (http://localhost:8000)

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # PowerShell: Copy-Item .env.example .env
```

Open `backend/.env` and set your Atlas connection string, database name and a secret:

```ini
MONGO_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net
MONGO_DB_NAME=stocksensedb
JWT_SECRET_KEY=<any random string, 32+ characters>
```

Load the stock catalogue into MongoDB once, then start the server:

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

> Atlas must allow your IP address (*Network Access*), or the backend cannot connect.

## Deployment

The app runs on Azure as a single container built from the root `Dockerfile`, using the same Atlas database. After pushing a new image to the registry, restart the web app:

```bash
az webapp restart -g mlprojectdocker -n stocksense-g13
```
