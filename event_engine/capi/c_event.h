#ifndef C_EVENT_H
#define C_EVENT_H

#include "c_heap_allocator.h"
#include "c_topic.h"
#include <stdint.h>
#include <stdlib.h>

/* @brief Message payload stored in the queue
 *
 * This structure holds the message data along with optional
 * metadata such as topic pointer, Python-compatible args/kwargs,
 * and a sequence identifier.
 */
typedef struct evt_message_payload {
    void* args;                     // optional user data pointer
    evt_topic* topic;               // optional Topic borrowed pointer
    uint64_t seq_id;                // optional sequence id (0 if unused)
    heap_allocator* allocator;      // allocator for payload data (may be NULL)
} evt_message_payload;

typedef void (*evt_callback_bare)(void);

typedef void (*evt_callback_with_args)(void* args);

typedef void (*evt_callback_with_topic)(evt_topic* topic);

typedef void (*evt_callback_with_userdata)(void* user_data);

typedef void (*evt_callback_with_args_topic)(void* args, evt_topic* topic);

typedef void (*evt_callback_with_args_userdata)(void* args, void* user_data);

typedef void (*evt_callback_with_topic_userdata)(evt_topic* topic, void* user_data);

typedef void (*evt_callback_with_args_topic_userdata)(void* args, evt_topic* topic, void* user_data);

typedef void (*evt_callback_with_payload)(evt_message_payload* payload);

typedef void (*evt_callback_with_payload_userdata)(evt_message_payload* payload, void* user_data);

typedef enum evt_callback_type {
    EVT_CALLBACK_BARE                       = 0,
    EVT_CALLBACK_WITH_ARGS                  = 1,
    EVT_CALLBACK_WITH_TOPIC                 = 2,
    EVT_CALLBACK_WITH_USERDATA              = 4,
    EVT_CALLBACK_WITH_ARGS_TOPIC            = 3,
    EVT_CALLBACK_WITH_ARGS_USERDATA         = 5,
    EVT_CALLBACK_WITH_TOPIC_USERDATA        = 6,
    EVT_CALLBACK_WITH_ARGS_TOPIC_USERDATA   = 7,
    EVT_CALLBACK_WITH_PAYLOAD               = 8,
    EVT_CALLBACK_WITH_PAYLOAD_USERDATA      = 12,
} evt_callback_type;

typedef union evt_callback_variants {
    evt_callback_bare                       bare;
    evt_callback_with_args                  with_args;
    evt_callback_with_topic                 with_topic;
    evt_callback_with_userdata              with_userdata;
    evt_callback_with_args_topic            with_args_topic;
    evt_callback_with_args_userdata         with_args_userdata;
    evt_callback_with_topic_userdata        with_topic_userdata;
    evt_callback_with_args_topic_userdata   with_args_topic_userdata;
    evt_callback_with_payload               with_payload;
    evt_callback_with_payload_userdata      with_payload_userdata;
} evt_callback_variants;

typedef struct evt_callback {
    evt_callback_type type;
    evt_callback_variants fn;
    void* user_data;
} evt_callback;

typedef enum evt_hook_watcher_type {
    EVT_HOOK_WATCHER_PRE_INVOKED = 0,
    EVT_HOOK_WATCHER_POST_INVOKED = 1,
} evt_hook_watcher_type;

typedef struct evt_hook evt_hook;

typedef void (*evt_hook_watcher_fn)(evt_hook* hook, evt_hook_watcher_type watcher_type, evt_message_payload* payload, void* user_data);

typedef struct evt_hook_watcher {
    evt_hook_watcher_fn fn;
    void* user_data;
} evt_hook_watcher;

typedef enum evt_hook_ret_code {
    EVT_HOOK_OK = 0,
    EVT_HOOK_ERR_INVALID_INPUT = -1,
    EVT_HOOK_ERR_OOM = -2,
    EVT_HOOK_ERR_DUPLICATE = -3,
} evt_hook_ret_code;

typedef struct evt_hook {
    evt_topic* topic;
    evt_callback* callbacks;
    size_t n_callbacks;
    evt_hook_watcher* pre_watchers;
    size_t n_pre_watchers;
    evt_hook_watcher* post_watchers;
    size_t n_post_watchers;
} evt_hook;

static inline void c_evt_callback_invoke(const evt_callback* callback, evt_message_payload* payload) {
    if (!callback) return;
    void* args = payload ? payload->args : NULL;
    evt_topic* topic = payload ? payload->topic : NULL;
    void* user_data = callback->user_data;

    switch (callback->type) {
        case EVT_CALLBACK_WITH_PAYLOAD_USERDATA:
            if (callback->fn.with_payload_userdata) callback->fn.with_payload_userdata(payload, user_data);
            break;
        case EVT_CALLBACK_WITH_PAYLOAD:
            if (callback->fn.with_payload) callback->fn.with_payload(payload);
            break;
        case EVT_CALLBACK_WITH_ARGS_TOPIC_USERDATA:
            if (callback->fn.with_args_topic_userdata) callback->fn.with_args_topic_userdata(args, topic, user_data);
            break;
        case EVT_CALLBACK_WITH_TOPIC_USERDATA:
            if (callback->fn.with_topic_userdata) callback->fn.with_topic_userdata(topic, user_data);
            break;
        case EVT_CALLBACK_WITH_ARGS_USERDATA:
            if (callback->fn.with_args_userdata) callback->fn.with_args_userdata(args, user_data);
            break;
        case EVT_CALLBACK_WITH_ARGS_TOPIC:
            if (callback->fn.with_args_topic) callback->fn.with_args_topic(args, topic);
            break;
        case EVT_CALLBACK_WITH_TOPIC:
            if (callback->fn.with_topic) callback->fn.with_topic(topic);
            break;
        case EVT_CALLBACK_WITH_ARGS:
            if (callback->fn.with_args) callback->fn.with_args(args);
            break;
        case EVT_CALLBACK_WITH_USERDATA:
            if (callback->fn.with_userdata) callback->fn.with_userdata(user_data);
            break;
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
    hook->pre_watchers = NULL;
    hook->n_pre_watchers = 0;
    hook->post_watchers = NULL;
    hook->n_post_watchers = 0;
    return hook;
}

static inline void c_evt_hook_free(evt_hook* hook) {
    if (!hook) return;
    if (hook->callbacks) free(hook->callbacks);
    if (hook->pre_watchers) free(hook->pre_watchers);
    if (hook->post_watchers) free(hook->post_watchers);
    free(hook);
}

static inline int c_evt_hook_add_watcher(evt_hook* hook, evt_hook_watcher_fn fn, void* user_data, evt_hook_watcher_type type) {
    if (!hook || !fn) return EVT_HOOK_ERR_INVALID_INPUT;
    if (type == EVT_HOOK_WATCHER_PRE_INVOKED) {
        const size_t new_count = hook->n_pre_watchers + 1;
        evt_hook_watcher* grown = (evt_hook_watcher*) realloc(hook->pre_watchers, new_count * sizeof(evt_hook_watcher));
        if (!grown) return EVT_HOOK_ERR_OOM;
        hook->pre_watchers = grown;
        hook->pre_watchers[hook->n_pre_watchers].fn = fn;
        hook->pre_watchers[hook->n_pre_watchers].user_data = user_data;
        hook->n_pre_watchers = new_count;
        return EVT_HOOK_OK;
    } else if (type == EVT_HOOK_WATCHER_POST_INVOKED) {
        const size_t new_count = hook->n_post_watchers + 1;
        evt_hook_watcher* grown = (evt_hook_watcher*) realloc(hook->post_watchers, new_count * sizeof(evt_hook_watcher));
        if (!grown) return EVT_HOOK_ERR_OOM;
        hook->post_watchers = grown;
        hook->post_watchers[hook->n_post_watchers].fn = fn;
        hook->post_watchers[hook->n_post_watchers].user_data = user_data;
        hook->n_post_watchers = new_count;
        return EVT_HOOK_OK;
    }
    return EVT_HOOK_ERR_INVALID_INPUT;
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
                case EVT_CALLBACK_WITH_TOPIC:               existing = (const void*) callback->fn.with_topic; break;
                case EVT_CALLBACK_WITH_ARGS:                existing = (const void*) callback->fn.with_args; break;
                case EVT_CALLBACK_WITH_USERDATA:            existing = (const void*) callback->fn.with_userdata; break;
                case EVT_CALLBACK_WITH_ARGS_TOPIC:          existing = (const void*) callback->fn.with_args_topic; break;
                case EVT_CALLBACK_WITH_ARGS_USERDATA:       existing = (const void*) callback->fn.with_args_userdata; break;
                case EVT_CALLBACK_WITH_TOPIC_USERDATA:      existing = (const void*) callback->fn.with_topic_userdata; break;
                case EVT_CALLBACK_WITH_ARGS_TOPIC_USERDATA: existing = (const void*) callback->fn.with_args_topic_userdata; break;
                case EVT_CALLBACK_WITH_PAYLOAD:             existing = (const void*) callback->fn.with_payload; break;
                case EVT_CALLBACK_WITH_PAYLOAD_USERDATA:    existing = (const void*) callback->fn.with_payload_userdata; break;
                case EVT_CALLBACK_BARE:                     existing = (const void*) callback->fn.bare; break;
                default: break;
            }
            if (existing == fn && callback->user_data == user_data) {
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
        case EVT_CALLBACK_WITH_TOPIC:               cb->fn.with_topic = (evt_callback_with_topic) fn; break;
        case EVT_CALLBACK_WITH_ARGS:                cb->fn.with_args = (evt_callback_with_args) fn; break;
        case EVT_CALLBACK_WITH_USERDATA:            cb->fn.with_userdata = (evt_callback_with_userdata) fn; break;
        case EVT_CALLBACK_WITH_ARGS_TOPIC:          cb->fn.with_args_topic = (evt_callback_with_args_topic) fn; break;
        case EVT_CALLBACK_WITH_ARGS_USERDATA:       cb->fn.with_args_userdata = (evt_callback_with_args_userdata) fn; break;
        case EVT_CALLBACK_WITH_TOPIC_USERDATA:      cb->fn.with_topic_userdata = (evt_callback_with_topic_userdata) fn; break;
        case EVT_CALLBACK_WITH_ARGS_TOPIC_USERDATA: cb->fn.with_args_topic_userdata = (evt_callback_with_args_topic_userdata) fn; break;
        case EVT_CALLBACK_WITH_PAYLOAD:             cb->fn.with_payload = (evt_callback_with_payload) fn; break;
        case EVT_CALLBACK_WITH_PAYLOAD_USERDATA:    cb->fn.with_payload_userdata = (evt_callback_with_payload_userdata) fn; break;
        case EVT_CALLBACK_BARE:                     cb->fn.bare = (evt_callback_bare) fn; break;
        default:                           cb->fn.bare = NULL; break;
    }

    hook->n_callbacks = new_count;
    return EVT_HOOK_OK;
}

static inline int c_evt_hook_pop_callback(evt_hook* hook, size_t idx) {
    if (!hook) return EVT_HOOK_ERR_INVALID_INPUT;
    if (idx >= hook->n_callbacks) return EVT_HOOK_ERR_INVALID_INPUT;

    /* shift left to fill the gap */
    for (size_t i = idx + 1; i < hook->n_callbacks; ++i) {
        hook->callbacks[i - 1] = hook->callbacks[i];
    }

    hook->n_callbacks -= 1;

    if (hook->n_callbacks == 0) {
        free(hook->callbacks);
        hook->callbacks = NULL;
    } else {
        /* optional shrink; ignore failure to avoid losing callbacks */
        evt_callback* shrunk = (evt_callback*) realloc(hook->callbacks, hook->n_callbacks * sizeof(evt_callback));
        if (shrunk) hook->callbacks = shrunk;
    }

    return EVT_HOOK_OK;
}

static inline int c_evt_hook_invoke(evt_hook* hook, evt_message_payload* payload) {
    if (!hook) return EVT_HOOK_ERR_INVALID_INPUT;

    evt_hook_watcher* watcher = hook->pre_watchers;
    for (size_t i = 0; i < hook->n_pre_watchers; ++i) {
        watcher->fn(hook, EVT_HOOK_WATCHER_PRE_INVOKED, payload, watcher->user_data);
        watcher++;
    }

    for (size_t i = 0; i < hook->n_callbacks; ++i) {
        c_evt_callback_invoke(&hook->callbacks[i], payload);
    }

    watcher = hook->post_watchers;
    for (size_t i = 0; i < hook->n_post_watchers; ++i) {
        watcher->fn(hook, EVT_HOOK_WATCHER_POST_INVOKED, payload, watcher->user_data);
        watcher++;
    }
    return EVT_HOOK_OK;
}

#endif /* C_EVENT_H */