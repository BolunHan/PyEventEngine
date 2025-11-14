"""
A small Python-native MQ implementation for benchmarking.
- Uses a dict mapping str topic -> queue.Queue
- Exact topic matching only

Includes a simple benchmark harness (configurable via command-line args):
- num_topics: how many distinct string topics
- messages_per_topic: how many messages to publish per topic
- producer_threads: number of concurrent publisher threads
- consumer_threads_per_topic: number of consumer threads per topic
- msg_size: payload size in bytes (string length)

Behavior:
- Topics are created on first use.
- Producers publish messages round-robin across topics.
- Consumers pull from their topic queue until they've consumed the expected number
  of messages for that topic, then exit.

This module is intentionally minimal and focused on being a benchmark target.
"""

from __future__ import annotations

import argparse
import threading
import time
import queue
import string
import random
from typing import Dict, Any, Optional, List


class PyMQ:
    """A tiny MQ using exact-topic matching backed by queue.Queue instances.

    API:
    - publish(topic: str, msg: Any)
    - subscribe(topic: str) -> queue.Queue (consumer receives messages by calling get())
    - create_topic(topic: str)
    - topic_count()
    """

    def __init__(self) -> None:
        self._topics: Dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def create_topic(self, topic: str, maxsize: int = 0) -> queue.Queue:
        """Create a topic queue (no-op if exists). Returns the queue for consumers.
        maxsize follows queue.Queue semantics (0 means infinite).
        """
        with self._lock:
            q = self._topics.get(topic)
            if q is None:
                q = queue.Queue(maxsize=maxsize)
                self._topics[topic] = q
            return q

    def subscribe(self, topic: str) -> queue.Queue:
        """Return the queue associated with topic. Creates topic if missing."""
        return self.create_topic(topic)

    def publish(self, topic: str, msg: Any, block: bool = True, timeout: Optional[float] = None) -> None:
        """Publish a message to a given topic (exact match)."""
        q = self.create_topic(topic)
        q.put(msg, block=block, timeout=timeout)

    def topic_count(self) -> int:
        with self._lock:
            return len(self._topics)


def _make_payload(size: int) -> str:
    # generate a reproducible-ish short string payload
    if size <= 0:
        return ""
    # use letters to avoid non-text bytes; faster than random.choice per char
    return ("x" * size)


def run_benchmark(
    num_topics: int = 10,
    messages_per_topic: int = 100_000,
    producer_threads: int = 2,
    consumer_threads_per_topic: int = 1,
    msg_size: int = 32,
) -> Dict[str, Any]:
    """Run a simple publish/consume benchmark and return metrics."""
    mq = PyMQ()

    # prepare topics
    topics = [f"topic_{i}" for i in range(num_topics)]
    for t in topics:
        mq.create_topic(t)

    total_messages = num_topics * messages_per_topic
    payload = _make_payload(msg_size)

    # For signaling
    start_event = threading.Event()
    produced_counter = 0
    produced_counter_lock = threading.Lock()

    # Consumers track how many messages they need to consume per topic
    per_topic_target = messages_per_topic
    consumers_done = threading.Event()

    # Data structures to track consumption
    consumed_counts = {t: 0 for t in topics}
    consumed_locks = {t: threading.Lock() for t in topics}

    # Consumer worker
    def consumer_worker(topic: str, target: int):
        q = mq.subscribe(topic)
        count = 0
        # wait for start
        start_event.wait()
        while count < target:
            try:
                _ = q.get(timeout=5.0)
            except queue.Empty:
                # if producers are done but queue empty, break to avoid hanging
                continue
            count += 1
            if count % 10000 == 0:
                # occasionally yield
                time.sleep(0)
        with consumed_locks[topic]:
            consumed_counts[topic] += count

    # Producer worker: publish messages round-robin across topics
    def producer_worker(producer_id: int, messages_to_publish: int):
        nonlocal produced_counter
        start_event.wait()
        # simple round-robin index
        topic_idx = producer_id % num_topics
        for i in range(messages_to_publish):
            topic = topics[topic_idx]
            mq.publish(topic, payload)
            topic_idx += 1
            if topic_idx >= num_topics:
                topic_idx = 0
            if i and (i % 10000 == 0):
                time.sleep(0)
            # update produced counter occasionally
            if (i + 1) % 1000 == 0:
                with produced_counter_lock:
                    produced_counter += 1000
        # add remaining
        with produced_counter_lock:
            produced_counter += messages_to_publish % 1000

    # Start consumer threads
    consumer_threads: List[threading.Thread] = []
    for t in topics:
        for _ in range(consumer_threads_per_topic):
            thr = threading.Thread(target=consumer_worker, args=(t, per_topic_target), daemon=True)
            thr.start()
            consumer_threads.append(thr)

    # Start producer threads
    producer_threads_list: List[threading.Thread] = []
    # split messages among producers roughly equally
    base = messages_per_topic // producer_threads
    extra = messages_per_topic % producer_threads
    # Each producer will publish messages_per_topic messages for each topic divided by number of producers,
    # but we want total messages = num_topics * messages_per_topic. For simplicity, assign each producer
    # total_messages = (total_messages // producer_threads) +- 1.
    total_messages_for_producers = total_messages
    per_producer_base = total_messages_for_producers // producer_threads
    remainder = total_messages_for_producers % producer_threads
    for pid in range(producer_threads):
        assign = per_producer_base + (1 if pid < remainder else 0)
        thr = threading.Thread(target=producer_worker, args=(pid, assign), daemon=True)
        thr.start()
        producer_threads_list.append(thr)

    # Run benchmark
    t0 = time.perf_counter()
    start_event.set()

    # Wait for producers to finish
    for thr in producer_threads_list:
        thr.join()
    t_after_publish = time.perf_counter()

    # Wait for all consumers to consume expected counts
    for thr in consumer_threads:
        thr.join()
    t_after_consume = time.perf_counter()

    publish_time = t_after_publish - t0
    end_to_end_time = t_after_consume - t0

    metrics = {
        "num_topics": num_topics,
        "messages_per_topic": messages_per_topic,
        "total_messages": total_messages,
        "producer_threads": producer_threads,
        "consumer_threads_per_topic": consumer_threads_per_topic,
        "msg_size": msg_size,
        "publish_seconds": publish_time,
        "end_to_end_seconds": end_to_end_time,
        "publish_msgs_per_sec": total_messages / publish_time if publish_time > 0 else None,
        "end_to_end_msgs_per_sec": total_messages / end_to_end_time if end_to_end_time > 0 else None,
    }

    return metrics


def main():
    parser = argparse.ArgumentParser(description="Benchmark Python-native MQ (exact-topic matching)")
    parser.add_argument("--num-topics", type=int, default=10)
    parser.add_argument("--messages-per-topic", type=int, default=100_000)
    parser.add_argument("--producer-threads", type=int, default=2)
    parser.add_argument("--consumer-threads-per-topic", type=int, default=1)
    parser.add_argument("--msg-size", type=int, default=32)
    args = parser.parse_args()

    print("Running py native MQ benchmark with:")
    print(f"  topics={args.num_topics}, messages_per_topic={args.messages_per_topic}, producers={args.producer_threads}, consumers_per_topic={args.consumer_threads_per_topic}, msg_size={args.msg_size}")

    start = time.time()
    metrics = run_benchmark(
        num_topics=args.num_topics,
        messages_per_topic=args.messages_per_topic,
        producer_threads=args.producer_threads,
        consumer_threads_per_topic=args.consumer_threads_per_topic,
        msg_size=args.msg_size,
    )
    elapsed = time.time() - start

    print("Benchmark results:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print(f"Wall clock (including setup): {elapsed:.3f}s")


if __name__ == "__main__":
    main()

