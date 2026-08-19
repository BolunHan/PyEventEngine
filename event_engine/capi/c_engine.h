#ifndef C_EVENTENGINE_ENGINE_H
#define C_EVENTENGINE_ENGINE_H

#include <stdatomic.h>
#include <stdbool.h>

#include <cbase/allocator_protocol/c_allocator_protocol.h>
#include <event_engine/capi/c_event.h>
#include <event_engine/capi/c_event_pypayload.h>
#include <event_engine/capi/c_mqueue.h>
#include <event_engine/capi/c_ret_code.h>
#include <event_engine/capi/c_topic.h>

// ========== Structs ==========

typedef struct evt_engine {
    message_queue*   mq;                   // OWNED — message queue backing the engine
    bytemap*         exact_topic_hooks;    // OWNED — exact-topic hook registry
    bytemap*         generic_topic_hooks;  // OWNED — generic-topic hook registry
    double           mq_timeout_seconds;   // timeout for hybrid get
    uint64_t         mq_spin_limit;        // spin limit for hybrid get
    _Atomic uint64_t seq_id;               // publish sequence counter; atomic ops only
    atomic_bool      active;               // loop switch; atomic store/load only
} evt_engine;

// ========== Forward Declaration ==========

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

    atomic_init(&engine->active, false);
    engine->mq_timeout_seconds = DEFAULT_MQ_TIMEOUT_SECONDS;
    engine->mq_spin_limit = DEFAULT_MQ_SPIN_LIMIT;
    atomic_init(&engine->seq_id, 0);
    return EVT_RET_OK;

oom:
    if (engine->mq) c_mq_free(engine->mq);
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

// ========== Public APIs (MessageQueue Management) ==========

static inline int c_evt_engine_loop(evt_engine* engine) {
    if (!engine) return EVT_RET_ERR_INVALID_INPUT;
    if (!engine->mq) return EVT_RET_ERR_UNINITIALIZED;

    double               timeout = engine->mq_timeout_seconds;
    size_t               max_spin = engine->mq_spin_limit;
    evt_message_payload* msg = NULL;

    while (atomic_load_explicit(&engine->active, memory_order_acquire)) {
        // Step 1: Await message
        int ret_code = c_mq_get_hybrid(engine->mq, &msg, max_spin, timeout);
        if (ret_code != EVT_RET_OK) continue;

        // Trigger message callbacks
        c_evt_engine_trigger(engine, msg);

        // Clean up the message payload
        c_evt_pypayload_free(msg);
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

static inline int c_evt_engine_publish(evt_engine* engine, evt_message_payload* payload, bool block, size_t max_spin, double timeout) {
    if (!engine || !engine->mq || !payload) return EVT_RET_ERR_INVALID_INPUT;
    if (!payload->topic || !payload->topic->is_exact) return EVT_RET_ERR_INVALID_TOPIC;

    // Step 1: Assembling payload (assign monotonic sequence id)
    payload->seq_id = atomic_fetch_add_explicit(&engine->seq_id, 1, memory_order_relaxed);

    // Step 2: Send the payload (queue is thread-safe)
    int ret_code = block ? c_mq_put_hybrid(engine->mq, payload, max_spin, timeout) : c_mq_put(engine->mq, payload);

    // Step 3: Handle failure case (roll back seq_id and release payload)
    if (ret_code != EVT_RET_OK) {
        atomic_fetch_sub_explicit(&engine->seq_id, 1, memory_order_relaxed);
        c_evt_pypayload_free(payload);
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
