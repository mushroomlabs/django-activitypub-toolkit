from .linked_data import ContextModelSerializer


class CollectionContextSerializer(ContextModelSerializer):
    def _serialize_field(self, field_name, value):
        if field_name in ["items", "ordered_items"]:
            return [{"@id": ci.item.uri} for ci in value]

        if field_name == "total_items":
            # totalItems in AS2 context expects xsd:nonNegativeInteger
            return [
                {"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#nonNegativeInteger"}
            ]

        return super()._serialize_field(field_name, value)


__all__ = ("CollectionContextSerializer",)
