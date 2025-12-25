#ifndef C_EVENT_H
#define C_EVENT_H

#include "c_heap_allocator.h"
#include "c_topic.h"

/* @brief Message payload stored in the queue
 *
 * This structure holds the message data along with optional
 * metadata such as topic pointer, Python-compatible args/kwargs,
 * and a sequence identifier.
 */
typedef struct evt_message_payload {
    evt_topic* topic;               // optional Topic pointer (borrowed or owned)
    void* args;                     // pointer compatible with Python "args"
    void* kwargs;                   // pointer compatible with Python "kwargs"
    uint64_t seq_id;                // optional sequence id (0 if unused)
    heap_allocator* allocator;      // allocator for payload data (may be NULL)
} evt_message_payload;

typedef void (*evt_callback_bare)(void);

typedef void (*evt_callback_with_topic)(evt_topic* topic);

typedef void (*evt_callback_with_args)(void* args, void* kwargs, uint64_t seq_id);

typedef void (*evt_callback_with_topic_args)(evt_topic* topic, void* args, void* kwargs, uint64_t seq_id);

typedef void (*evt_callback_with_payload)(evt_message_payload* payload);

typedef void (*evt_callback_with_userdata)(evt_message_payload* payload, void* user_data);

typedef enum evt_callback_type {
    EVT_CALLBACK_BARE = 0,
    EVT_CALLBACK_WITH_TOPIC = 1,
    EVT_CALLBACK_WITH_ARGS = 2,
    EVT_CALLBACK_WITH_TOPIC_ARGS = 3,
    EVT_CALLBACK_WITH_PAYLOAD = 4,
    EVT_CALLBACK_WITH_USERDATA = 5,
} evt_callback_type;

typedef union evt_callback_variants {
    evt_callback_bare               bare;
    evt_callback_with_topic         with_topic;
    evt_callback_with_args          with_args;
    evt_callback_with_topic_args    with_topic_args;
    evt_callback_with_payload       with_payload;
    evt_callback_with_userdata      with_userdata;
} evt_callback_variants;

typedef struct evt_callback {
    evt_callback_type type;
    evt_callback_variants fn;
    void* user_data;
} evt_callback;

typedef struct evt_hook {
    evt_topic* topic;
    evt_callback* callbacks;
    size_t n_callbacks;
} evt_hook;

/* Return codes for evt_hook_register_callback */
typedef enum evt_hook_error {
    EVT_HOOK_OK = 0,
    EVT_HOOK_ERR_INVALID_INPUT = -1,
    EVT_HOOK_ERR_OOM = -2,
    EVT_HOOK_ERR_DUPLICATE = -3,
} evt_hook_error;

static inline void c_evt_callback_invoke(const evt_callback* callback, evt_message_payload* payload) {
    if (!callback) return;

    switch (callback->type) {
        case EVT_CALLBACK_WITH_USERDATA:
        {
            if (callback->fn.with_userdata) callback->fn.with_userdata(payload, callback->user_data);
            break;
        }
        case EVT_CALLBACK_WITH_PAYLOAD:
            if (callback->fn.with_payload) callback->fn.with_payload(payload);
            break;
        case EVT_CALLBACK_WITH_TOPIC_ARGS:
        {
            if (callback->fn.with_topic_args) {
                if (!payload) callback->fn.with_topic_args(NULL, NULL, NULL, 0);
                else callback->fn.with_topic_args(payload->topic, payload->args, payload->kwargs, payload->seq_id);
            }
            break;
        }
        case EVT_CALLBACK_WITH_ARGS:
        {
            if (callback->fn.with_args) {
                if (!payload) callback->fn.with_args(NULL, NULL, 0);
                else callback->fn.with_args(payload->args, payload->kwargs, payload->seq_id);
            }
            break;
        }
        case EVT_CALLBACK_WITH_TOPIC:
        {
            if (callback->fn.with_topic) {
                if (!payload) callback->fn.with_topic(NULL);
                else callback->fn.with_topic(payload->topic);
            }
            break;
        }
        case EVT_CALLBACK_BARE:
            if (callback->fn.bare) callback->fn.bare();
            break;
        default:
            break;
    }
}

static inline evt_hook* c_evt_hook_new(evt_topic* topic) {
    evt_hook* hook = (evt_hook*) calloc(1, sizeof(evt_hook));
    if (!hook) {
        return NULL;
    }
    hook->topic = topic;
    hook->callbacks = NULL;
    hook->n_callbacks = 0;
    return hook;
}

static inline void c_evt_hook_free(evt_hook* hook) {
    if (!hook) return;
    if (hook->callbacks) free(hook->callbacks);
    free(hook);
}

static inline int c_evt_hook_register_callback(evt_hook* hook, const void* fn, evt_callback_type ftype, void* user_data, int deduplicate) {
    if (!hook || !fn) return EVT_HOOK_ERR_INVALID_INPUT;

    /* Deduplication check: compare function pointer and type */
    if (hook->callbacks && deduplicate) {
        for (size_t i = 0; i < hook->n_callbacks; ++i) {
            const evt_callback* callback = &hook->callbacks[i];
            if (callback->type != ftype) continue;
            const void* existing = NULL;
            switch (callback->type) {
                case EVT_CALLBACK_WITH_TOPIC:      existing = (const void*) callback->fn.with_topic; break;
                case EVT_CALLBACK_WITH_ARGS:       existing = (const void*) callback->fn.with_args; break;
                case EVT_CALLBACK_WITH_TOPIC_ARGS: existing = (const void*) callback->fn.with_topic_args; break;
                case EVT_CALLBACK_WITH_PAYLOAD:    existing = (const void*) callback->fn.with_payload; break;
                case EVT_CALLBACK_WITH_USERDATA:   existing = (const void*) callback->fn.with_userdata; break;
                case EVT_CALLBACK_BARE:            existing = (const void*) callback->fn.bare; break;
                default: break;
            }
            if (existing == fn) {
                return EVT_HOOK_ERR_DUPLICATE; /* duplicate ignored */
            }
        }
    }

    const size_t new_count = hook->n_callbacks + 1;
    evt_callback* grown = (evt_callback*) realloc(hook->callbacks, new_count * sizeof(evt_callback));
    if (!grown) {
        return EVT_HOOK_ERR_OOM;
    }
    hook->callbacks = grown;

    evt_callback* cb = hook->callbacks + hook->n_callbacks;
    cb->type = ftype;
    cb->user_data = user_data;

    switch (ftype) {
        case EVT_CALLBACK_WITH_TOPIC:      cb->fn.with_topic = (evt_callback_with_topic) fn; break;
        case EVT_CALLBACK_WITH_ARGS:       cb->fn.with_args = (evt_callback_with_args) fn; break;
        case EVT_CALLBACK_WITH_TOPIC_ARGS: cb->fn.with_topic_args = (evt_callback_with_topic_args) fn; break;
        case EVT_CALLBACK_WITH_PAYLOAD:    cb->fn.with_payload = (evt_callback_with_payload) fn; break;
        case EVT_CALLBACK_WITH_USERDATA:   cb->fn.with_userdata = (evt_callback_with_userdata) fn; break;
        case EVT_CALLBACK_BARE:            cb->fn.bare = (evt_callback_bare) fn; break;
        default:                           cb->fn.bare = NULL; break;
    }

    hook->n_callbacks = new_count;
    return EVT_HOOK_OK;
}

static inline int c_evt_hook_invoke_callbacks(evt_hook* hook, evt_message_payload* payload) {
    if (!hook) return EVT_HOOK_ERR_INVALID_INPUT;

    for (size_t i = 0; i < hook->n_callbacks; ++i) {
        c_evt_callback_invoke(&hook->callbacks[i], payload);
    }
    return EVT_HOOK_OK;
}

#endif /* C_EVENT_H */