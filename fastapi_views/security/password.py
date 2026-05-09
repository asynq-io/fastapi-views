from __future__ import annotations

import base64
import secrets
from abc import ABC, abstractmethod

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class HashProvider(ABC):
    @abstractmethod
    def hash(self, password: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify(self, password: str, hashed: str) -> bool:
        raise NotImplementedError


class ScryptHashProvider(HashProvider):
    def __init__(
        self,
        *,
        n: int = 2**14,
        r: int = 8,
        p: int = 1,
        length: int = 32,
    ) -> None:
        self.n = n
        self.r = r
        self.p = p
        self.length = length

    def _kdf(self, salt: bytes) -> Scrypt:
        return Scrypt(salt=salt, length=self.length, n=self.n, r=self.r, p=self.p)

    def hash(self, password: str) -> str:
        """Hash a password.

        Returns a string in the format ``<salt>$<hash>`` where both
        components are base64-encoded.
        """
        salt = secrets.token_bytes(16)
        derived = self._kdf(salt).derive(password.encode())
        salt_b64 = base64.b64encode(salt).decode()
        hash_b64 = base64.b64encode(derived).decode()
        return f"{salt_b64}${hash_b64}"

    def verify(self, password: str, hashed: str) -> bool:
        """Verify a password against a hash produced by :meth:`hash`."""
        salt_b64, _, hash_b64 = hashed.partition("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        try:
            self._kdf(salt).verify(password.encode(), expected)
        except InvalidKey:
            return False
        return True
