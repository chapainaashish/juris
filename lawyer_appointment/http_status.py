from rest_framework import generics, permissions, status
from rest_framework.exceptions import APIException


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict detected."
    default_code = "conflict"
