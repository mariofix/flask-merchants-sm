from ..core import CoreProvider


class CashProvider(CoreProvider):
    name = "cash-provider"

    def create(self):
        return {"url": "url", "transaction": "tr_1234"}
