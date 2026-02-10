from flask import Blueprint, render_template
from flask_admin import BaseView, expose


class StoreFront(BaseView):
    @expose("/")
    def get(self):
        return self.render("store/storefront.html")


class StoreProductView(BaseView):
    @expose("/")
    def get(self):
        return self.render("store/product.html")


class StoreCheckoutView(BaseView):
    @expose("/")
    def get(self):
        return self.render("store/checkout.html")


bp = Blueprint("store", __name__)


@bp.get("/")
def storefront():
    return render_template("store/storefront.html")


@bp.get("/product/<slug>")
def product(slug):
    return render_template("store/product.html", slug=slug)


@bp.get("/checkout/")
def checkout():
    return render_template("store/checkout.html")
