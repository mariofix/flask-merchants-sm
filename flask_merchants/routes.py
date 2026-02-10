from flask import Blueprint, render_template

blueprint = Blueprint("merchants", __name__, template_folder="templates", static_folder="static")


@blueprint.get("/")
def merchants_home():
    return render_template("merchants/home.html")
