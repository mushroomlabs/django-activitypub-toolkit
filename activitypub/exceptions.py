class InvalidSignature(Exception):
    pass


class UnprocessableJsonLd(Exception):
    pass


class InvalidDomainError(Exception):
    pass


class DocumentResolutionError(Exception):
    pass


class ReferenceRedirect(Exception):
    def __init__(self, message, location=None):
        super().__init__(self, message)
        self.location = location


class DropMessage(Exception):
    pass
