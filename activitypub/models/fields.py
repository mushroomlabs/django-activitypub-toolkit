from django.apps import apps
from django.db import models
from django.db.models.fields.related_descriptors import ManyToManyDescriptor
from django.db.models.signals import m2m_changed


class ReferenceRelationship(models.Model):
    """
    Base through model for ReferenceField relationships.

    This creates a many-to-many relationship between References,
    linking source_reference to target_reference instead of
    source_model to target_model.
    """

    source_reference = models.ForeignKey(
        "activitypub.Reference",
        on_delete=models.CASCADE,
        related_name="+",
    )
    target_reference = models.ForeignKey(
        "activitypub.Reference",
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        abstract = True
        unique_together = (("source_reference", "target_reference"),)


# Cache through models to avoid re-creating them
_through_model_cache = {}


class ReferenceField(models.ManyToManyField):
    """
    Many-to-many field that links via reference FKs instead of model PKs.

    Creates a through table that links source_reference_id to target_reference_id,
    allowing queries without requiring the source instance to have a pk.

    This field should only be used on models that have a 'reference' ForeignKey
    to the Reference model.

    Example:
        class ObjectContext(AbstractContextModel):
            reference = models.OneToOneField(Reference, on_delete=models.CASCADE)
            source = ReferenceField()

        # Works even if obj is unsaved:
        obj = ObjectContext(reference=some_ref)
        related_refs = obj.source.all()  # Queries via obj.reference, not obj.pk
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("related_name", "+")
        kwargs.setdefault("to", "activitypub.Reference")
        # Don't set through=None - we'll set it in contribute_to_class
        super().__init__(**kwargs)

    def contribute_to_class(self, cls, name, **kwargs):
        # Skip for abstract models
        if cls._meta.abstract:
            super().contribute_to_class(cls, name, **kwargs)
            return

        # Type assertion: remote_field is always set in __init__
        assert self.remote_field is not None

        # Create our custom through model BEFORE calling parent
        # This prevents Django from creating its default through model
        self._create_through_model(cls, name)

        # Now let parent handle the rest
        super().contribute_to_class(cls, name, **kwargs)

        # Replace the descriptor with our custom one
        setattr(cls, name, ReferenceRelatedDescriptor(self.remote_field, reverse=False))

    def _create_through_model(self, cls, name):
        """
        Create a reference-based through model BEFORE Django creates its default.

        Django's default through model links source_model_id -> target_model_id.
        We need source_reference_id -> target_reference_id.

        Uses ReferenceRelationship as the base class.
        """
        # Type assertion: this should only be called after __init__
        assert self.remote_field is not None

        through_name = f"{cls.__name__}_{name}"
        cache_key = f"{cls._meta.app_label}.{through_name}"

        # Check cache first
        if cache_key in _through_model_cache:
            self.remote_field.through = _through_model_cache[cache_key]
            return

        # Also check if already in app registry (for reload scenarios)
        try:
            existing = cls._meta.apps.all_models[cls._meta.app_label].get(through_name.lower())
            if existing:
                _through_model_cache[cache_key] = existing
                self.remote_field.through = existing
                return
        except (AttributeError, KeyError):
            pass

        db_table = f"{cls._meta.db_table}_{name}"

        # Create a proper Django model class inheriting from ReferenceRelationship
        through_attrs = {
            "Meta": type(
                "Meta",
                (),
                {
                    "db_table": db_table,
                    "app_label": cls._meta.app_label,
                    # Don't set auto_created so Django includes it in migrations
                },
            ),
            "__module__": cls.__module__,
        }

        # Create the through model inheriting from ReferenceRelationship
        through_model = type(through_name, (ReferenceRelationship,), through_attrs)

        # Register the through model in Django's app registry FIRST
        # This is essential for migrations and lazy reference resolution
        if through_name.lower() not in cls._meta.apps.all_models.get(cls._meta.app_label, {}):
            cls._meta.apps.register_model(cls._meta.app_label, through_model)

        # Cache it AFTER registering
        _through_model_cache[cache_key] = through_model

        # Set it on the remote_field so Django uses it instead of creating a new one
        # Use the string reference so Django resolves it from the registry
        self.remote_field.through = f"{cls._meta.app_label}.{through_name}"

    def _check_relationship_model(self, from_model=None, **kwargs):
        """
        Override M2M validation - our through table links references, not models.
        Django's default check expects FKs to source_model and target_model,
        but we have FKs to Reference instead.
        """
        return []

    def _check_ignored_options(self, **kwargs):
        """Skip parent's ignored options check"""
        return []

    def deconstruct(self):
        """
        Return enough information to recreate the field as a 4-tuple.
        Used by migrations.
        """
        name, path, args, kwargs = super().deconstruct()
        # Use the correct import path
        path = "activitypub.models.fields.ReferenceField"
        # Remove 'to' and 'through' since we always set them
        kwargs.pop("to", None)
        kwargs.pop("through", None)
        return name, path, args, kwargs


class ReferenceRelatedDescriptor(ManyToManyDescriptor):
    """
    Descriptor that provides access to the ReferenceRelatedManager.
    Inherits from ManyToManyDescriptor but returns our custom manager.
    """

    def __get__(self, instance, cls=None):
        if instance is None:
            return self

        # Return our custom manager instead of the default one
        return ReferenceRelatedManager(
            instance=instance,
            field=self.field,
            reverse=self.reverse,
        )

    def __set__(self, instance, value):
        raise AttributeError(
            f"Cannot set values directly on ReferenceField '{self.field.name}'. "
            "Use the manager methods: add(), set(), remove(), clear()"
        )


class ReferenceRelatedManager:
    """
    Manager for ReferenceField that queries via the source instance's
    reference FK instead of its pk.

    This allows queries to work even when the source instance is unsaved,
    as long as it has a reference attribute.
    """

    def __init__(self, instance, field, reverse=False):
        self.instance = instance
        self.field = field
        self.reverse = reverse

        # Validate that instance has reference attribute
        if not hasattr(instance, "reference"):
            raise ValueError(
                f"{type(instance).__name__} must have a 'reference' attribute "
                "to use ReferenceField"
            )

        # Get the remote field from ManyToManyField
        self.remote_field = field.remote_field
        # Type assertion: remote_field is always set for ManyToManyField
        assert self.remote_field is not None
        self.through = self.remote_field.through
        self.source_model = type(instance)

        # Get the target model (Reference)
        self.target_model = apps.get_model("activitypub", "Reference")

    def get_queryset(self):
        """
        Build queryset that filters via reference relationship.

        Instead of filtering through table by source_model_id=instance.pk,
        we filter by source_reference_id=instance.reference_id.
        """
        if not hasattr(self.instance, "reference"):
            raise ValueError(
                f"{self.source_model.__name__} instance must have a 'reference' attribute"
            )

        if self.instance.reference is None:
            # No reference set, return empty queryset
            return self.target_model.objects.none()

        # Get target reference IDs from through table
        through_qs = self.through.objects.filter(source_reference=self.instance.reference)

        target_ids = through_qs.values_list("target_reference_id", flat=True)

        return self.target_model.objects.filter(pk__in=target_ids)

    def all(self):
        """Return all related references."""
        return self.get_queryset()

    def filter(self, *args, **kwargs):
        """Filter the related references."""
        return self.get_queryset().filter(*args, **kwargs)

    def exclude(self, *args, **kwargs):
        """Exclude references matching the criteria."""
        return self.get_queryset().exclude(*args, **kwargs)

    def first(self):
        """Return the first related reference."""
        return self.get_queryset().first()

    def last(self):
        """Return the last related reference."""
        return self.get_queryset().last()

    def count(self):
        """Return the count of related references."""
        return self.get_queryset().count()

    def exists(self):
        """Return whether any related references exist."""
        return self.get_queryset().exists()

    def get(self, *args, **kwargs):
        """Get a single related reference."""
        return self.get_queryset().get(*args, **kwargs)

    def add(self, *references):
        """
        Add references to the relationship.

        Args:
            *references: Reference instances to add
        """

        if not hasattr(self.instance, "reference") or self.instance.reference is None:
            raise ValueError(
                f"Cannot add references: {self.source_model.__name__} instance "
                "must have a reference attribute set"
            )

        # Track which were actually added (not already existing)
        added_pks = set()

        for ref in references:
            _, created = self.through.objects.get_or_create(
                source_reference=self.instance.reference,
                target_reference=ref,
            )
            if created:
                added_pks.add(ref.pk)

        # Send m2m_changed signal if any were added
        if added_pks:
            m2m_changed.send(
                sender=self.through,
                instance=self.instance,
                action="post_add",
                reverse=False,
                model=self.target_model,
                pk_set=added_pks,
                using=self.through.objects.db,
            )

    def remove(self, *references):
        """
        Remove references from the relationship.

        Args:
            *references: Reference instances to remove
        """
        if not hasattr(self.instance, "reference") or self.instance.reference is None:
            raise ValueError(
                f"Cannot remove references: {self.source_model.__name__} instance "
                "must have a reference attribute set"
            )

        # Get PKs that will be removed
        removed_pks = set(
            self.through.objects.filter(
                source_reference=self.instance.reference,
                target_reference__in=references,
            ).values_list("target_reference_id", flat=True)
        )

        # Delete the relationships
        self.through.objects.filter(
            source_reference=self.instance.reference,
            target_reference__in=references,
        ).delete()

        # Send m2m_changed signal if any were removed
        if removed_pks:
            m2m_changed.send(
                sender=self.through,
                instance=self.instance,
                action="post_remove",
                reverse=False,
                model=self.target_model,
                pk_set=removed_pks,
                using=self.through.objects.db,
            )

    def clear(self):
        """Remove all references from the relationship."""
        if not hasattr(self.instance, "reference") or self.instance.reference is None:
            raise ValueError(
                f"Cannot clear references: {self.source_model.__name__} instance "
                "must have a reference attribute set"
            )

        # Get PKs that will be removed
        removed_pks = set(
            self.through.objects.filter(
                source_reference=self.instance.reference,
            ).values_list("target_reference_id", flat=True)
        )

        # Delete all relationships
        self.through.objects.filter(
            source_reference=self.instance.reference,
        ).delete()

        # Send m2m_changed signal if any were removed
        if removed_pks:
            m2m_changed.send(
                sender=self.through,
                instance=self.instance,
                action="post_clear",
                reverse=False,
                model=self.target_model,
                pk_set=removed_pks,
                using=self.through.objects.db,
            )

    def set(self, references, clear=False):
        """
        Set the references, optionally clearing existing ones first.

        Args:
            references: Iterable of Reference instances
            clear: If True, clear existing references first
        """
        if clear:
            self.clear()

        # Get existing target IDs
        existing_ids = set(
            self.through.objects.filter(source_reference=self.instance.reference).values_list(
                "target_reference_id", flat=True
            )
        )

        # Add new references
        for ref in references:
            if ref.pk not in existing_ids:
                self.add(ref)

        # Remove references not in the new set
        new_ids = {ref.pk for ref in references}
        to_remove_ids = existing_ids - new_ids
        if to_remove_ids:
            self.through.objects.filter(
                source_reference=self.instance.reference,
                target_reference_id__in=to_remove_ids,
            ).delete()

    def __iter__(self):
        """Allow iteration over related references."""
        return iter(self.get_queryset())

    def __len__(self):
        """Return the count of related references."""
        return self.count()

    def __bool__(self):
        """Return whether any related references exist."""
        return self.exists()

    def __repr__(self):
        return f"<ReferenceRelatedManager for {self.source_model.__name__}.{self.field.name}>"


class ContextProxy:
    def __init__(self, reference, context_class):
        object.__setattr__(self, "_reference", reference)
        object.__setattr__(self, "_context_class", context_class)
        object.__setattr__(self, "_instance", None)
        object.__setattr__(self, "_dirty", False)

    def _get_instance(self):
        if object.__getattribute__(self, "_instance") is None:
            reference = object.__getattribute__(self, "_reference")
            ctx_class = object.__getattribute__(self, "_context_class")
            context = reference.get_by_context(ctx_class) or ctx_class(reference=reference)
            object.__setattr__(self, "_instance", context)
        return object.__getattribute__(self, "_instance")

    def __getattr__(self, name):
        instance = self._get_instance()
        return getattr(instance, name)

    def __setattr__(self, name, value):
        setattr(self._get_instance(), name, value)
        object.__setattr__(self, "_dirty", True)

    def save(self):
        """Save the context if it's been modified"""
        if object.__getattribute__(self, "_dirty"):
            instance = object.__getattribute__(self, "_instance")
            if instance:
                instance.save()
                object.__setattr__(self, "_dirty", False)


class RelatedContextField:
    def __init__(self, context_class):
        self.context_class = context_class

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return ContextProxy(instance.reference, self.context_class)


__all__ = ("ReferenceField", "RelatedContextField")
