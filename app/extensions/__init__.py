from flask_babel import Babel
from flask_mailman import Mail
from flask_wtf import CSRFProtect

from flask_merchants import FlaskMerchants
from merchants.providers.khipu import KhipuProvider
from merchants.providers.dummy import DummyProvider

babel = Babel()
mail = Mail()
flask_merchants = FlaskMerchants(providers=[DummyProvider(), KhipuProvider(api_key="api_")])
csrf = CSRFProtect()
