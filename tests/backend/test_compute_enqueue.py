"""enqueue_compute_task：broker 配置与 send_task 行为。"""

import uuid
from unittest.mock import patch

from backend.workers.compute_enqueue import enqueue_compute_task


def test_enqueue_without_broker_does_not_send():
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.celery_broker_url = None

        enqueue_compute_task(uuid.uuid4())


def test_enqueue_with_broker_calls_send_task():
    task_id = uuid.uuid4()
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        with patch("backend.workers.celery_app.celery_app.send_task") as send_task:
            enqueue_compute_task(task_id)
            send_task.assert_called_once()
            args, kwargs = send_task.call_args
            assert args[0] == "tasks.execute_compute"
            assert kwargs["args"] == [str(task_id)]
            assert kwargs["queue"] == "compute"
