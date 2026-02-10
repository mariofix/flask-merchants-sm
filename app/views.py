from flask_admin.contrib.sqla import ModelView

from flask_merchants.views import AppAdmin


class ProductView(AppAdmin, ModelView):
    name = "Product"
    name_plural = "Products"
    column_list = ["slug", "active", "currency", "price", "extra_attrs"]
