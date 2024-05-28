import time

from EventEngine import Topic, EventEngine, LOGGER

BUFFER_SIZE = 1024
EVENT_ENGINE = EventEngine(buffer_size=BUFFER_SIZE)
N = 1000000


def on_data(topic, data, *arg, **kwargs):
    pass


def init_test():
    ts = time.time()
    topic = Topic('realtime.APPL.TradeData')
    data = {'dtype': 'TradeData', 'ticker': 'APPL', 'price': 95., 'volume': 200}
    EVENT_ENGINE.register_handler(topic=topic, handler=on_data)

    for _ in range(N):
        EVENT_ENGINE.put(topic=topic, data=data)

    LOGGER.info(f'All {N:,d} task done, time cost {time.time() - ts:.2f}s.')


if __name__ == '__main__':
    EVENT_ENGINE.start()
    init_test()
    EVENT_ENGINE.stop()
