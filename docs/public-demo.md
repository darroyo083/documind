# Public Demo Release

DocuMind has a separate production Compose file for the portfolio demo:

```bash
PUBLIC_DEMO_MODE=true SECRET_KEY="replace-with-a-long-random-value" \
  docker compose -f docker-compose.demo.yml \
    -f docker-compose.demo.local.yml up --build -d
```

The local override serves the frontend at `http://localhost:8080`. The base
production stack publishes no host port. Nginx serves the built React
application, proxies `/api/` to the internal backend, and provides SPA
fallback routing.

## Architecture

`PUBLIC_DEMO_MODE` is the canonical operator flag. The demo Compose file maps
it to both the backend environment and the frontend build-time
`VITE_PUBLIC_DEMO_MODE` argument. Normal development keeps the flag false and
continues to use `docker-compose.yml`, PostgreSQL, authentication, uploads,
and the real application APIs.

When the flag is true, the backend serves deterministic synthetic fixtures from
`backend/app/demo_fixtures.py`. The public demo does not require PostgreSQL,
uploads, embeddings, an AI provider, or provider credentials at runtime. The
backend image remains stateless for this mode; its default database URL is not
opened because no database-backed route is used.

The frontend reuses the existing `SpaceDetail`, Overview, Actions, Compare,
Intelligence, Ask, evidence, and Search components. `frontend/src/api.ts`
adapts those reads to the public-demo endpoints. No separate fake workspace is
maintained.

## Shared reverse proxy

The production cutover uses the existing external Docker network named
`nginx-proxy` through `docker-compose.demo.proxy.yml`. Only the static frontend
joins that network and advertises `PUBLIC_DEMO_DOMAIN` plus
`PUBLIC_DEMO_WWW_DOMAIN` to `jwilder/nginx-proxy` and its Let's Encrypt
companion. The backend remains reachable only on the private Compose network.

The proxy vhost snippet at
`deploy/nginx-proxy/vhost.d/www.withdocumind.com` permanently redirects the
secondary hostname to `https://withdocumind.com$request_uri`, while leaving
the ACME challenge path available for certificate issuance.

## Cost and mutation protection

The backend middleware rejects every non-demo mutation before authentication,
storage, or provider dependencies are resolved. This covers login,
registration, uploads, retries, deletes, action updates, and every private
generation route. The only allowed POST in demo mode is the deterministic
`/public-demo/space/ask` endpoint; it never calls a provider.

OpenAPI and ReDoc are disabled in demo mode. The public fixture endpoints are
read-only except for the deterministic Ask request. The demo UI removes
authentication actions, uploads, delete/retry controls, refresh/regenerate
controls, and editable checklist controls.

## Fixtures

The synthetic Northwind Workspace contains:

- `Northwind_Membership_Agreement.pdf` — CHF 420 monthly fee, CHF 50 card
  deposit, 06:00–22:00 access, and a 30-day cancellation term.
- `Northwind_Renewal_Notice.pdf` — CHF 460 renewal fee, 07:00–21:00 access,
  decision deadline, and the conflicting 60-day cancellation line.
- `Northwind_Scanned_Appendix.pdf` — deterministic failed state showing that
  scanned PDFs have no extractable text.

Overview, Actions, Compare, Intelligence, Ask, Search, and source disclosures
are all pre-generated from this synthetic corpus. Ask supports four suggested
questions, including `¿De qué va esto?`; unsupported questions return a clear
demo-only response without contacting an AI provider. Search includes the
release-gate queries `CHF 460`, `access-card deposit`, and `when can building
access be suspended`.

## Future portfolio video

`frontend/src/components/DemoVideo.tsx` is the insertion point. It renders
nothing until `VITE_DEMO_VIDEO_SRC` is supplied, so the public landing never
shows a broken empty video frame. Set `DEMO_VIDEO_SRC` and optionally
`DEMO_VIDEO_POSTER` at build time when the separate Remotion asset exists.

## Production checks

Do not pass `OPENCODE_GO_API_KEY`, `DEEPSEEK_API_KEY`, or any other provider
credential to the demo stack. `SECRET_KEY` is still required by the shared
application configuration even though authentication is disabled at the demo
edge. Keep it in the deployment environment, never in `.env`, source, or an
image layer.
