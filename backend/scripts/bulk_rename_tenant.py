"""One-off bulk rename org -> tenant in backend Python files."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
TESTS = Path(__file__).resolve().parents[1] / "tests"
SKIP = {
    "auth.py",
    "deps.py",
    "tenant_context_service.py",
    "membership_service.py",
    "auth_service.py",
    "027_tenant_saas_foundation.py",
}

REPLACEMENTS = [
    ("ctx.org_id", "ctx.tenant_id"),
    ("org_id=", "tenant_id="),
    ("org_id:", "tenant_id:"),
    ("org_id,", "tenant_id,"),
    ("org_id)", "tenant_id)"),
    ("org_id ", "tenant_id "),
    ("(org_id", "(tenant_id"),
    (".org_id", ".tenant_id"),
    ("org_slug", "tenant_slug"),
    ("org_name", "tenant_name"),
    ("Organisation", "Tenant"),
    ("organisations", "tenants"),
    ("UserOrgMembership", "UserTenantMapping"),
    ("user_org_memberships", "user_tenant_mappings"),
    ("org_context", "tenant_context_service"),
    ("org_membership", "membership_service"),
    ("get_or_create_default_org", "get_or_create_default_tenant"),
    ("get_org_slug", "get_tenant_slug"),
    ("get_org_by_id", "get_tenant_by_id"),
    ("default_org_slug", "default_tenant_slug"),
    ("default_org_name", "default_tenant_name"),
    ("list_user_organisations", "list_user_tenants"),
    ("user_has_org_access", "user_has_tenant_access"),
    ("SwitchOrgRequest", "SwitchTenantRequest"),
    ("switch-org", "switch-tenant"),
    ("switch_organisation", "switch_tenant"),
    ("vault_org_folder", "vault_tenant_folder"),
    ("org_rule_book_config_path", "tenant_rule_book_config_path"),
    ("_seed_org_rule_book_config", "_seed_tenant_rule_book_config"),
    ("for_org(", "for_tenant("),
    ("load_config_for_org", "load_config_for_tenant"),
]


def main() -> None:
    for base in (ROOT, TESTS):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.name in SKIP or "027_tenant" in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            orig = text
            for old, new in REPLACEMENTS:
                text = text.replace(old, new)
            if text != orig:
                path.write_text(text, encoding="utf-8")
                print("updated", path)


if __name__ == "__main__":
    main()
