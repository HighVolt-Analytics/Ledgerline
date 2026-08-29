OAuth 2.0 & Multi-Tenant App Registration ArchitectureLedgerLink acts as a multi-tenant SaaS where each tenant organization connects its own distinct Xero organization.+-----------------------------------------------------------------------------------+
|                               LEDGERLINK ARCHITECTURE                             |
|                                                                                   |
|  +-------------------+       +--------------------+       +--------------------+  |
|  |    React 18 UI    | ----> |   FastAPI Engine   | ----> |   PostgreSQL RLS   |  |
|  |  (TanStack Query) |       |  (OAuth / Sync API)|       |  (Encrypted Vault) |  |
|  +-------------------+       +--------------------+       +--------------------+  |
|                                        |                             |            |
|                                        v                             |            |
|                              +--------------------+                  |            |
|                              |  Celery + Redis    | <----------------+            |
|                              |  (Async Export)    |                               |
|                              +--------------------+                               |
|                                        |                                          |
|                                        v                                          |
|                              +--------------------+                               |
|                              |  Xero REST API v2  |                               |
|                              | (Invoices/Attach)  |                               |
|                              +--------------------+                               |
+-----------------------------------------------------------------------------------+
1. App Registration ModelApp Type: Use a Standard Web App (authorization_code grant with client secret). Do not use Custom Connections; Custom Connections are strictly single-tenant, machine-to-machine integrations billed per individual organization ($5–$10/month per connection) and cannot be dynamically initiated by end-users in a multi-tenant SaaS.  Redirect URIs:Local Dev: http://localhost:8001/api/integrations/xero/callbackStaging: [https://staging.ledgerlink.com/api/integrations/xero/callback](https://staging.ledgerlink.com/api/integrations/xero/callback)Production: [https://app.ledgerlink.com/ledgerlink/api/integrations/xero/callback](https://app.ledgerlink.com/ledgerlink/api/integrations/xero/callback)2. OAuth Scopes (Granular Scopes)Request the minimum necessary scopes to maintain security hygiene:ScopePurposeRead/Writeoffline_accessRequired to obtain a 60-day rolling refresh token.Token Managementopenid profile emailBase OpenID Connect user context for audit logging.Readaccounting.settings.readPull Chart of Accounts, Tax Rates, Tracking Categories, and Org details.Readaccounting.contactsRead existing suppliers; create new contacts when missing.Read / Writeaccounting.invoicesCreate and read ACCPAY bills.Read / Writeaccounting.attachmentsUpload source PDF attachments directly to bills.Read / Write3. Token Lifecycle & Storage SchemaAccess Tokens: Valid for 30 minutes (1,800 seconds).Refresh Tokens: Single-use with rolling 60-day expiry. Every refresh request returns a new refresh token and invalidates the previous one (Xero permits a ~30-minute retry grace period for network drops).Database Entity (tenant_xero_connections):id (UUID, PK)tenant_id (UUID, Indexed, Unique, Foreign Key with PostgreSQL RLS enforcement)xero_tenant_id (UUID, Xero’s organization GUID)xero_tenant_name (String, display name)access_token_encrypted (Bytea / Text, AES-256-GCM / Fernet encrypted)refresh_token_encrypted (Bytea / Text, AES-256-GCM / Fernet encrypted)token_expires_at (TIMESTAMPTZ)scopes (Text array)sync_status (ENUM: CONNECTED, SYNCING, ERROR, DISCONNECTED, ACTION_REQUIRED)last_sync_at (TIMESTAMPTZ)created_at, updated_at (TIMESTAMPTZ)Sequence Diagrams (Word-Based)Flow 1: Connect (OAuth 2.0 Dance & Tenant Selection)[React UI]          [FastAPI Backend]            [PostgreSQL]              [Xero Identity]
    |                       |                          |                          |
    |-- Click "Connect" --->|                          |                          |
    |                       |-- Generate State Token ->| (Store State in Redis)   |
    |<- Auth URL + State ---|                          |                          |
    |                                                                             |
    |-- Redirect Browser to Xero Authorization URL ------------------------------>|
    |                                                                             |
    |                                   (User authenticates & authorizes org)    |
    |                                                                             |
    |<-- Redirect to /api/integrations/xero/callback?code=XYZ&state=ABC ----------|
    |                       |                          |                          |
    |-- Forward Callback -->|                          |                          |
    |                       |-- Validate State ------->| (Check Redis & Expire)   |
    |                       |                                                     |
    |                       |-- POST /connect/token (code + secret) ------------->|
    |                       |<-- Return {access_token, refresh_token} ------------|
    |                       |                                                     |
    |                       |-- GET https://api.xero.com/connections ------------>|
    |                       |<-- Return [{id, tenantId, tenantName}] -------------|
    |                       |                          |                          |
    |                       |-- Encrypt & Store Token->| (Upsert Connection Row)  |
    |<- Return Status 200 --|                          |                          |
If a user authorizes multiple Xero organizations, FastAPI stores the available tenants and returns the list to React, requiring the tenant admin to explicitly select which Xero tenant binds to their LedgerLink account.Flow 2: Master Data Sync (Pull Settings)[React UI]          [FastAPI Backend]            [PostgreSQL]              [Xero REST API]
    |                       |                          |                          |
    |-- "Sync Master Data"->|                          |                          |
    |                       |-- Dispatch Celery Task ->|                          |
    |<- Accepted (202) -----|                          |                          |
    |                                                                             |
    |   [Celery Worker]                                                           |
    |          |-- Fetch Valid Access Token ---------->|                          |
    |          |   (Auto-refresh if expired < 5 min)   |                          |
    |          |                                                                  |
    |          |-- GET /api.xro/2.0/Accounts (Type: EXPENSE, DIRECTCOSTS, etc.) ->|
    |          |-- GET /api.xro/2.0/TaxRates ------------------------------------>|
    |          |-- GET /api.xro/2.0/TrackingCategories -------------------------->|
    |          |-- GET /api.xro/2.0/Contacts (IsSupplier: true) ----------------->|
    |          |                                                                  |
    |          |<-- Return Master Data Payloads ----------------------------------|
    |          |                                       |                          |
    |          |-- Batch Upsert Normalized Master Data>| (Scoped to Tenant ID)    |
    |          |-- Update Connection last_sync_at ---->|                          |
Flow 3: Mapping & Configuration[React UI]                 [FastAPI Backend]                  [PostgreSQL]
    |                              |                                |
    |-- GET /xero/master-data ---->|                                |
    |                              |-- Query Local Accounts/Taxes ->|
    |<- Return Options List -------|                                |
    |                                                               |
    | (User maps: LL Supplier -> Xero Contact,                      |
    |  LL Category -> Xero GL Account Code,                         |
    |  LL Tax Code -> Xero TaxType)                                 |
    |                                                               |
    |-- POST /xero/mappings ------>|                                |
    |                              |-- Upsert Tenant Mappings ----->|
    |<- Mapping Saved 200 ---------|                                |
Flow 4: Export Bill with PDF Attachment[User / Rule Engine]       [FastAPI Backend]     [Celery Worker]     [PostgreSQL]     [Azure Blob]     [Xero REST API]
         |                         |                    |                 |                |                 |
         |-- Approve & Export ---->|                    |                 |                |                 |
         |                         |-- Enqueue Task --->|                 |                |                 |
         |                         |-- Record Status -->| (PENDING in     |                |                 |
         |<- 202 Export Queued ----|                    |  Export Ledger) |                |                 |
         |                                              |                 |                |                 |
         |                                              |-- Load Invoice, |                |                 |
         |                                              |   Mappings,     |                |                 |
         |                                              |   Token ------->|                |                 |
         |                                              |                                  |                 |
         |                                              |-- Fetch PDF Binary ------------->|                 |
         |                                              |<-- Return PDF Stream ------------|                 |
         |                                              |                                                    |
         |                                              |-- POST /api.xro/2.0/Invoices (ACCPAY Draft) ------>|
         |                                              |<-- Return 200 {InvoiceID: "guid-123"} -------------|
         |                                              |                                                    |
         |                                              |-- POST /api.xro/2.0/Invoices/guid-123/Attachments/invoice.pdf
         |                                              |<-- Return 200 Attachment Confirmation -------------|
         |                                              |                 |                                  |
         |                                              |-- Update Ledger>| (EXPORTED, XeroID, Hash)         |
Flow 5: Webhook & Reconcile[Xero Webhook Dispatcher]       [FastAPI Webhook Handler]      [Redis / Celery]      [Xero API / PostgreSQL]
            |                               |                         |                         |
            |-- POST /api/xero/webhooks --->|                         |                         |
            |   (Header: x-xero-signature)  |                         |                         |
            |                               |-- Compute HMAC-SHA256   |                         |
            |                               |   vs Raw Body & Secret  |                         |
            |                               |-- Signature Invalid?    |                         |
            |                               |   Return 401            |                         |
            |                               |-- Signature Valid:      |                         |
            |                               |   Enqueue Event Payloads|                         |
            |<- Return 200 OK --------------|                         |                         |
            |                                                         |                         |
            |                                     [Celery Worker] <---|                         |
            |                                            |                                      |
            |                                            |-- Deduplicate Event by ResourceID    |
            |                                            |-- GET /api.xro/2.0/Invoices/{id} --->|
            |                                            |<-- Return Full Invoice Payload ------|
            |                                            |                                      |
            |                                            |-- Check if Bill Status Changed       |
            |                                            |   (e.g., DRAFT -> AUTHORISED / PAID) |
            |                                            |-- Update Export Ledger Status ------>|
REST Outbound API & Inbound Webhooks Protocol1. Outbound API Calls (api.xero.com)Base URL: [https://api.xero.com/api.xro/2.0/](https://api.xero.com/api.xro/2.0/)Standard Headers:Authorization: Bearer <access_token>Xero-tenant-id: <xero_tenant_id>Accept: application/jsonContent-Type: application/json (or application/pdf for file attachments)Idempotency-Key: <unique_uuid> (guarantees safe retries on transient failures)2. Rate Limit Budget & Backoff StrategyXero applies four tiers of rate limiting:Minute Limit: 60 calls per minute per organization.  Daily Limit: 5,000 calls per 24-hour rolling window per organization.  Concurrent Limit: Maximum 5 simultaneous open requests per organization.  App-wide Limit: 10,000 calls per minute across all connected tenants.  Handling Mechanism:Celery uses a Redis-backed token-bucket rate limiter configured to max 40 requests/minute per tenant (leaving buffer for ad-hoc UI calls).If Xero returns HTTP 429 Too Many Requests, inspect the Retry-After header. Celery worker immediately pauses and reschedules the task using countdown=int(retry_after) + 2.                  +--------------------------------+
                  |  Inbound Xero Webhook Request  |
                  +--------------------------------+
                                   |
                                   v
                  +--------------------------------+
                  | Verify HMAC-SHA256 Signature   |
                  +--------------------------------+
                               /       \
                              /         \
                    [Valid]  /           \  [Invalid]
                            v             v
             +---------------------+   +---------------------+
             | Return HTTP 200 OK  |   | Return HTTP 401     |
             +---------------------+   | Unauthorized        |
                        |              +---------------------+
                        v
             +---------------------+
             | Push Event to Redis |
             +---------------------+
                        |
                        v
             +---------------------+
             | Celery Worker:      |
             | GET Invoice & Update|
             +---------------------+
3. Inbound Webhooks ArchitectureRole vs REST: REST is the authoritative push/pull channel. Webhooks serve strictly as a reactive trigger to detect when a Xero user approves (AUTHORISED), edits, or pays (PAID) an exported draft bill in Xero without polling.  Signature Verification (HMAC-SHA256):Xero sends an x-xero-signature header with every webhook payload.  FastAPI must read the raw bytes of the request body before JSON deserialization.Compute HMAC-SHA256 using the application's Webhook Signing Key as the secret key.  Base64-encode the resulting digest and perform a constant-time comparison against x-xero-signature.  Return HTTP 200 OK on match; return HTTP 401 Unauthorized on mismatch (required during the initial "Intent to Receive" setup handshake).  Payload Structure:Xero webhook payloads do not contain document details. They contain arrays of lightweight events:JSON{
  "events": [
    {
      "resourceUrl": "https://api.xero.com/api.xro/2.0/Invoices/c3866228-2b47-4951-8600-4d9f67a6d859",
      "resourceId": "c3866228-2b47-4951-8600-4d9f67a6d859",
      "eventCategory": "INVOICE",
      "eventType": "UPDATE",
      "eventDateUtc": "2026-08-28T06:00:00.000Z",
      "tenantId": "e186b5e8-5b1b-4395-9276-f8319f6a27e3"
    }
  ],
  "firstEventSequence": 1,
  "lastEventSequence": 1,
  "entropy": "xyz..."
}
Async Processing: The FastAPI endpoint returns HTTP 200 immediately (< 2 seconds required by Xero) and pushes the raw event array into Redis. A Celery worker consumes the event, matches the resourceId against xero_export_ledger.xero_invoice_id, and pulls the full updated record via REST API.Phase 1 Object Strategy & Minimal Payload ChecklistIn Xero, both Accounts Receivable (Sales) and Accounts Payable (Bills) use the Invoice endpoint. Bills are differentiated strictly by setting "Type": "ACCPAY".1. ACCPAY Bill Payload Schema (POST /api.xro/2.0/Invoices)JSON{
  "Invoices": [
    {
      "Type": "ACCPAY",
      "Contact": {
        "ContactID": "9c9103e3-78f0-466a-b286-a2468383e587"
      },
      "Date": "2026-08-28",
      "DueDate": "2026-09-28",
      "InvoiceNumber": "INV-2026-00892",
      "Reference": "LL-PO-84920",
      "Status": "DRAFT",
      "LineAmountTypes": "Exclusive",
      "CurrencyCode": "USD",
      "LineItems": [
        {
          "Description": "Consulting & Software Engineering Services - August 2026",
          "Quantity": 1.0,
          "UnitAmount": 4500.00,
          "AccountCode": "400",
          "TaxType": "INPUT",
          "Tracking": [
            {
              "Name": "Department",
              "Option": "Engineering"
            },
            {
              "Name": "Region",
              "Option": "North America"
            }
          ]
        }
      ]
    }
  ]
}
2. Supporting/Nested Field Resolution StrategyContact: Look up the matched ContactID from local tenant cache. If no match exists, either trigger Contact Creation (POST /api.xro/2.0/Contacts with { "Name": "Supplier Name" }) or abort with an "Unmapped Supplier" validation error based on tenant settings.AccountCode: Resolved from LedgerLink GL mapping table (e.g., LedgerLink Category "Cloud Hosting" $\rightarrow$ Xero Account Code "400").TaxType: Resolved from LedgerLink Tax mapping (e.g., "Standard VAT 20%" $\rightarrow$ "INPUT2", "Zero Rated" $\rightarrow$ "ZERORATEDINPUT").Tracking: Array containing up to 2 active Tracking Category Name/Option pairs (e.g., Department, Cost Center).LineAmountTypes: Defaults to Exclusive (Line items do not include tax) or Inclusive.Status: Hardcoded to DRAFT for Phase 1. Draft invoices do not affect GL balances and can be verified/approved by a finance manager inside Xero.3. PDF Attachment Protocol (POST /api.xro/2.0/Invoices/{InvoiceID}/Attachments/{FileName})Header: Content-Type: application/pdfQuery Parameter: IncludeOnline=true (makes attachment visible when viewing invoice in Xero).Payload: Raw binary stream fetched directly from Azure Blob storage.4. Export Ledger Record Schema (xero_export_ledger)id (UUID, PK)tenant_id (UUID, FK)ledgerlink_document_id (UUID, FK)xero_invoice_id (UUID, indexed)xero_invoice_number (String)export_status (PENDING, EXPORTED, FAILED, VOIDED, RECONCILED)payload_hash (SHA-256 of the outgoing JSON to prevent duplicate re-posts)xero_status (DRAFT, SUBMITTED, AUTHORISED, PAID, DELETED)error_details (JSONB: validation failures, missing codes)last_exported_at (TIMESTAMPTZ)LedgerLink-to-Xero Object Coverage & Scope MatrixLedgerLink Document / EntityXero Target ObjectXero Type / SubtypeDirectionPhase 1 ActionTechnical RationaleSupplier InvoiceInvoiceACCPAYPushCreate / UpdateCore Phase 1 MVP. Ingests supplier bills into Xero as DRAFT.Invoice Source FileAttachmentFile attachmentPushCreateAttaches original PDF from Azure Blob to the created ACCPAY bill.Supplier / VendorContactContact (IsSupplier)BidirectionalRead (Sync) + CreateMaster data sync pulls existing suppliers. Creates new supplier if auto-provisioning enabled.Chart of AccountsAccountEXPENSE, DIRECTCOSTS, CURRLIABPullRead-onlyCached locally so UI dropdowns allow GL code mapping.Tax RatesTaxRateOutput / Input tax ratesPullRead-onlyRequired for accurate tax calculation on Line Items.Cost Centers / DeptsTrackingCategoryTracking Category + OptionsPullRead-onlyAllows assigning Xero tracking dimensions to invoice line items.Tenant MetadataOrganisationBase Currency, Country, NamePullRead-onlyVerifies base currency and tax regime of the connected Xero org.Customer Sales InvoiceInvoiceACCRECPushPhase 2Out of scope for Phase 1 AP automation.Vendor Credit NoteCreditNoteACCPAYCREDITPushPhase 2Needed when processing credit memos / adjustments.Purchase OrderPurchaseOrderPOBidirectionalPhase 22-way / 3-way matching against existing Xero POs.Payment ConfirmationPaymentACCPAYPAYMENTPullPhase 2Syncing payment status back to LedgerLink vault.General Journal EntryManualJournalN/APushPhase 3Only needed for payroll/complex accrued expense allocations.Explicit Out of Scope List (Do Not Implement in Phase 1 or 2)Quote (Sales quoting)RepeatingInvoice (Recurring bill schedules)BankTransaction / BankTransfer (Direct bank feed management / Spend Money transactions)Overpayment / PrepaymentItem (Xero Untracked/Tracked Inventory items)BatchPayment (Xero payment execution / ABA files)ExpenseClaim / Receipt (Xero personal expense module)  Payroll / Employees (Handled via separate Xero Payroll APIs)Reports (Balance Sheet, Profit and Loss, Trial Balance)  Security, Isolation, & Failure Modes1. Security & Tenant SegregationTenant Isolation: All database tables (xero_integrations, xero_master_data, xero_mappings, xero_export_ledger) contain a non-nullable tenant_id column. PostgreSQL Row-Level Security (RLS) policies restrict all queries using the current_setting('app.current_tenant_id') session parameter set by FastAPI middleware.Token Vaulting: Tokens are never returned to the frontend. Access and refresh tokens are encrypted using symmetric envelope encryption (AES-256-GCM) with tenant-derived salt before writing to PostgreSQL.OAuth CSRF Mitigation: The state parameter generated prior to redirect is a signed, encrypted JWT containing {tenant_id, user_id, nonce, exp: now() + 10min}. The callback handler verifies the signature and checks that the authorizing user belongs to the active tenant session.2. Failure Modes & Edge Case Handling MatrixFailure ModeRoot CauseSystem Behavior & MitigationUser Remediation in UIMissing GL MappingExtracted invoice category has no mapped Xero Account Code.Celery export task fails pre-flight validation before calling Xero. Status set to FAILED.Integrations UI flags invoice with a prompt: "Map category 'Hardware' to a Xero GL Account to export."Contact DisambiguationExtracted supplier name matches multiple Xero contacts or has slight spelling variations.Do not guess. Stop export; mark status as MAPPING_REQUIRED.UI provides a contact resolution dropdown pre-filtered with closest Levenshtein matches.Currency MismatchInvoice is in EUR, but Xero Organization is on a Standard edition without Multi-Currency enabled.Xero API returns 400 Bad Request (Foreign currency not enabled).Error captured in Export Ledger. UI prompts user to either convert to base currency or enable currency in Xero.Validation Error: Closed PeriodInvoice date falls into a locked accounting period in Xero.Xero returns 400 Bad Request (The document date cannot be before the period lock date).UI displays lock-date violation. Allows admin to override the invoice posting date.Token Revoked / ExpiredRefresh token rotation failed, or admin revoked access inside Xero settings.Refresh call returns 400 invalid_grant. Integration status flipped to ACTION_REQUIRED.Integrations banner prompts tenant admin: "Xero connection expired. Click Re-authenticate."Organization SwitchedUser connected a different Xero org than originally configured during re-auth.Callback checks if incoming xero_tenant_id matches the stored xero_tenant_id. If mismatched, connection is blocked.UI warns user: "You attempted to connect 'Org B', but this tenant is mapped to 'Org A'. Disconnect first to switch."Environment Configuration & Open Questions1. Callback & Webhook Routing ArchitectureLOCAL DEVELOPMENT (Vite :5173 / FastAPI :8001)
  OAuth Callback:  http://localhost:8001/api/integrations/xero/callback (Direct to Backend)
  Webhooks:        Requires Ngrok tunnel -> https://<subdomain>.ngrok-free.app/api/integrations/xero/webhooks

STAGING / PRODUCTION (Behind Reverse Proxy / Ingress)
  Host:            https://app.ledgerlink.com
  Path Routing:    /ledgerlink/api/integrations/xero/callback
                   /ledgerlink/api/integrations/xero/webhooks
Note on Webhook Delivery: Local development cannot receive Xero webhooks directly on localhost. Developers must configure an active HTTPS tunnel (e.g., ngrok) and update the Webhook Delivery URL in the Xero Developer Portal during webhook testing.2. Open Questions for the Xero App Owner / AdminDeveloper App Registration Status: Has the Xero app been created in the Xero Developer Portal as a Standard Web App, and do we have access to the Client ID and Client Secret?  Demo Company Access: Has a Xero Demo Company (with active demo Chart of Accounts, tracking categories, and VAT/GST settings) been provisioned to test the complete OAuth flow and bill creation before connecting real client organizations?Webhook Signing Key Availability: Has the webhook subscription been created under the developer portal, and is the Webhook Signing Key available for configuring the HMAC validator?  App Tier & Certification Timeline: Is the app currently on the default developer tier (limited to 5–25 connections)? If LedgerLink expects more than 25 connected customer tenants, when will the app partner certification process be initiated with Xero?  