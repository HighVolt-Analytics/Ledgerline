"""Xero accounting connectivity.

All OAuth, HTTP, sync, export, and master write-back live in this package.
SQLAlchemy tables stay in ``app.models`` (xero_*); HTTP routes stay in ``app.api``.

Layout
------
oauth / tokens / store / connect_api   handshake and token persistence
client                                 Accounting API client (new layer)
http_legacy                            older retry client still used by verify/reconcile
sync / sync_jobs / sync_counts         inbound pull
tax_rates                              tax rate sync/create/update/delete
accounts / account_types               chart of accounts sync/create/update/delete
export / accpay / attachments / push   ACCPAY draft bills
contacts / mapping / errors            supplier resolve and mapping gates
master_data / organisation_isolation   cached org lists
verify / readiness / reconcile         connection health
background_sync                        scheduled jobs
"""
