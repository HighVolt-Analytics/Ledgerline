"""Default classifier rules — moved to data/document_type_classifiers.json."""

from app.schemas.document_type import DocumentTypeClassifier
from app.services.document_type_classifier_templates import classifier_template_for_code


def default_classifier_for_code(code: str) -> DocumentTypeClassifier:
    """Backward-compatible loader for tests referencing the old module."""
    template = classifier_template_for_code(code)
    if template is None:
        return DocumentTypeClassifier()
    return DocumentTypeClassifier.model_validate(template)
