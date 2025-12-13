"""
Custom lookup classes for ReferenceField QuerySet filtering.

These lookups enable filtering on ReferenceField using Django's standard QuerySet API:
    Model.objects.filter(field=ref)
    Model.objects.filter(field__in=[ref1, ref2])
    Model.objects.filter(field__isnull=True)

The lookups work by generating subqueries through the through table, since
ReferenceField uses a non-standard M2M structure where both source and through
tables have FKs to the Reference model.
"""

from django.db.models.lookups import Lookup


class ReferenceFieldLookup(Lookup):
    """
    Base class for ReferenceField lookups.

    Provides common functionality for generating subqueries through the
    ReferenceField's through table.
    """

    def get_prep_lookup(self):
        """Prepare the lookup value."""
        if hasattr(self.rhs, "_prepare"):
            return self.rhs._prepare(self.lhs.output_field)
        if hasattr(self.lhs.output_field, "get_prep_value"):
            return self.lhs.output_field.get_prep_value(self.rhs)
        return self.rhs


class ReferenceFieldExact(ReferenceFieldLookup):
    """
    Implements the 'exact' lookup for ReferenceField.

    Transforms:
        Model.objects.filter(field=ref)
    Into:
        Model.objects.filter(
            reference_id__in=Subquery(
                Through.objects.filter(target_reference=ref)
                .values_list('source_reference_id', flat=True)
            )
        )
    """

    lookup_name = "exact"

    def as_sql(self, compiler, connection):
        """
        Generate SQL for exact match lookup.

        SQL pattern:
            WHERE source.reference_id IN (
                SELECT source_reference_id
                FROM through_table
                WHERE target_reference_id = %s
            )
        """
        field = self.lhs.output_field
        through_model = field.remote_field.through
        source_model = field.model

        # Get table and column names
        through_table = through_model._meta.db_table
        source_table = source_model._meta.db_table
        reference_column = source_model._meta.get_field("reference").column

        # Process the RHS (the Reference we're filtering by)
        rhs_sql, rhs_params = self.process_rhs(compiler, connection)

        # Build the subquery SQL
        sql = (
            f'"{source_table}"."{reference_column}" IN '
            f'(SELECT "source_reference_id" FROM "{through_table}" '
            f'WHERE "target_reference_id" = {rhs_sql})'
        )

        return sql, rhs_params


class ReferenceFieldIn(ReferenceFieldLookup):
    """
    Implements the 'in' lookup for ReferenceField.

    Transforms:
        Model.objects.filter(field__in=[ref1, ref2])
    Into:
        Model.objects.filter(
            reference_id__in=Subquery(
                Through.objects.filter(target_reference__in=[ref1, ref2])
                .values_list('source_reference_id', flat=True)
            )
        )
    """

    lookup_name = "in"

    def as_sql(self, compiler, connection):
        """
        Generate SQL for 'in' lookup.

        SQL pattern:
            WHERE source.reference_id IN (
                SELECT source_reference_id
                FROM through_table
                WHERE target_reference_id IN (%s, %s, ...)
            )
        """
        field = self.lhs.output_field
        through_model = field.remote_field.through
        source_model = field.model

        # Get table and column names
        through_table = through_model._meta.db_table
        source_table = source_model._meta.db_table
        reference_column = source_model._meta.get_field("reference").column

        # Process the RHS (list of References) and convert to PKs
        rhs_value = self.rhs
        if hasattr(rhs_value, "__iter__") and not isinstance(rhs_value, str):
            # Convert Reference objects to their PKs
            pk_list = [obj.pk if hasattr(obj, "pk") else obj for obj in rhs_value]
        else:
            pk_list = [rhs_value]

        # Build placeholders for SQL
        placeholders = ", ".join(["%s"] * len(pk_list))

        # Build the subquery SQL
        sql = (
            f'"{source_table}"."{reference_column}" IN '
            f'(SELECT "source_reference_id" FROM "{through_table}" '
            f'WHERE "target_reference_id" IN ({placeholders}))'
        )

        return sql, pk_list


class ReferenceFieldIsNull(ReferenceFieldLookup):
    """
    Implements the 'isnull' lookup for ReferenceField.

    Transforms:
        Model.objects.filter(field__isnull=True)
    Into:
        Model.objects.filter(
            ~Exists(
                Through.objects.filter(source_reference_id=OuterRef('reference_id'))
            )
        )
    """

    lookup_name = "isnull"

    def as_sql(self, compiler, connection):
        """
        Generate SQL for isnull lookup.

        SQL pattern for isnull=True:
            WHERE NOT EXISTS (
                SELECT 1 FROM through_table
                WHERE source_reference_id = source.reference_id
            )

        SQL pattern for isnull=False:
            WHERE EXISTS (
                SELECT 1 FROM through_table
                WHERE source_reference_id = source.reference_id
            )
        """
        field = self.lhs.output_field
        through_model = field.remote_field.through
        source_model = field.model

        # Get table and column names
        through_table = through_model._meta.db_table
        source_table = source_model._meta.db_table
        reference_column = source_model._meta.get_field("reference").column

        # Determine if we want NULL or NOT NULL
        is_null = self.rhs  # True for isnull=True, False for isnull=False

        if is_null:
            # isnull=True: no relationships exist
            sql = (
                f'NOT EXISTS (SELECT 1 FROM "{through_table}" '
                f'WHERE "source_reference_id" = "{source_table}"."{reference_column}")'
            )
        else:
            # isnull=False: at least one relationship exists
            sql = (
                f'EXISTS (SELECT 1 FROM "{through_table}" '
                f'WHERE "source_reference_id" = "{source_table}"."{reference_column}")'
            )

        return sql, []
