# Authorization, IDOR, missing authentication, privilege (CWE-269, 284, 285, 306, 639, 862, 863)

**Tuple.** A caller reaches a protected object or action, or a state transition, through a path whose guard is
missing, wrong, or bypassable.

## Complete fix
- Enforce the check on the server, in the handler or in the shared service function, for **every** action
  (read, create, update, delete, list, export, bulk, admin) and for every route alias and API version. Deny by
  default.
- **Ownership:** derive identity, tenant, and role from the authenticated principal, never from request
  parameters. Check that the subject owns, or is granted, this specific object, not just that it is logged in.
- **Privilege from user data:** a privilege derived from data a user or tenant controls (a name prefix, a
  self-set field, a label) must be removed, not made trustworthy by guarding the code that writes it.
- **Preconditions in the entry point:** a promise like "only after the caller is authenticated" is enforced inside
  the exported handler itself, not left to a wrapper that some callers or routes skip.
- **Fallback and self branches** ("owner can always…", "if no policy, allow…", service-account or
  parent-credential shortcuts) must go through the same policy evaluation or be removed.
- **Derived credentials** (child tokens, service accounts, impersonation) must not be able to widen their own
  permissions or those of their parent.
- **Self-service updates:** compare the requested change field by field. Block changes to role, group, tenant,
  verification state, MFA, recovery, and other security fields, including aliases of those fields and
  collection-valued fields.
- **Missing authentication:** sensitive functions (admin, configuration, debug, file, and execution endpoints)
  need authentication even when they are "internal". Environment-variable switches that skip auth are bugs.
- Only middleware that wraps the handler counts (route guards, decorators, interceptors). Edge, proxy, and UI
  hiding are not authorization.
- Values a framework rebuilds from request headers (full URL, base URL, host, scheme) are attacker-controlled.
  Make route and authorization decisions on the raw path from the server's request scope.
- Look for inverted conditions, early returns that skip a check, and checks done after side effects.

## Incomplete fixes
- Hiding the button or link.
- Checking only the first request of a multi-step flow.
- Protecting the main route while batch, export, legacy, or alternate-protocol endpoints still reach the same
  action.
