from django.db import models

from ..contexts import SCHEMA
from .linked_data import AbstractContextModel


class Language(models.Model):
    class LanguageCodes(models.TextChoices):
        en = ("en", "English")

    code = models.CharField(max_length=10, primary_key=True)
    name = models.TextField()

    def __str__(self):
        return f"{self.name} ({self.code})"


class SchemaLanguageContext(AbstractContextModel):
    """
    Context model for schema.org Language vocabulary.
    Stores only the ISO code; human-readable names come from lookup table.
    """

    LINKED_DATA_FIELDS = {"identifier": SCHEMA.identifier}

    # Only store the ISO 639 language code
    identifier = models.CharField(max_length=10, db_index=True, unique=True)

    @property
    def name(self):
        return self.LanguageCodes.get_value(self.identifier)

    @classmethod
    def should_handle_reference(cls, g, reference):
        return reference.get_value(g, predicate=SCHEMA.identifier) is not None


__all__ = ("SchemaLanguageContext",)
