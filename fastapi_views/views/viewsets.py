from abc import ABC

from .api import (
    AsyncCreateAPIView,
    AsyncDestroyAPIView,
    AsyncListAPIView,
    AsyncRetrieveAPIView,
    AsyncUpdateAPIView,
    CreateAPIView,
    DestroyAPIView,
    ListAPIView,
    RetrieveAPIView,
    UpdateAPIView,
)


class ReadOnlyAPIViewSet(ListAPIView, RetrieveAPIView, ABC):
    """ReadOnlyAPIViewSet"""


class AsyncReadOnlyAPIViewSet(AsyncListAPIView, AsyncRetrieveAPIView, ABC):
    """AsyncReadOnlyAPIViewSet"""


class ListCreateAPIViewSet(ListAPIView, CreateAPIView, ABC):
    """ListCreateAPIViewSet"""


class AsyncListCreateAPIViewSet(AsyncListAPIView, AsyncCreateAPIView, ABC):
    """AsyncListCreateAPIViewSet"""


class RetrieveUpdateAPIViewSet(RetrieveAPIView, UpdateAPIView, ABC):
    """RetrieveUpdateAPIViewSet"""


class AsyncRetrieveUpdateAPIViewSet(AsyncRetrieveAPIView, AsyncUpdateAPIView, ABC):
    """AsyncRetrieveUpdateAPIViewSet"""


class RetrieveUpdateDestroyAPIViewSet(
    RetrieveAPIView, UpdateAPIView, DestroyAPIView, ABC
):
    """RetrieveUpdateDestroyAPIViewSet"""


class AsyncRetrieveUpdateDestroyAPIViewSet(
    AsyncRetrieveAPIView, AsyncUpdateAPIView, AsyncDestroyAPIView, ABC
):
    """AsyncRetrieveUpdateDestroyAPIViewSet"""


class ListRetrieveUpdateDestroyAPIViewSet(
    ListAPIView, RetrieveAPIView, UpdateAPIView, DestroyAPIView, ABC
):
    """ListRetrieveUpdateDestroyAPIViewSet"""


class AsyncListRetrieveUpdateDestroyAPIViewSet(
    AsyncListAPIView, AsyncRetrieveAPIView, AsyncUpdateAPIView, AsyncDestroyAPIView, ABC
):
    """AsyncListRetrieveUpdateDestroyAPIViewSet"""


class ListCreateDestroyAPIViewSet(ListAPIView, CreateAPIView, DestroyAPIView, ABC):
    """ListCreateDestroyAPIViewSet"""


class AsyncListCreateDestroyAPIViewSet(
    AsyncListAPIView, AsyncCreateAPIView, AsyncDestroyAPIView, ABC
):
    """AsyncListCreateDestroyAPIViewSet"""


class APIViewSet(
    ListAPIView, CreateAPIView, RetrieveAPIView, UpdateAPIView, DestroyAPIView, ABC
):
    """APIViewSet"""


class AsyncAPIViewSet(
    AsyncListAPIView,
    AsyncCreateAPIView,
    AsyncRetrieveAPIView,
    AsyncUpdateAPIView,
    AsyncDestroyAPIView,
    ABC,
):
    """AsyncAPIViewSet"""
