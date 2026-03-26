# Azure MSAL Authentication

## Context

Current API key auth is sufficient for internal/dev use but not for production multi-tenant deployment. Need Azure AD/Entra ID authentication via MSAL (Microsoft Authentication Library) as an option alongside API key auth.

## Requirements

- Azure AD app registration with client ID + tenant ID
- MSAL.js on frontend for interactive login (redirect or popup flow)
- Backend validates JWT access tokens from Azure AD
- Support both auth methods: API key (for service-to-service) and MSAL (for browser users)
- Role-based access if needed later (admin vs. viewer)

## Implementation Sketch

### Frontend
- `@azure/msal-browser` + `@azure/msal-react` packages
- `MsalProvider` wrapping the app
- `AuthGate` checks for MSAL session OR API key in sessionStorage
- Authenticated fetch wrapper adds `Authorization: Bearer <token>` header
- WS auth: acquire token, pass as `?token=` query param (same pattern as API key)

### Backend
- `python-jose` or `PyJWT` for JWT validation
- Verify token issuer, audience, expiry, signature against Azure AD JWKS endpoint
- `verify_auth` dependency chain: try Bearer token first, fall back to API key
- Cache JWKS keys with TTL to avoid hitting Azure AD on every request

### Configuration
```bash
# .env additions
AUTH_PROVIDER=msal          # or "apikey" or "none" (development)
AZURE_CLIENT_ID=...
AZURE_TENANT_ID=...
AZURE_AUTHORITY=https://login.microsoftonline.com/{tenant_id}
```

## Priority

Medium-high — required before any external/multi-tenant deployment. API key auth is the bridge until this lands.
