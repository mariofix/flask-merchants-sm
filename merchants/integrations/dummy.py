from ..core import CoreProvider


class DummyProvider(CoreProvider):
    name = "dummy-provider"

    def create(self):
        return {"url": "url", "transaction": "tr_1234"}
