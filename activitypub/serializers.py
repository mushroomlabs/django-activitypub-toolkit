from rest_framework import serializers


class NodeInfoSoftwareSerializer(serializers.Serializer):
    name = serializers.CharField()
    version = serializers.CharField(default="unknown")


class NodeInfoSerializer(serializers.Serializer):
    version = serializers.CharField()
    software = NodeInfoSoftwareSerializer()
    protocols = serializers.ListSerializer(child=serializers.CharField())
