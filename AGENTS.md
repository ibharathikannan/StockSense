# StockSense Agent Guide

## Purpose and current scope

StockSense is a stock-intelligence project with two deliberately separate areas:

- A full-stack web application built with FastAPI, Next.js, and MongoDB Atlas. The current runtime provides authentication, registration, user administration, roles, and permission-based access control.
- An offline market-data pipeline that downloads price and macroeconomic data and builds time-series features for future forecasting work.

Model training, model serving, forecasts in the web application, portfolio management, brokerage integration, and trade execution are not implemented yet. Do not invent or add these capabilities unless the task explicitly expands the scope. This project must not present output as personalized financial advice.

Read the root `README.md` before broad changes. Read `frontend/README.md` or `data/README.md` before working in those areas.

## Architecture

### Backend (`backend/`)

- `app/main.py` creates the FastAPI application, owns its lifespan, and registers routers.
- `app/api/routers/` is the HTTP layer. Keep request handling and response mapping thin.
- `app/schemas/` defines request and response validation.
- `app/services/` owns reusable business rules and domain errors.
- `app/repositories/` owns MongoDB queries and persistence details.
- `app/core/` owns configuration, permissions, and security primitives.
- `app/db/` owns MongoDB client and database setup.

Preserve the routing-to-business-logic-to-persistence direction. Do not put MongoDB queries in routers or duplicate business rules across endpoints. Introduce a new abstraction only when it creates a real seam or removes repeated complexity; prefer small interfaces with substantial behavior behind them.

FastAPI is the security boundary. Authorization must be enforced by backend dependencies and business rules. Frontend visibility checks are user-experience controls only.

### Frontend (`frontend/`)

- This is a Next.js 16 App Router application using TypeScript and Tailwind.
- Pages and layouts live in `src/app/`; reusable UI lives in `src/components/`.
- Backend calls are grouped by domain in `src/services/` and go through `src/lib/api.ts`.
- Authentication state is centralized in `src/lib/auth.tsx`.
- `src/proxy.ts` only checks whether the session cookie exists. It does not validate the token.
- The browser uses same-origin `/api/*`; `next.config.ts` proxies those requests to FastAPI.

Keep backend calls out of presentational components when a domain service is the natural seam. Reuse shared UI and types before adding variants. Preserve accessibility, responsive behavior, loading states, and actionable error messages. Do not expose authentication tokens to client-side JavaScript.

### Data pipeline (`data/`)

- The data pipeline is offline and is not a runtime dependency of the web application.
- Collection, macro-data download, feature construction, and format conversion remain separate steps.
- Parquet files are the shared datasets; CSV files are local convenience copies unless documentation says otherwise.
- Time-series evaluation must avoid future leakage. Fit learned preprocessing on training folds only and do not replace walk-forward validation with random train/test splits.

Do not download external data, overwrite committed datasets, or regenerate large artifacts unless the task explicitly requires it. Preserve dataset schemas unless a coordinated schema change is part of the request.

### Deployment

- Local development runs FastAPI on port 8000 and Next.js on port 3000.
- Production uses the root `Dockerfile`: Next.js is public on port 3000 and proxies to FastAPI on loopback port 8000.
- A push to `main` runs `.github/workflows/cicd.yaml`, pushes the `latest` image to Azure Container Registry, and causes the Azure Web App to restart through its webhook.

Never commit, push, publish an image, deploy, restart Azure resources, or change repository/cloud settings unless the user explicitly requests that action.

## Scope and change discipline

- Implement only the requested outcome and the minimum supporting changes needed for a complete solution.
- Preserve existing behavior unless the request explicitly changes it.
- Do not mix unrelated cleanup, broad refactors, renames, formatting sweeps, or dependency upgrades into a focused change.
- Preserve user-authored and untracked changes. Do not discard or overwrite work you did not create.
- Before changing an interface, trace its callers and preserve the contract or update all affected callers and tests together.
- Ask before making a material scope expansion, adding a production dependency, changing a database or dataset schema, breaking an API contract, or altering authentication, authorization, CI, or deployment behavior beyond the request.
- Do not commit generated files, local virtual environments, build output, caches, secrets, or `.env` files.

## Engineering practices

- Prefer clear, typed, cohesive modules and descriptive names over cleverness.
- Keep interfaces small, hide implementation details, and place behavior at the seam where callers and tests naturally exercise it.
- Reuse existing patterns before introducing frameworks, layers, or utilities.
- Keep functions focused, but do not split code into shallow pass-through wrappers.
- Validate input at system edges and handle errors at the layer that can add useful context.
- Make authorization fail closed. Preserve password hashing, HTTP-only cookie handling, role checks, and production secret validation.
- Never log credentials, tokens, connection strings, personal data, or secret values.
- Use configuration and environment variables rather than hard-coded deployment values.
- Add comments for non-obvious reasons and invariants, not for code that already explains itself.
- Add or update tests at the public interface affected by the change. Regression tests should reproduce the real failure mode.
- Keep documentation synchronized when setup, commands, architecture, configuration, or user-visible behavior changes.

## Validation

Run the narrowest relevant checks first, then the broader checks justified by the change.

### Backend

From `backend/` with its virtual environment active:

```bash
pytest -q
```

The integration suite drops the database named `stocksense_test` before and after tests. Never point `TEST_MONGO_URI` at a cluster where that database contains valuable data. Do not run the suite until the target is known to be a safe test instance.

### Frontend

From `frontend/`:

```bash
npm run lint
npx tsc --noEmit
npm run build
```

This repository uses Next.js 16. Consult the installed documentation under `frontend/node_modules/next/dist/docs/` before relying on conventions from older versions.

### Data and deployment

- For data changes, validate the smallest affected pipeline stage and inspect its schema and representative output. Do not run network-backed downloads merely as a generic check.
- For container or startup changes, build the Docker image when the environment permits it.
- Do not use deployment as validation.

If a relevant check cannot be run, state exactly what was not run and why.

## Completion standard

Before handing work back:

- Review the diff for unintended scope changes, secrets, generated files, and debugging artifacts.
- Confirm the requested behavior and relevant failure paths.
- Report changed files and validation results concisely.
- Identify remaining risks, assumptions, or unverified behavior without claiming completion beyond the evidence.

Keep this file focused on stable repository-wide guidance. Update it when architecture, commands, or recurring review expectations materially change.
