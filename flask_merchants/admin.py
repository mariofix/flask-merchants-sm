from flask_admin import Admin
from flask_admin.theme import Bootstrap4Theme

from .views import MerchantsIndex

admin = Admin(
    name="merchants_admin",
    theme=Bootstrap4Theme(swatch="pulse", fluid=True),
    index_view=MerchantsIndex(),
    endpoint="merchants_admin",
)
