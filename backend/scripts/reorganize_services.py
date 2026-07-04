"""One-shot migration: flat app.services -> domain subpackages. No behavior changes."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SERVICES = BACKEND / "app" / "services"

# module_name -> subpackage directory
MODULE_TO_PACKAGE: dict[str, str] = {
    # ingest
    "attachment_filter": "ingest",
    "capture_channel": "ingest",
    "email_ingestion": "ingest",
    "email_recipient_validation": "ingest",
    "gmail_ingestion": "ingest",
    "gmail_oauth_service": "ingest",
    "graph_client": "ingest",
    "graph_mail_folders": "ingest",
    "graph_mail_sender": "ingest",
    "ingest_capture_service": "ingest",
    "ingest_fanout_service": "ingest",
    "inline_mailbox_poller": "ingest",
    "mailbox_backfill_service": "ingest",
    "mailbox_inbox_poll": "ingest",
    "mailbox_invite_service": "ingest",
    "mailbox_oauth_service": "ingest",
    "mailbox_poll": "ingest",
    "mailbox_provider": "ingest",
    "viber_client": "ingest",
    "viber_connection_service": "ingest",
    "viber_ingest_service": "ingest",
    "whatsapp_connection_service": "ingest",
    "whatsapp_graph_client": "ingest",
    "whatsapp_ingest_service": "ingest",
    # classification
    "classifier_catalogue_compiler": "classification",
    "classification_audit_service": "classification",
    "classification_compare_service": "classification",
    "classification_drift_service": "classification",
    "classification_learning_service": "classification",
    "document_classifier_builder": "classification",
    "document_type_approval_service": "classification",
    "document_type_catalog": "classification",
    "document_type_catalogue_match": "classification",
    "document_type_classifier": "classification",
    "document_type_classifier_seeds": "classification",
    "document_type_classifier_templates": "classification",
    "document_type_classify_preview": "classification",
    "document_type_conflicts": "classification",
    "document_type_field_checks": "classification",
    "document_type_field_defaults": "classification",
    "document_type_field_keys": "classification",
    "document_type_lifecycle": "classification",
    "document_type_match_service": "classification",
    "document_type_playbook_profile_service": "classification",
    "document_type_playbook_service": "classification",
    "document_type_reclassify_service": "classification",
    "document_type_recognition_service": "classification",
    "document_type_recognition_signals": "classification",
    "document_type_rule_engine": "classification",
    "document_type_sample_analyzer": "classification",
    "document_type_sample_types": "classification",
    "document_type_scoring_service": "classification",
    "document_type_validation_service": "classification",
    "finance_dt_policy_scorer": "classification",
    "heading_kind_recognition": "classification",
    "legacy_cascade": "classification",
    "playbook_profile_catalog": "classification",
    "recognition_signal_catalog": "classification",
    "recognition_signal_registry": "classification",
    "sample_cluster_service": "classification",
    "sample_proposal_engine": "classification",
    "segment_heading_classification": "classification",
    # rule_book
    "account_mapper": "rule_book",
    "custom_validation_service": "rule_book",
    "extended_validations": "rule_book",
    "rule_book_audit": "rule_book",
    "rule_book_config_io": "rule_book",
    "rule_book_config_repository": "rule_book",
    "rule_book_evaluate_service": "rule_book",
    "rule_book_ingest_stats": "rule_book",
    "rule_book_mapper": "rule_book",
    "rule_book_save_buffer": "rule_book",
    "rule_engine": "rule_book",
    "validation_rule_catalog": "rule_book",
    "validation_runner": "rule_book",
    "validator": "rule_book",
    # invoice
    "invoice_access_service": "invoice",
    "invoice_data": "invoice",
    "invoice_edit_service": "invoice",
    "invoice_evaluation_service": "invoice",
    "invoice_pipeline_phases": "invoice",
    "invoice_related_query_service": "invoice",
    "invoice_reset": "invoice",
    "invoice_response_service": "invoice",
    "non_posting_document_service": "invoice",
    "pipeline": "invoice",
    "pipeline_stages": "invoice",
    "processing_api_service": "invoice",
    "processing_override_catalog": "invoice",
    "remap_service": "invoice",
    "routing_review_service": "invoice",
    # purchase
    "expense_vendor_policy": "purchase",
    "po_reference": "purchase",
    "purchase_coding_service": "purchase",
    "purchase_document_service": "purchase",
    "purchase_dossier_service": "purchase",
    "purchase_linking_service": "purchase",
    "purchase_match_service": "purchase",
    "team_expense_approval": "purchase",
    "team_expense_service": "purchase",
    "team_expense_validator": "purchase",
    # sales
    "counterparty_service": "sales",
    "sales_coding_service": "sales",
    "sales_document_service": "sales",
    "sales_dossier_service": "sales",
    "sales_linking_service": "sales",
    "sales_match_service": "sales",
    "so_reference": "sales",
    # dossier
    "document_duplicate_service": "dossier",
    "document_ref_service": "dossier",
    "dossier_api_service": "dossier",
    "dossier_approval_service": "dossier",
    "dossier_audit": "dossier",
    "dossier_linked_documents_service": "dossier",
    "dossier_manual_link_service": "dossier",
    "dossier_match_service": "dossier",
    "dossier_pipeline_service": "dossier",
    "dossier_service": "dossier",
    # payments
    "fx_posting_service": "payments",
    "journal_generator": "payments",
    "payment_execution_auth": "payments",
    "payment_execution_instruction_service": "payments",
    "payment_execution_readiness_service": "payments",
    "payment_execution_rules": "payments",
    "payment_rail_service": "payments",
    "payment_service": "payments",
    "stripe_global_payouts_service": "payments",
    "stripe_service": "payments",
    # auth
    "auth_account_service": "auth",
    "auth_email_service": "auth",
    "auth_service": "auth",
    "auth_session_service": "auth",
    "membership_enumeration": "auth",
    "membership_service": "auth",
    "privilege_service": "auth",
    # audit
    "audit_change_summary": "audit",
    "audit_detail_helpers": "audit",
    "audit_export_service": "audit",
    "audit_log_service": "audit",
    "audit_service": "audit",
    # tenant
    "org_ai_brief_service": "tenant",
    "platform_service": "tenant",
    "tenant_context_service": "tenant",
    "tenant_members_service": "tenant",
    "tenant_module_service": "tenant",
    "tenant_org_context": "tenant",
    "tenant_storage_paths": "tenant",
    # vault
    "vault_blob_sync": "vault",
    "vault_invoice_paths": "vault",
    "vault_migrate": "vault",
    "vault_paths": "vault",
    "vault_service": "vault",
    # reports
    "dashboard_service": "reports",
    "matrix_service": "reports",
    "reports_service": "reports",
    "reports_workbook_service": "reports",
    "workbook_writer": "reports",
    # reconciliation
    "reconciliation_api_service": "reconciliation",
    "reconciliation_overview": "reconciliation",
    "reconciliation_service": "reconciliation",
    # approval
    "approval_api_service": "approval",
    "approval_board_service": "approval",
    "approval_pipeline_service": "approval",
    "approval_policy_io": "approval",
    "approval_service": "approval",
    # master_data
    "bundle_vendor_service": "master_data",
    "chart_of_accounts_service": "master_data",
    "customer_master_service": "master_data",
    "customer_registry_service": "master_data",
    "employee_import_service": "master_data",
    "master_data_service": "master_data",
    "uom_conversion_service": "master_data",
    "vendor_detection": "master_data",
    "vendor_hold_service": "master_data",
    "vendor_name_utils": "master_data",
    "vendor_payout_method_service": "master_data",
    "vendor_registration_policy": "master_data",
    "vendor_registry_service": "master_data",
    "vendor_resolver": "master_data",
    "vendor_seed": "master_data",
    # integration
    "accounting_integration_service": "integration",
    "collection_service": "integration",
    "ledger_link_service": "integration",
    "publish_service": "integration",
    # extraction
    "azure_foundry_vision_client": "extraction",
    "azure_openai_client": "extraction",
    "di_extract_service": "extraction",
    "document_ai_provider": "extraction",
    "document_heading_utils": "extraction",
    "document_intelligence": "extraction",
    "document_layout_service": "extraction",
    "document_text": "extraction",
    "extraction_field_values": "extraction",
    "field_extraction_confidence": "extraction",
    "gemini_vision_client": "extraction",
    "layout_field_extractor": "extraction",
    "line_items_parser": "extraction",
    "llm_document_service": "extraction",
    "pdf_page_text_service": "extraction",
    "pdf_parser": "extraction",
    "pdf_segment_service": "extraction",
    "pdf_split_service": "extraction",
    "permit_ocr_extractors": "extraction",
    "vision_pdf": "extraction",
    # shared
    "amount_sanity": "shared",
    "billing_io": "shared",
    "blob_storage": "shared",
    "currency": "shared",
    "file_storage": "shared",
    "notifier": "shared",
    "public_api_url": "shared",
    "public_app_url": "shared",
    "token_vault": "shared",
}

PACKAGES = sorted(set(MODULE_TO_PACKAGE.values()))


def module_import_path(module: str) -> str:
    return f"app.services.{MODULE_TO_PACKAGE[module]}.{module}"


def rewrite_imports(text: str) -> str:
    modules_by_len = sorted(MODULE_TO_PACKAGE, key=len, reverse=True)

    for module in modules_by_len:
        pkg = MODULE_TO_PACKAGE[module]
        new_prefix = f"app.services.{pkg}.{module}"
        # already namespaced
        text = re.sub(
            rf"\bfrom app\.services\.{re.escape(module)}\b(?!\.)",
            f"from {new_prefix}",
            text,
        )
        text = re.sub(
            rf"\bimport app\.services\.{re.escape(module)}\b(?!\.)",
            f"import {new_prefix}",
            text,
        )

    def replace_services_import(match: re.Match[str]) -> str:
        names = [n.strip() for n in match.group(1).split(",") if n.strip()]
        by_pkg: dict[str, list[str]] = {}
        unknown: list[str] = []
        for name in names:
            pkg = MODULE_TO_PACKAGE.get(name)
            if pkg is None:
                unknown.append(name)
            else:
                by_pkg.setdefault(pkg, []).append(name)
        if unknown:
            raise ValueError(f"Unknown service modules in import: {unknown}")
        lines = []
        for pkg in sorted(by_pkg):
            mods = ", ".join(by_pkg[pkg])
            lines.append(f"from app.services.{pkg} import {mods}")
        return "\n".join(lines)

    text = re.sub(
        r"from app\.services import ([^\n]+)",
        replace_services_import,
        text,
    )
    return text


def move_modules() -> None:
    flat_modules = [
        p for p in SERVICES.glob("*.py") if p.is_file()
    ]
    found = {p.stem for p in flat_modules}
    expected = set(MODULE_TO_PACKAGE)
    missing = expected - found
    extra = found - expected
    if missing:
        raise SystemExit(f"Mapping references missing modules: {sorted(missing)}")
    if extra:
        raise SystemExit(f"Unmapped modules in services/: {sorted(extra)}")

    for pkg in PACKAGES:
        (SERVICES / pkg).mkdir(exist_ok=True)

    for path in flat_modules:
        module = path.stem
        dest = SERVICES / MODULE_TO_PACKAGE[module] / path.name
        shutil.move(str(path), str(dest))

    init_root = SERVICES / "__init__.py"
    if not init_root.exists():
        init_root.write_text(
            '"""Domain-organized business logic (see subpackages)."""\n',
            encoding="utf-8",
        )

    for pkg in PACKAGES:
        init_path = SERVICES / pkg / "__init__.py"
        if not init_path.exists():
            init_path.write_text(f'"""{pkg.replace("_", " ")} services."""\n', encoding="utf-8")


def update_all_imports() -> int:
    changed = 0
    for path in BACKEND.rglob("*.py"):
        if path.name == "reorganize_services.py":
            continue
        original = path.read_text(encoding="utf-8")
        updated = rewrite_imports(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return changed


def main() -> None:
    move_modules()
    n = update_all_imports()
    print(f"Moved {len(MODULE_TO_PACKAGE)} modules into {len(PACKAGES)} subpackages.")
    print(f"Updated imports in {n} files.")


if __name__ == "__main__":
    main()
