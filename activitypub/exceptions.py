class InvalidSignature(Exception):
    pass


class UnprocessableJsonLd(Exception):
    pass


class MessageProcessorException(Exception):
    pass


class DropMessage(MessageProcessorException):
    pass
