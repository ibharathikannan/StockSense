# Frontend

Next.js (App Router) + TypeScript + Tailwind. Setup, configuration and how to add a module are in the
[root README](../README.md).

```bash
npm install
npm run dev        # http://localhost:3000
npm run lint && npx tsc --noEmit && npm run build
```

Note for contributors and AI assistants: this is Next.js 16 — see `AGENTS.md`, and read the docs in
`node_modules/next/dist/docs/` before relying on older conventions (e.g. `middleware.ts` is now `proxy.ts`).
