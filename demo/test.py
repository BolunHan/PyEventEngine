import time

from event_engine import Topic, PatternTopic, EventEngine, LOGGER
from types import SimpleNamespace


class _TopicSet(object):
    on_order = Topic('on_order')
    on_report = Topic('on_report')

    launch_order = PatternTopic('launch_order.{ticker}')
    cancel_order = PatternTopic('cancel_order.{ticker}')
    realtime = PatternTopic('realtime.{ticker}.{dtype}')

    @classmethod
    def push(cls, market_data):
        return cls.realtime(ticker=market_data['ticker'], dtype=market_data['dtype'])

    @classmethod
    def parse(cls, topic: Topic) -> SimpleNamespace:
        try:
            _ = topic.value.split('.')

            action = _.pop(0)
            if action in ['open', 'close']:
                dtype = None
            else:
                dtype = _.pop(-1)
            ticker = '.'.join(_)

            p = SimpleNamespace(
                action=action,
                dtype=dtype,
                ticker=ticker
            )
            return p
        except Exception as _:
            raise ValueError(f'Invalid topic {topic}')


EVENT_ENGINE = EventEngine()
TOPIC = _TopicSet


class Strategy(object):
    def __init__(self, ticker: str):
        self.ticker = ticker

    def on_data(self, market_data, **kwargs):
        topic = kwargs.pop('topic')
        LOGGER.info(f'Strategy.on_data triggered market_data={market_data}, topic={topic}, kwargs={kwargs}')

        if market_data['price'] > 100:
            self.launch_order(order={'ticker': self.ticker, 'volume': 200, 'price': 100})

    def on_order(self, order, **kwargs):
        topic = kwargs.pop('topic')
        LOGGER.info(f'Strategy.on_order triggered order={order}, topic={topic}, kwargs={kwargs}')

    def on_report(self, report, **kwargs):
        topic = kwargs.pop('topic')
        LOGGER.info(f'Strategy.on_report triggered report={report}, topic={topic}, kwargs={kwargs}')

    def launch_order(self, order):
        LOGGER.info(f'Strategy.launch order={order}')
        EVENT_ENGINE.put(topic=TOPIC.launch_order(ticker=self.ticker), order=order)

    def register(self):
        EVENT_ENGINE.register_handler(topic=TOPIC.realtime(ticker=self.ticker, dtype='TradeData'), handler=self.on_data)
        EVENT_ENGINE.register_handler(topic=TOPIC.on_order, handler=self.on_order)
        EVENT_ENGINE.register_handler(topic=TOPIC.on_report, handler=self.on_report)


class SimMatch(object):
    def __init__(self, ticker):
        self.ticker = ticker

    def on_order(self, order, **kwargs):
        topic = kwargs.pop('topic')
        LOGGER.info(f'SimMatch.on_order triggered order={order}, topic={topic}, kwargs={kwargs}')
        self.order_filled(order=order)

    def order_filled(self, order):
        report = {'ticker': self.ticker, 'price': order['price'], 'filled_volume': order['volume']}
        LOGGER.info(f'SimMatch fully filled order {order}, reports {report}')
        EVENT_ENGINE.put(topic=TOPIC.on_report, report=report)

    def register(self):
        EVENT_ENGINE.register_handler(topic=TOPIC.launch_order(ticker=self.ticker), handler=self.on_order)


def init_test_case():
    strategy = Strategy(ticker='APPL')
    sim_match = SimMatch(ticker='APPL')

    strategy.register()
    sim_match.register()
    history = [
        {'dtype': 'TradeData', 'ticker': 'APPL', 'price': 95., 'volume': 200},  # show logs
        {'dtype': 'TradeData', 'ticker': 'TSLA', 'price': 289., 'volume': 200},  # should NOT show logs
        {'dtype': 'TickData', 'ticker': 'APPL', 'last_price': 101.},  # should NOT show logs
        {'dtype': 'TradeData', 'ticker': 'APPL', 'price': 102., 'volume': 100},  # show logs and trigger orders
        {'dtype': 'TradeData', 'ticker': 'APPL', 'price': 95, 'volume': 200},
    ]

    for _, market_data in enumerate(history, start=1):
        EVENT_ENGINE.put(topic=TOPIC.push(market_data), market_data=market_data)
        LOGGER.info(f'task {_} / {len(history)}...')
        time.sleep(1)


if __name__ == '__main__':
    EVENT_ENGINE.start()
    init_test_case()
    EVENT_ENGINE.stop()
