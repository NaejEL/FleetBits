"""Single source of truth for the site-scoping decision of the API routers.

Eleven modules used to answer "is this caller confined to one site?" on their
own. ``telemetry.py`` looked at ``site_scope`` alone, so an ``admin`` carrying a
``site_scope`` was confined; the other ten required a non-``admin`` ``role``
*and* a ``site_scope``, so the same token read the whole fleet. ``TokenPayload``
allows both that shape and its mirror — a token carrying no ``site_scope`` at
all — which every module used to serve fleet-wide.

The decision now lives here, in the strictest form of each disagreement that
does not break a role the data model describes as fleet-wide
(GUIDELINES §1, §3 — fail closed, least privilege):

- a token **carrying** a ``site_scope`` is confined to it, whatever its role —
  assigning a scope is always a meaningful, confining act;
- a token carrying **no** ``site_scope`` is refused outright when its role is
  one the model describes as scopable, and served fleet-wide when its role is
  fleet-wide by nature.

Which roles are which comes from the data model, not from taste.
``app/models/user.py`` declares ``VALID_ROLES = {admin, operator, technician,
viewer, ci_bot}`` and documents that "``site_scope`` restricts *operator-role*
users to a single site". So:

- ``operator`` and ``technician`` are the human, site-bound roles: a token of
  either that carries no scope is an anomaly, and is refused;
- ``admin``, ``ci_bot`` and ``viewer`` are fleet-wide by nature. A ``ci_bot``
  key is *minted* without a scope (``app/schemas/user.py`` defaults
  ``ApiKeyCreate.role`` to ``ci_bot`` with ``site_scope=None``), and a
  ``viewer`` is a fleet-wide read role. Refusing them here would not harden
  anything: it would delete the ring-0 rules of ``deployments.py`` by making
  them unreachable, and lock every fleet-wide reader out of the inventory.
  They stay subject to their own controls — role gates, and the ring-0
  restriction the deployment router applies to ``ci_bot``.

Any role outside those five — a value that could only come from a forged or
stale token — is treated as scopable, i.e. refused. The allow-list is the
fleet-wide set, so the default answer is "confine, or refuse".
"""

from fastapi import HTTPException, status

from app.services.token import TokenPayload

#: Roles whose normal shape carries no ``site_scope``. Everything else that
#: arrives without a scope is refused, so this set — not its complement — is
#: what has to be kept in step with ``app/models/user.py``.
FLEET_WIDE_ROLES = frozenset({"admin", "ci_bot", "viewer"})


def require_site_scope(user: TokenPayload) -> str | None:
    """Return the site this caller is confined to, or ``None`` for a fleet-wide caller.

    Raises HTTP 403 for a token of a scopable role (``operator``,
    ``technician``, or any unrecognised role) that carries no ``site_scope``:
    there is no site to confine such a caller to, so it is refused rather than
    served fleet-wide data.
    """
    if user.site_scope:
        return user.site_scope
    # The per-router copies this replaced all spelled the question
    # `user.role != "admin" and bool(user.site_scope)`, which answered "not
    # confined" for both shapes above. This is the single remaining definition.
    if user.role not in FLEET_WIDE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token carries no site scope; site-scoped data access denied",
        )
    return None
