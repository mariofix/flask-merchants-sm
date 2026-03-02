import logging

from celery import Celery, Task
from celery.signals import task_failure, task_postrun, task_prerun, task_retry
from flask import Flask

celery_log = logging.getLogger("sm.celery")


# ---------------------------------------------------------------------------
# Celery task signal handlers → sm.celery logger
# ---------------------------------------------------------------------------

@task_prerun.connect
def _task_prerun(task_id: str, task: Task, args: tuple, kwargs: dict, **extra: object) -> None:
    celery_log.info("task_started: task=%s id=%s", task.name, task_id)


@task_postrun.connect
def _task_postrun(task_id: str, task: Task, args: tuple, kwargs: dict, retval: object, state: str, **extra: object) -> None:
    celery_log.info("task_finished: task=%s id=%s state=%s", task.name, task_id, state)


@task_failure.connect
def _task_failure(task_id: str, exception: Exception, traceback: object, sender: Task, **extra: object) -> None:
    celery_log.error(
        "task_failed: task=%s id=%s error=%r",
        sender.name,
        task_id,
        exception,
        exc_info=(type(exception), exception, traceback),
    )


@task_retry.connect
def _task_retry(request: object, reason: object, einfo: object, **extra: object) -> None:
    # Log at ERROR so connection problems are picked up by Sentry
    celery_log.error(
        "task_retry: task=%s id=%s reason=%r",
        getattr(request, "task", None),
        getattr(request, "id", None),
        str(reason),
    )


# ---------------------------------------------------------------------------
# App factory integration
# ---------------------------------------------------------------------------

def celery_init_app(app: Flask):
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app
