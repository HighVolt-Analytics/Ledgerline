from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "services" / "integration" / "accounting_integration_service.py"
text = p.read_text(encoding="utf-8")
text = text.replace("resolve_resolve_xero_scopes", "resolve_xero_scopes")
p.write_text(text, encoding="utf-8")
print("fixed scope function name")
