from rest_framework import status
from rest_framework.exceptions import APIException


class RejectedFollowRequest(Exception):
    """Raised when a follow request should be rejected due to permission checks"""

    pass


class LemmyAPIException(APIException):
    """Base exception for Lemmy API errors.

    Returns errors in Lemmy format: {"error": "error_code"}
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "unknown"
    default_code = "unknown"

    def __init__(self, detail=None, code=None):
        if detail is None:
            detail = self.default_detail
        self.detail = {"error": detail}


class PersonNotFound(LemmyAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "couldnt_find_person"


class NoIdGiven(LemmyAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "no_id_given"
