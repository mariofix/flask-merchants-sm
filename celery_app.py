import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

import sentry_sdk  # noqa: E402
from sentry_sdk.integrations.flask import FlaskIntegration  # noqa: E402

dsn = os.getenv("FLASK_SENTRY_DSN", None)
if dsn:
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for Tracing.
        # We recommend adjusting this value in production,
        traces_sample_rate=0.2,
    )
app = create_app()
celery_app = app.extensions["celery"]
