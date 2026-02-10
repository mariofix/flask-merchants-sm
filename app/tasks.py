from celery import shared_task
from flask import current_app
from flask_mailman import EmailMultiAlternatives
from flask_security.mail_util import MailUtil

from .extensions import mail


class MyMailUtil(MailUtil):
    def send_mail(self, template, subject, recipient, sender, body, html, **kwargs):
        kwargs["user"] = kwargs["user"].__dict__
        send_flask_mail.delay(
            subject=subject,
            from_email=sender,
            to=[recipient],
            body=body,
            html=html,
        )  # type: ignore


@shared_task(bind=True, ignore_result=False)
def send_flask_mail(*args, **kwargs):
    with current_app.app_context():
        with mail.get_connection() as connection:
            html = kwargs.pop("html", None)
            msg = EmailMultiAlternatives(**kwargs, connection=connection)
            if html:
                msg.attach_alternative(html, "text/html")
                msg.send()
