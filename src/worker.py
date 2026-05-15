"""RQ worker entrypoint for durable indexing jobs."""

from __future__ import annotations

import logging

from redis import Redis
from rq import Queue, Worker

from api.dependencies import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = Queue(settings.indexing_queue_name, connection=redis)
    worker = Worker([queue], connection=redis)
    worker.work()


if __name__ == "__main__":
    main()
