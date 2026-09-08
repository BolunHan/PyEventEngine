#ifndef C_EVENTENGINE_ENGINE_GIL_H
#define C_EVENTENGINE_ENGINE_GIL_H

#include <Python.h>

#include <event_engine/capi/c_engine.h>

/* GIL-aware wrappers over the pure-C engine layer (c_engine.h).

   Every function in this header MUST be entered with the GIL held from a
   thread that owns a Python thread state (Python threads satisfy both; raw
   pthreads must call PyGILState_Ensure first). The GIL is released only
   around blocking queue waits - all dispatch (trigger, hook callbacks,
   payload release) runs under the GIL. */

// ========== Forward Declarations ==========

static inline int c_evt_engine_loop_gil(evt_engine* engine);

static inline int c_evt_engine_publish_gil(evt_engine* engine, evt_message_payload* payload, bool block, size_t max_spin, double timeout);

// ========== Implementations ==========

/**
 * @brief Run the engine dispatch loop with the GIL held on entry.
 *
 * Releases the GIL only around the blocking queue wait, so every dispatch
 * runs under the GIL. Identical loop body to c_evt_engine_loop - the pure
 * variant keeps the GIL semantics out of the C layer.
 *
 * @param engine Engine to run (must be initialized).
 * @return EVT_RET_OK on clean shutdown, error code otherwise.
 */
static inline int c_evt_engine_loop_gil(evt_engine* engine) {
    if (!engine) return EVT_RET_ERR_INVALID_INPUT;
    if (!engine->mq) return EVT_RET_ERR_UNINITIALIZED;

    c_evt_engine_pin_cpu();

    size_t               max_spin = engine->mq_spin_limit;
    evt_message_payload* msg = NULL;

    while (atomic_load_explicit(&engine->active, memory_order_acquire)) {
        // Step 1: Await message (release the GIL during the blocking wait)
        int ret_code;
        Py_BEGIN_ALLOW_THREADS
            ret_code = c_mq_get_hybrid(engine->mq, &msg, max_spin, c_evt_engine_mq_wait_seconds(engine));
        Py_END_ALLOW_THREADS

            // Step 2: Fire overdue timer ticks (dispatch runs with the GIL held)
            c_evt_engine_timer_poll(engine);
        if (ret_code != EVT_RET_OK) continue;

        // Dispatch and release the payload via its self-destruct hook
        c_evt_engine_trigger(engine, msg);
        if (msg->fn_dealloc) msg->fn_dealloc(msg);
    }
    return EVT_RET_OK;
}

/**
 * @brief Publish a payload to the engine queue with the GIL held on entry.
 *
 * Releases the GIL only around the blocking put; the failure path releases
 * the payload via its self-destruct hook (py payload deallocs need the GIL,
 * which is held there). Identical to c_evt_engine_publish otherwise.
 *
 * @param engine Engine to publish on (must be initialized).
 * @param payload Payload to send (exact topic only; must not be NULL).
 * @param block Block until space is available when the queue is full.
 * @param max_spin Spin iterations before falling back to blocking.
 * @param timeout Maximum seconds to block (<= 0 waits forever).
 * @return EVT_RET_OK on success, error code otherwise.
 */
static inline int c_evt_engine_publish_gil(evt_engine* engine, evt_message_payload* payload, bool block, size_t max_spin, double timeout) {
    if (!engine || !engine->mq || !payload) return EVT_RET_ERR_INVALID_INPUT;
    if (!payload->topic || !payload->topic->is_exact) return EVT_RET_ERR_INVALID_TOPIC;

    // Step 1: Assembling payload (assign monotonic sequence id)
    payload->seq_id = atomic_fetch_add_explicit(&engine->seq_id, 1, memory_order_relaxed);

    // Step 2: Send the payload (release the GIL during the blocking wait)
    int ret_code;
    Py_BEGIN_ALLOW_THREADS
        ret_code = block ? c_mq_put_hybrid(engine->mq, payload, max_spin, timeout) : c_mq_put(engine->mq, payload);
    Py_END_ALLOW_THREADS

        // Step 3: Handle failure case (roll back seq_id and release payload)
        if (ret_code != EVT_RET_OK) {
        atomic_fetch_sub_explicit(&engine->seq_id, 1, memory_order_relaxed);
        if (payload->fn_dealloc) payload->fn_dealloc(payload);
    }
    return ret_code;
}

#endif  // C_EVENTENGINE_ENGINE_GIL_H
