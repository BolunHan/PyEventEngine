#include <iostream>
#include <functional>
#include <queue>
#include <map>
#include <thread>
#include <chrono>
#include <ctime>
#include "topic_api.cpp"

class EventHookBase {
public:
    using Handler = std::function<void(const Topic &, const std::tuple<> &, const std::map<std::string, std::string> &)>;

    EventHookBase(const Topic &topic, const std::vector<Handler> &handlers = {}) :
            topic(topic), handlers(handlers) {
        // Check if the handler is callable
        for (const auto &handler: handlers) {
            if (!handler) {
                throw std::invalid_argument("Invalid handler");
            }
        }
    }

    void operator()() {
        trigger(topic, std::tuple<>(), {});
    }

    void operator+=(const Handler &handler) {
        addHandler(handler);
    }

    void operator-=(const Handler &handler) {
        removeHandler(handler);
    }

    void trigger(const Topic &topic, const std::tuple<> &args = std::tuple<>{}, const std::map<std::string, std::string> &kwargs = {}) {
        for (const auto &handler: handlers) {
            try {
                handler(topic, args, kwargs);
            } catch (const std::exception &e) {
                std::cerr << "Exception caught: " << e.what() << std::endl;
            }
        }
    }

    void addHandler(const Handler &handler) {
        if (!handler) {
            throw std::invalid_argument("Invalid handler");
        }
        handlers.push_back(handler);
    }

    void removeHandler(const Handler &handler) {
        handlers.erase(std::remove(handlers.begin(), handlers.end(), handler), handlers.end());
    }

private:
    Topic topic;
    std::vector<Handler> handlers;
};

class EventEngineBase {
public:
    using EventHook = EventHookBase;
    using EventQueue = std::queue<std::pair<Topic, std::tuple<>>>;
    using EventMap = std::map<Topic, EventHook>;

    EventEngineBase(int maxSize = 0) :
            max_size(maxSize), active(false), event_hooks(), engine() {}

    void start() {
        if (active) {
            std::cerr << "EventEngine already started!" << std::endl;
            return;
        }

        active = true;
        engine = std::thread(&EventEngineBase::run, this);
    }

    void stop() {
        if (!active) {
            std::cerr << "EventEngine already stopped!" << std::endl;
            return;
        }

        active = false;
        engine.join();
    }

    void put(const Topic &topic) {
        publish(topic);
    }

    void publish(const Topic &topic) {
        event_queue.push(std::make_pair(topic, std::tuple<>()));
    }

    void registerHook(const EventHook &hook) {
        const auto &topic = hook.getTopic();
        if (event_hooks.find(topic) != event_hooks.end()) {
            auto &existingHook = event_hooks[topic];
            for (const auto &handler: hook.getHandlers()) {
                existingHook.addHandler(handler);
            }
        } else {
            event_hooks[topic] = hook;
        }
    }

    void unregisterHook(const Topic &topic) {
        event_hooks.erase(topic);
    }

    void registerHandler(const Topic &topic, const EventHook::Handler &handler) {
        if (event_hooks.find(topic) != event_hooks.end()) {
            event_hooks[topic].addHandler(handler);
        } else {
            event_hooks[topic] = EventHook(topic, {handler});
        }
    }

    void unregisterHandler(const Topic &topic, const EventHook::Handler &handler) {
        if (event_hooks.find(topic) != event_hooks.end()) {
            event_hooks[topic].removeHandler(handler);
        }
    }

    void setMaxSize(int maxSize) {
        max_size = maxSize;
    }

private:
    int max_size;
    bool active;
    EventQueue event_queue;
    EventMap event_hooks;
    std::thread engine;

    void run() {
        while (active) {
            if (!event_queue.empty()) {
                const auto &event = event_queue.front();
                const auto &topic = event.first;
                const auto &args = event.second;

                if (event_hooks.find(topic) != event_hooks.end()) {
                    event_hooks[topic].trigger(topic, args);
                }

                event_queue.pop();
            } else {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
        }
    }
};

int main() {
    // Test case
    EventEngineBase engine;

    Topic topic1("topic1");
    EventHookBase::Handler handler1 = [](const Topic &, const std::tuple<> &, const std::map<std::string, std::string> &) {
        std::cout << "Handler 1 called" << std::endl;
    };

    EventHookBase::Handler handler2 = [](const Topic &, const std::tuple<> &, const std::map<std::string, std::string> &) {
        std::cout << "Handler 2 called" << std::endl;
    };

    EventHookBase::Handler handler3 = [](const Topic &, const std::tuple<> &, const std::map<std::string, std::string> &) {
        std::cout << "Handler 3 called" << std::endl;
    };

    EventHookBase hook1(topic1, {handler1, handler2});
    EventHookBase hook2(topic1, {handler3});

    engine.registerHook(hook1);
    engine.registerHook(hook2);

    engine.start();

    engine.put(topic1);

    std::this_thread::sleep_for(std::chrono::seconds(1));

    engine.unregisterHook(topic1);
    engine.put(topic1);

    std::this_thread::sleep_for(std::chrono::seconds(1));

    engine.stop();

    return 0;
}
