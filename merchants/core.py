from abc import ABC, abstractmethod
from typing import Any

import requests


class CoreProvider(ABC):
    name: str = "core-provider"
    client: Any = requests.Session

    @abstractmethod
    def create(self):
        raise NotImplementedError("You must implement your own create()")

    @abstractmethod
    def get(self):
        raise NotImplementedError("You must implement your own get()")

    @abstractmethod
    def refund(self):
        raise NotImplementedError("You must implement your own refund()")
