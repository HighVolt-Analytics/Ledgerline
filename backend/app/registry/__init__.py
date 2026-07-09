"""Universal field registry."""

from app.registry.adapter import RegistryAdapter, get_registry_adapter, use_field_registry
from app.registry.field_definition import FieldDefinition, FieldRegistry, JurisdictionFieldVariant
from app.registry.loader import clear_field_registry_cache, get_field_registry, load_field_registry_from_path

__all__ = [
    "FieldDefinition",
    "FieldRegistry",
    "JurisdictionFieldVariant",
    "RegistryAdapter",
    "clear_field_registry_cache",
    "get_field_registry",
    "get_registry_adapter",
    "load_field_registry_from_path",
    "use_field_registry",
]
