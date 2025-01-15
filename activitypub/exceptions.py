class InvalidSignature(Exception):
    pass


class UnprocessableJsonLd(Exception):
    pass


class MessageAdapterException(Exception):
    pass


class DropMessage(MessageAdapterException):
    pass
