from ..core import CoreProvider
import uuid
import secrets


class CasinoProvider(CoreProvider):
    name = "casino-provider"

    def create(self, payload: dict):

        codigo = payload.get("merchants_token", None)
        if not codigo:
            print("codigo no existe")
        random_uuid = str(uuid.uuid4())
        random_index = secrets.choice([1, 2, 3])
        salida = {
            "transaction": f"SM_{random_uuid.split('-')[random_index].upper()}{random_index}",
        }
        return salida

    def get(self):
        return True

    def refund(self):
        return True
