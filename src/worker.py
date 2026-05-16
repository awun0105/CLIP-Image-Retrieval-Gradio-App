"""RQ worker entrypoint for durable indexing jobs."""

from __future__ import annotations

from redis import Redis
from rq import Queue, Worker

from api.dependencies import get_settings
from core.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    redis = Redis.from_url(settings.redis_url)
    queue = Queue(settings.indexing_queue_name, connection=redis)
    worker = Worker([queue], connection=redis)
    worker.work()


if __name__ == "__main__":
    main()
