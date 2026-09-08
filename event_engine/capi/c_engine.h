#ifndef C_EVENTENGINE_ENGINE_H
#define C_EVENTENGINE_ENGINE_H

#if defined(__linux__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE
#endif

#include <math.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <string.h>

#if defined(__linux__)
#include <pthread.h>
#include <sched.h>
#elif defined(_WIN32)
#include <windows.h>
#endif

#include <cbase/allocator_protocol/c_allocator_protocol.h>
#include <event_engine/capi/c_event.h>
#include <event_engine/capi/c_mqueue.h>
#include <event_engine/capi/c_ret_code.h>
#include <event_engine/capi/c_topic.h>

// ========== Constants ==========

/* CPU index the engine loop thread is pinned to. -1 disables affinity.
   Override at build time with: EE_LOOP_CPU=2 make build */
#ifndef EE_LOOP_CPU
#define EE_LOOP_CPU 0
#endif

// ========== Structs ==========

typedef struct evt_engine_task {
    evt_topic*          topic;    // timer topic
    evt_message_payload payload;  // embedded payload for fast access
} evt_engine_task;

typedef struct evt_engine_timer_ctx {
    /* Linked-list node. The list is kept sorted by next_due ascending, so the
       head is always the next timer ctx to tick. One ctx exists per registered
       interval; every task in the ctx fires together on each tick. */
    struct evt_engine_timer_ctx* next;
    /* Firing switch for this ctx's tasks — there is no per-task gating.
       Registering (re)arms the ctx, so any registration reactivates a paused
       timer; c_evt_engine_set_timer_active pauses/resumes every ctx without
       releasing tasks. */
    atomic_bool      active;
    double           interval_seconds;  // tick interval shared by all tasks in this ctx
    double           next_due;          // next tick timestamp (aligned to interval boundaries)
    size_t           capacity;          // allocated task buffer capacity
    size_t           n_task;            // registered task count in this ctx
    evt_engine_task* task;              // OWNED — contiguous task buffer (registration order)
} evt_engine_timer_ctx;

typedef struct evt_engine {
    message_queue*        mq;                   // OWNED — message queue backing the engine
    bytemap*              exact_topic_hooks;    // OWNED — exact-topic hook registry
    bytemap*              generic_topic_hooks;  // OWNED — generic-topic hook registry
    double                mq_timeout_seconds;   // timeout for hybrid get
    uint64_t              mq_spin_limit;        // spin limit for hybrid get
    _Atomic uint64_t      seq_id;               // publish sequence counter; atomic ops only
    atomic_bool           active;               // loop switch; atomic store/load only
    evt_engine_timer_ctx* timer;                // OWNED — timer ctx linked-list head (sorted by next_due)
    bytemap*              timer_topics;         // OWNED — timer topic key → ctx registry (filters duplicates)
    size_t                n_timer;              // registered timer task count (across all ctxs)
    double                next_timer_due;       // cached earliest next tick (head ctx next_due)
} evt_engine;

// ========== Forward Declaration ==========

static inline void                 c_evt_engine_pin_cpu(void);
static inline evt_engine*          c_evt_engine_new(allocator_protocol* allocator);
static inline int                  c_evt_engine_init(evt_engine* engine, allocator_protocol* allocator);
static inline void                 c_evt_engine_free(evt_engine* engine);
static inline void                 c_evt_engine_dealloc(evt_engine* engine);
static inline int                  c_evt_engine_loop(evt_engine* engine);
static inline evt_message_payload* c_evt_engine_get(evt_engine* engine, bool block, size_t max_spin, double timeout);
static inline void                 c_evt_engine_trigger(evt_engine* engine, evt_message_payload* msg);
static inline int                  c_evt_engine_publish(evt_engine* engine, evt_message_payload* payload, bool block, size_t max_spin, double timeout);
static inline int                  c_evt_engine_register_hook(evt_engine* engine, evt_hook* hook);
static inline int                  c_evt_engine_unregister_hook(evt_engine* engine, evt_topic* topic, evt_hook** out_hook);
static inline int                  c_evt_engine_register_handler(evt_engine* engine, evt_topic* topic, const void* fn, evt_callback_type ftype, void* user_data, bool deduplicate);
static inline int                  c_evt_engine_unregister_handler(evt_engine* engine, evt_topic* topic, const void* fn, evt_callback_type ftype);
static inline bool                 c_evt_engine_is_active(const evt_engine* engine);
static inline void                 c_evt_engine_set_active(evt_engine* engine, bool active);
static inline uint64_t             c_evt_engine_get_seq_id(const evt_engine* engine);
static inline int                  c_evt_engine_register_timer(evt_engine* engine, evt_topic* topic, double interval_seconds, const void* payload_args);
static inline int                  c_evt_engine_unregister_timer(evt_engine* engine, evt_topic* topic);
static inline void                 c_evt_engine_set_timer_active(evt_engine* engine, bool active);

// ========== Utility Functions ==========

/**
 * @brief Pin the calling thread to the loop CPU selected by EE_LOOP_CPU.
 *
 * Called once at the top of the engine loop entry points so that both the
 * pure-C loop (c_evt_engine_loop) and the GIL-aware loop
 * (c_evt_engine_loop_gil) run their dispatch thread on a fixed core.
 * No-op when EE_LOOP_CPU is -1 or on platforms without thread affinity.
 */
static inline void c_evt_engine_pin_cpu(void) {
#if EE_LOOP_CPU >= 0
#if defined(__linux__)
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(EE_LOOP_CPU, &set);
    pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &set);
#elif defined(_WIN32)
    SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR) 1 << EE_LOOP_CPU);
#endif
#endif
}

// ========== Public APIs (Lifecycle Management) ==========

/**
 * @brief Allocate and initialize a new event engine.
 * @param allocator allocator_protocol for the allocation (NULL uses the default).
 * @return Newly allocated evt_engine, or NULL on allocation failure.
 */
static inline evt_engine* c_evt_engine_new(allocator_protocol* allocator) {
    evt_engine* engine = (evt_engine*) c_ap_alloc(sizeof(evt_engine), allocator);
    if (!engine) return NULL;

    int ret_code = c_evt_engine_init(engine, allocator);
    if (ret_code != EVT_RET_OK) {
        c_ap_free(engine);
        return NULL;
    }

    return engine;
}

/**
 * @brief Initialize a caller-allocated evt_engine.
 * @param engine Engine to initialize (must not be NULL).
 * @param allocator allocator_protocol; derived from the engine block when NULL.
 * @return EVT_RET_OK on success, error code otherwise.
 */
static inline int c_evt_engine_init(evt_engine* engine, allocator_protocol* allocator) {
    if (!engine) return EVT_RET_ERR_INVALID_INPUT;

    if (!allocator) allocator = c_ap_protocol_from_ptr(engine);

    engine->mq = c_mq_new(DEFAULT_MQ_CAPACITY, NULL, allocator);
    if (!engine->mq) goto oom;

    engine->exact_topic_hooks = c_bytemap_new(0, allocator);
    if (!engine->exact_topic_hooks) goto oom;

    engine->generic_topic_hooks = c_bytemap_new(0, allocator);
    if (!engine->generic_topic_hooks) goto oom;

    engine->timer_topics = c_bytemap_new(0, allocator);
    if (!engine->timer_topics) goto oom;

    atomic_init(&engine->active, false);
    engine->mq_timeout_seconds = DEFAULT_MQ_TIMEOUT_SECONDS;
    engine->mq_spin_limit = DEFAULT_MQ_SPIN_LIMIT;
    atomic_init(&engine->seq_id, 0);
    engine->timer = NULL;
    engine->n_timer = 0;
    engine->next_timer_due = 0;
    return EVT_RET_OK;

oom:
    if (engine->mq) c_mq_free(engine->mq);
    if (engine->timer_topics) c_bytemap_free(engine->timer_topics);
    if (engine->generic_topic_hooks) c_bytemap_free(engine->generic_topic_hooks);
    if (engine->exact_topic_hooks) c_bytemap_free(engine->exact_topic_hooks);
    return EVT_RET_ERR_OOM;
}

/**
 * @brief Destroy an evt_engine created by c_evt_engine_new.
 * @param engine Engine to destroy (may be NULL).
 */
static inline void c_evt_engine_free(evt_engine* engine) {
    if (!engine) return;

    c_evt_engine_dealloc(engine);

    c_ap_free(engine);
}

/**
 * @brief Deallocate resources of a caller-allocated engine; does not self-free.
 * @param engine Engine to deallocate (may be NULL).
 */
static inline void c_evt_engine_dealloc(evt_engine* engine) {
    if (!engine) return;

    atomic_store_explicit(&engine->active, false, memory_order_release);
    atomic_store_explicit(&engine->seq_id, 0, memory_order_relaxed);
    evt_engine_timer_ctx* ctx = engine->timer;
    while (ctx) {
        evt_engine_timer_ctx* next = ctx->next;
        atomic_store_explicit(&ctx->active, false, memory_order_release);
        for (size_t i = 0; i < ctx->n_task; i++) {
            if (ctx->task[i].payload.fn_dealloc) {
                ctx->task[i].payload.fn_dealloc(&ctx->task[i].payload);
            }
        }
        if (ctx->task) c_ap_free(ctx->task);
        c_ap_free(ctx);
        ctx = next;
    }
    engine->timer = NULL;
    engine->n_timer = 0;
    engine->next_timer_due = 0;
    if (engine->timer_topics) {
        c_bytemap_free(engine->timer_topics);
        engine->timer_topics = NULL;
    }

    if (engine->mq) {
        c_mq_free(engine->mq);
        engine->mq = NULL;
    }

    if (engine->generic_topic_hooks) {
        c_bytemap_free(engine->generic_topic_hooks);
        engine->generic_topic_hooks = NULL;
    }

    if (engine->exact_topic_hooks) {
        c_bytemap_free(engine->exact_topic_hooks);
        engine->exact_topic_hooks = NULL;
    }
}

/**
 * @brief Atomically query whether the engine loop is active.
 * @param engine Engine to inspect (may be NULL).
 * @return true when active, false otherwise.
 */
static inline bool c_evt_engine_is_active(const evt_engine* engine) {
    return engine ? atomic_load_explicit(&engine->active, memory_order_acquire) : false;
}

/**
 * @brief Atomically set the engine loop state.
 * @param engine Engine to update (may be NULL).
 * @param active New run state.
 */
static inline void c_evt_engine_set_active(evt_engine* engine, bool active) {
    if (!engine) return;
    atomic_store_explicit(&engine->active, active, memory_order_release);
}

/**
 * @brief Atomically query the current publish sequence id.
 * @param engine Engine to inspect (may be NULL).
 * @return Current seq_id, or 0 when engine is NULL.
 */
static inline uint64_t c_evt_engine_get_seq_id(const evt_engine* engine) {
    return engine ? atomic_load_explicit(&engine->seq_id, memory_order_relaxed) : 0;
}

// ========== Public APIs (Timer Management) ==========

/* Monotonic seconds since an arbitrary epoch, for drift-free scheduling.
   Single implementation lives in c_mqueue.h (c_mq_monotonic_seconds) —
   QPC on Windows, CLOCK_MONOTONIC elsewhere. */
static inline double c_evt_engine_monotonic_seconds(void) {
    return c_mq_monotonic_seconds();
}

/* Next interval-aligned tick: the smallest multiple of interval strictly
   greater than now. Every next_due is therefore a whole multiple of its
   interval — drift-free, and all timers of the same interval tick at the
   same instants. */
static inline double c_evt_engine_timer_align(double now, double interval_seconds) {
    return (floor(now / interval_seconds) + 1.0) * interval_seconds;
}

/* Insert a detached ctx into the list sorted by next_due ascending (ties go
   after equal dues, so coincident ticks round-robin) and re-cache the
   earliest next tick. */
static inline void c_evt_engine_timer_insert(evt_engine* engine, evt_engine_timer_ctx* ctx) {
    evt_engine_timer_ctx** link = &engine->timer;
    while (*link && (*link)->next_due <= ctx->next_due) link = &(*link)->next;
    ctx->next = *link;
    *link = ctx;
    engine->next_timer_due = engine->timer->next_due;
}

/* Unlink a ctx from the list and re-cache the earliest next tick. */
static inline void c_evt_engine_timer_unlink(evt_engine* engine, evt_engine_timer_ctx* ctx) {
    evt_engine_timer_ctx** link = &engine->timer;
    while (*link && *link != ctx) link = &(*link)->next;
    if (*link == ctx) *link = ctx->next;
    engine->next_timer_due = engine->timer ? engine->timer->next_due : 0;
}

/* Fire one tick of the (head) timer ctx. Every task in the ctx dispatches
   together — payloads are embedded and go directly to hooks, never queued.
   Afterwards the ctx advances to its next aligned boundary (coalescing any
   boundaries missed by a late wake — at most one tick per poll per interval,
   matching the original engine) and relinks to its sorted position. */
static inline void c_evt_engine_timer_fire(evt_engine* engine, evt_engine_timer_ctx* ctx, double now) {
    if (atomic_load_explicit(&ctx->active, memory_order_acquire)) {
        for (size_t i = 0; i < ctx->n_task; i++) {
            evt_engine_task* task = &ctx->task[i];
            task->payload.seq_id = atomic_fetch_add_explicit(&engine->seq_id, 1, memory_order_relaxed);
            c_evt_engine_trigger(engine, &task->payload);
        }
    }

    ctx->next_due += ctx->interval_seconds;
    while (ctx->next_due <= now) ctx->next_due += ctx->interval_seconds;

    // The head has moved on — relink it to its sorted position
    engine->timer = ctx->next;
    ctx->next = NULL;
    c_evt_engine_timer_insert(engine, ctx);
}

/* Fire overdue timer ticks. Called from the dispatch loop after every queue
   poll; the cached next_timer_due (the head's next_due) avoids probing the
   clock when nothing is due, and the sorted list keeps the head as the next
   ctx to tick. */
static inline void c_evt_engine_timer_poll(evt_engine* engine) {
    if (!engine->timer) return;

    if (engine->next_timer_due <= 0) {  // schedule not cached (defensive)
        engine->next_timer_due = engine->timer->next_due;
    }

    const double now = c_evt_engine_monotonic_seconds();
    if (now < engine->next_timer_due) return;

    while (engine->timer && engine->timer->next_due <= now) {
        c_evt_engine_timer_fire(engine, engine->timer, now);
    }
}

/**
 * @brief Register a timer task on the engine.
 *
 * The task payload is embedded in its ctx's contiguous task buffer and
 * carries @p payload_args as its user data; it is never queued — each tick
 * dispatches it directly to the matching hooks. There is one timer ctx per
 * interval: tasks sharing an interval share one ctx and fire together on the
 * same (interval-aligned) boundaries, while different intervals tick
 * independently. The topic registry filters out already-registered topics —
 * re-registering the same topic returns EVT_RET_ERR_DUPLICATE instead of
 * overriding the payload or double firing.
 *
 * @param engine Engine to register the timer on (must be initialized).
 * @param topic Topic for timer tick payloads (must not be NULL).
 * @param interval_seconds Tick interval shared by all tasks in the ctx (> 0).
 * @param payload_args User data carried by the task payload on every tick.
 * @return EVT_RET_OK on success, error code otherwise.
 */
static inline int c_evt_engine_register_timer(evt_engine* engine, evt_topic* topic, double interval_seconds, const void* payload_args) {
    if (!engine || !engine->mq || !topic) return EVT_RET_ERR_INVALID_INPUT;
    if (interval_seconds <= 0) return EVT_RET_ERR_INVALID_INPUT;

    // Filter out already-registered timer topics (prevents payload override
    // and double firing for the same topic).
    evt_engine_timer_ctx* ctx = NULL;
    c_bytemap_get(engine->timer_topics, topic->key, topic->key_len, (void**) &ctx);
    if (ctx) return EVT_RET_ERR_DUPLICATE;

    allocator_protocol* allocator = c_ap_protocol_from_ptr(engine);
    const double        now = c_evt_engine_monotonic_seconds();

    // One ctx per interval — locate it or create one aligned to the interval
    // boundaries (next_due is always a whole multiple of interval_seconds).
    bool ctx_is_new = false;
    ctx = engine->timer;
    while (ctx && ctx->interval_seconds != interval_seconds) ctx = ctx->next;
    if (!ctx) {
        ctx = (evt_engine_timer_ctx*) c_ap_alloc(sizeof(evt_engine_timer_ctx), allocator);
        if (!ctx) return EVT_RET_ERR_OOM;
        atomic_init(&ctx->active, true);
        ctx->interval_seconds = interval_seconds;
        ctx->next_due = c_evt_engine_timer_align(now, interval_seconds);
        ctx->capacity = 0;
        ctx->n_task = 0;
        ctx->task = NULL;
        ctx->next = NULL;
        ctx_is_new = true;
    }

    // Grow the contiguous task buffer when full
    if (ctx->n_task == ctx->capacity) {
        size_t           new_capacity = ctx->capacity ? ctx->capacity * 2 : 4;
        evt_engine_task* grown = (evt_engine_task*) c_ap_alloc(new_capacity * sizeof(evt_engine_task), allocator);
        if (!grown) {
            if (ctx_is_new) c_ap_free(ctx);
            return EVT_RET_ERR_OOM;
        }
        if (ctx->task) {
            memcpy(grown, ctx->task, ctx->n_task * sizeof(evt_engine_task));
            c_ap_free(ctx->task);
        }
        ctx->task = grown;
        ctx->capacity = new_capacity;
    }

    evt_engine_task* task = &ctx->task[ctx->n_task];
    task->topic = topic;
    task->payload.args = (void*) payload_args;
    task->payload.topic = topic;
    task->payload.seq_id = 0;
    task->payload.fn_dealloc = NULL;
    ctx->n_task += 1;

    // Publish the topic → ctx entry; roll back the task on registry failure
    if (c_bytemap_set(engine->timer_topics, topic->key, topic->key_len, (void*) ctx, NULL) != BYTEMAP_OK) {
        ctx->n_task -= 1;
        if (ctx_is_new) {
            if (ctx->task) c_ap_free(ctx->task);
            c_ap_free(ctx);
        }
        return EVT_RET_ERR_OOM;
    }

    if (ctx_is_new) c_evt_engine_timer_insert(engine, ctx);
    engine->n_timer += 1;

    // Registration (re)arms the ctx — see evt_engine_timer_ctx.active
    atomic_store_explicit(&ctx->active, true, memory_order_release);
    return EVT_RET_OK;
}

/**
 * @brief Unregister a timer task by topic.
 *
 * Releases the task payload through its self-destruct hook (if any) and
 * compacts the ctx's contiguous task buffer (registration order preserved).
 * Unlinks and frees the timer ctx when its last task is removed.
 *
 * @param engine Engine to unregister from (may be NULL).
 * @param topic Topic of the timer task to remove.
 * @return EVT_RET_OK on success, EVT_RET_ERR_NOT_FOUND when unknown.
 */
static inline int c_evt_engine_unregister_timer(evt_engine* engine, evt_topic* topic) {
    if (!engine || !topic) return EVT_RET_ERR_INVALID_INPUT;

    evt_engine_timer_ctx* ctx = NULL;
    if (c_bytemap_get(engine->timer_topics, topic->key, topic->key_len, (void**) &ctx) != BYTEMAP_OK || !ctx) {
        return EVT_RET_ERR_NOT_FOUND;
    }

    // Locate the task by topic key (registry keys and task topics share the
    // same key identity).
    size_t idx = 0;
    bool   found = false;
    for (; idx < ctx->n_task; idx++) {
        evt_topic* task_topic = ctx->task[idx].topic;
        if (task_topic && task_topic->key_len == topic->key_len &&
            memcmp(task_topic->key, topic->key, topic->key_len) == 0) {
            found = true;
            break;
        }
    }
    if (!found) return EVT_RET_ERR_NOT_FOUND;  // registry/task mismatch — defensive

    evt_engine_task* task = &ctx->task[idx];
    if (task->payload.fn_dealloc) task->payload.fn_dealloc(&task->payload);
    for (size_t j = idx + 1; j < ctx->n_task; j++) {
        ctx->task[j - 1] = ctx->task[j];
    }
    ctx->n_task -= 1;
    engine->n_timer -= 1;

    c_bytemap_pop(engine->timer_topics, topic->key, topic->key_len, NULL);

    if (ctx->n_task == 0) {
        c_evt_engine_timer_unlink(engine, ctx);
        if (ctx->task) c_ap_free(ctx->task);
        c_ap_free(ctx);
    }
    return EVT_RET_OK;
}

/**
 * @brief Atomically set the engine timer firing state without releasing tasks.
 *
 * Affects every timer ctx — there is no per-task gating. A later
 * c_evt_engine_register_timer call re-arms its ctx, discarding a paused state.
 *
 * @param engine Engine whose timer to update (may be NULL).
 * @param active New timer firing state.
 */
static inline void c_evt_engine_set_timer_active(evt_engine* engine, bool active) {
    if (!engine) return;
    evt_engine_timer_ctx* ctx = engine->timer;
    while (ctx) {
        atomic_store_explicit(&ctx->active, active, memory_order_release);
        ctx = ctx->next;
    }
}

// ========== Public APIs (MessageQueue Management) ==========

/* Blocking-wait timeout for one loop iteration. The wait is capped at the
   earliest timer tick so ticks fire on their own cadence instead of arriving
   in bursts on queue wake-ups. Pure C — makes no GIL assumptions. */
static inline double c_evt_engine_mq_wait_seconds(const evt_engine* engine) {
    double timeout = engine->mq_timeout_seconds;
    if (engine->timer && engine->n_timer &&
        atomic_load_explicit(&engine->timer->active, memory_order_acquire) &&
        engine->next_timer_due > 0) {
        double wait = engine->next_timer_due - c_evt_engine_monotonic_seconds();
        if (wait <= 0) {
            timeout = 1e-6;  // tick already due — wake immediately
        }
        else if (wait < timeout) {
            timeout = wait;
        }
    }
    return timeout;
}

/**
 * @brief Run the engine dispatch loop. Pure C — blocks on the queue wait
 * without touching the GIL; callers needing GIL release around the blocking
 * wait should use c_evt_engine_loop_gil instead.
 *
 * @param engine Engine to run (must be initialized).
 * @return EVT_RET_OK on clean shutdown, error code otherwise.
 */
static inline int c_evt_engine_loop(evt_engine* engine) {
    if (!engine) return EVT_RET_ERR_INVALID_INPUT;
    if (!engine->mq) return EVT_RET_ERR_UNINITIALIZED;

    c_evt_engine_pin_cpu();

    size_t               max_spin = engine->mq_spin_limit;
    evt_message_payload* msg = NULL;

    while (atomic_load_explicit(&engine->active, memory_order_acquire)) {
        // Step 1: Await message
        int ret_code = c_mq_get_hybrid(engine->mq, &msg, max_spin, c_evt_engine_mq_wait_seconds(engine));

        // Step 2: Fire overdue timer ticks
        c_evt_engine_timer_poll(engine);
        if (ret_code != EVT_RET_OK) continue;

        // Dispatch and release the payload via its self-destruct hook
        c_evt_engine_trigger(engine, msg);
        if (msg->fn_dealloc) msg->fn_dealloc(msg);
    }
    return EVT_RET_OK;
}

static inline evt_message_payload* c_evt_engine_get(evt_engine* engine, bool block, size_t max_spin, double timeout) {
    if (!engine || !engine->mq) return NULL;

    evt_message_payload* msg = NULL;
    int                  ret_code = block ? c_mq_get_hybrid(engine->mq, &msg, max_spin, timeout) : c_mq_get(engine->mq, &msg);
    if (ret_code != EVT_RET_OK) return NULL;
    return msg;
}

static inline void c_evt_engine_trigger(evt_engine* engine, evt_message_payload* msg) {
    evt_topic* msg_topic = msg->topic;

    // Step 1: Match exact_topic_hooks
    evt_hook* hook = NULL;
    c_bytemap_get(engine->exact_topic_hooks, msg_topic->key, msg_topic->key_len, (void**) &hook);
    if (hook) c_evt_hook_invoke(hook, msg);

    // Step 2: Match generic_topic_hooks
    bytemap_entry* entry = c_bytemap_first(engine->generic_topic_hooks);
    while (entry) {
        hook = (evt_hook*) c_bytemap_entry_value(entry);
        if (!hook) {
            entry = entry->next;
            continue;
        }
        bool is_matched = c_topic_match_bool(hook->topic, msg_topic);
        if (is_matched) c_evt_hook_invoke(hook, msg);
        entry = entry->next;
    }
}

/**
 * @brief Publish a payload to the engine queue. Pure C — blocks on the put
 * without touching the GIL; callers needing GIL release around the blocking
 * wait should use c_evt_engine_publish_gil instead.
 *
 * @param engine Engine to publish on (must be initialized).
 * @param payload Payload to send (exact topic only; must not be NULL).
 * @param block Block until space is available when the queue is full.
 * @param max_spin Spin iterations before falling back to blocking.
 * @param timeout Maximum seconds to block (<= 0 waits forever).
 * @return EVT_RET_OK on success, error code otherwise.
 */
static inline int c_evt_engine_publish(evt_engine* engine, evt_message_payload* payload, bool block, size_t max_spin, double timeout) {
    if (!engine || !engine->mq || !payload) return EVT_RET_ERR_INVALID_INPUT;
    if (!payload->topic || !payload->topic->is_exact) return EVT_RET_ERR_INVALID_TOPIC;

    // Step 1: Assembling payload (assign monotonic sequence id)
    payload->seq_id = atomic_fetch_add_explicit(&engine->seq_id, 1, memory_order_relaxed);

    // Step 2: Send the payload
    int ret_code = block ? c_mq_put_hybrid(engine->mq, payload, max_spin, timeout) : c_mq_put(engine->mq, payload);

    // Step 3: Handle failure case (roll back seq_id and release payload)
    if (ret_code != EVT_RET_OK) {
        atomic_fetch_sub_explicit(&engine->seq_id, 1, memory_order_relaxed);
        if (payload->fn_dealloc) payload->fn_dealloc(payload);
    }
    return ret_code;
}

// ========== Public APIs (Hooks and Handlers Management) ==========

/* Fetch the function pointer stored in a callback entry. Every union variant
   stores the function pointer at the same address, so no type dispatch is
   needed — read it through any member. */
static inline const void* c_evt_callback_fn(const evt_callback* callback) {
    return callback ? (const void*) callback->fn.bare : NULL;
}

static inline int c_evt_engine_register_hook(evt_engine* engine, evt_hook* hook) {
    if (!engine || !hook || !hook->topic) return EVT_RET_ERR_INVALID_INPUT;

    evt_topic* topic = hook->topic;
    bytemap*   map = topic->is_exact ? engine->exact_topic_hooks : engine->generic_topic_hooks;

    // Reject duplicate registration for the same topic
    evt_hook* existing = NULL;
    c_bytemap_get(map, topic->key, topic->key_len, (void**) &existing);
    if (existing && existing != hook) return EVT_RET_ERR_DUPLICATE;

    int ret_code = c_bytemap_set(map, topic->key, topic->key_len, (void*) hook, NULL);
    return ret_code == BYTEMAP_OK ? EVT_RET_OK : EVT_RET_ERR_OOM;
}

static inline int c_evt_engine_unregister_hook(evt_engine* engine, evt_topic* topic, evt_hook** out_hook) {
    if (!engine || !topic || !out_hook) return EVT_RET_ERR_INVALID_INPUT;

    bytemap* map = topic->is_exact ? engine->exact_topic_hooks : engine->generic_topic_hooks;

    *out_hook = NULL;
    c_bytemap_pop(map, topic->key, topic->key_len, (void**) out_hook);
    if (!*out_hook) return EVT_RET_ERR_NOT_FOUND;
    return EVT_RET_OK;
}

static inline int c_evt_engine_register_handler(evt_engine* engine, evt_topic* topic, const void* fn, evt_callback_type ftype, void* user_data, bool deduplicate) {
    if (!engine || !topic || !fn) return EVT_RET_ERR_INVALID_INPUT;

    bytemap* map = topic->is_exact ? engine->exact_topic_hooks : engine->generic_topic_hooks;

    // Fetch or create the hook for the topic
    evt_hook* hook = NULL;
    int       ret_code = c_bytemap_get(map, topic->key, topic->key_len, (void**) &hook);
    if (ret_code == BYTEMAP_ERR_NOT_FOUND) {
        allocator_protocol* allocator = c_ap_protocol_from_ptr(engine);
        hook = c_evt_hook_new(topic, allocator);
        if (!hook) return EVT_RET_ERR_OOM;
        if (c_bytemap_set(map, topic->key, topic->key_len, (void*) hook, NULL) != BYTEMAP_OK) {
            c_evt_hook_free(hook);
            return EVT_RET_ERR_OOM;
        }
    }
    else if (ret_code != BYTEMAP_OK || !hook) {
        return EVT_RET_ERR_INVALID_INPUT;  // corrupted registry entry
    }

    return c_evt_hook_register_callback(hook, fn, ftype, user_data, deduplicate);
}

static inline int c_evt_engine_unregister_handler(evt_engine* engine, evt_topic* topic, const void* fn, evt_callback_type ftype) {
    if (!engine || !topic || !fn) return EVT_RET_ERR_INVALID_INPUT;

    bytemap*  map = topic->is_exact ? engine->exact_topic_hooks : engine->generic_topic_hooks;

    evt_hook* hook = NULL;
    if (c_bytemap_get(map, topic->key, topic->key_len, (void**) &hook) != BYTEMAP_OK || !hook) {
        return EVT_RET_ERR_NOT_FOUND;
    }

    // Locate the matching callback entry
    size_t idx = 0;
    bool   found = false;
    for (; idx < hook->n_callbacks; idx++) {
        if (hook->callbacks[idx].type == ftype && c_evt_callback_fn(&hook->callbacks[idx]) == fn) {
            found = true;
            break;
        }
    }
    if (!found) return EVT_RET_ERR_NOT_FOUND;

    int ret_code = c_evt_hook_pop_callback(hook, idx);
    if (ret_code != EVT_RET_OK) return ret_code;

    // Drop the hook from the registry once its last handler is removed
    if (hook->n_callbacks == 0) {
        c_bytemap_pop(map, topic->key, topic->key_len, NULL);
        c_evt_hook_free(hook);
    }
    return EVT_RET_OK;
}

#endif  // C_EVENTENGINE_ENGINE_H
