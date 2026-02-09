class InvalidSignature(Exception):
    pass


class UnprocessableJsonLd(Exception):
    pass


class InvalidDomainError(Exception):
    pass


class UnauthenticatedPublisher(Exception):
    pass


class DocumentPublishingError(Exception):
    pass


class DocumentResolutionError(Exception):
    pass


class DocumentValidationError(Exception):
    pass


class ReferenceRedirect(Exception):
    def __init__(self, message, redirect_uri=None):
        super().__init__(self, message)
        self.redirect_uri = redirect_uri


class DropMessage(Exception):
    pass


class RejectedFollowRequest(Exception):
    pass
