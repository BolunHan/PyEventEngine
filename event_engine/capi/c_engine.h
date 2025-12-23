#ifndef C_ENGINE_H
#define C_ENGINE_H

#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "c_heap_allocator.h"
#include "c_event.h"
#include "c_topic.h"

/* Default capacity if not provided elsewhere */
#ifndef DEFAULT_MQ_CAPACITY
#define DEFAULT_MQ_CAPACITY 0x0fff
#endif

/* Hybrid spin limit (number of busy iterations before blocking) */
#ifndef DEFAULT_MQ_SPIN_LIMIT
#define DEFAULT_MQ_SPIN_LIMIT 0xffff
#endif

/* Default timeout in seconds for blocking operations */
#ifndef DEFAULT_MQ_TIMEOUT_SECONDS
#define DEFAULT_MQ_TIMEOUT_SECONDS 1.0
#endif

/* @brief In-memory ring-buffer message queue
 *
 * The buffer is a flexible array member placed last so the whole queue + buffer
 * can be allocated in one block for better locality and simpler allocation.
 */
typedef struct message_queue {
    heap_allocator* allocator; // allocator for internal allocations
    size_t capacity;            // max number of entries
    size_t head;                // index to pop
    size_t tail;                // index to push
    size_t count;               // current count
    evt_topic* topic;           // topic this queue is bound to (may be NULL)

    pthread_mutex_t mutex;
    pthread_cond_t not_empty;
    pthread_cond_t not_full;

    evt_message_payload* buf[]; // flexible array member: pointers to evt_message_payload
} message_queue;

/* ----------------------------------------------------------------------
 * Signatures and Documentation
 * --------------------------------------------------------------------*/

/**
 * @brief Create a new message queue.
 * @param capacity maximum number of entries (must be > 0)
 * @param topic optional Topic to bind the queue to (may be NULL)
 * @param allocator optional heap_allocator for internal allocations (may be NULL)
 * @return pointer to newly allocated message_queue or NULL on allocation failure
 */
static inline message_queue* c_mq_new(size_t capacity, evt_topic* topic, heap_allocator* allocator);

/**
 * @brief Destroy a message queue.
 * @param mq pointer to message_queue to destroy
 * @param free_self if non-zero free the queue allocation as well (true)
 * @return 0 on success, -1 on invalid argument
 *
 * Note: does not free evt_message_payload pointers still present in the buffer;
 * caller is responsible for draining/freeing them before calling with free_self=1.
 */
static inline int c_mq_free(message_queue* mq, int free_self);

/**
 * @brief Non-blocking put into the queue.
 * @param mq queue pointer
 * @param msg pointer to evt_message_payload (caller-owned)
 * @return 0 on success, -1 on full/invalid args
 */
static inline int c_mq_put(message_queue* mq, evt_message_payload* msg);

/**
 * @brief Non-blocking get from the queue.
 * @param mq queue pointer
 * @param out_msg out parameter to receive evt_message_payload*
 * @return 0 on success, -1 on empty/invalid args
 */
static inline int c_mq_get(message_queue* mq, evt_message_payload** out_msg);

/**
 * @brief Blocking put; waits until space available or timeout.
 * @param mq queue pointer
 * @param msg pointer to evt_message_payload
 * @param timeout_seconds maximum seconds to wait (<=0 means wait forever)
 * @return 0 on success, -1 on timeout/invalid args or error
 */
static inline int c_mq_put_await(message_queue* mq, evt_message_payload* msg, double timeout_seconds);

/**
 * @brief Blocking get; waits until an item is available or timeout.
 * @param mq queue pointer
 * @param out_msg out parameter to receive evt_message_payload*
 * @param timeout_seconds maximum seconds to wait (<=0 means wait forever)
 * @return 0 on success, -1 on timeout/invalid args or error
 */
static inline int c_mq_get_await(message_queue* mq, evt_message_payload** out_msg, double timeout_seconds);

/**
 * @brief Busy-looping put (spin up to max_spin times until space).
 * @param mq queue pointer
 * @param msg pointer to evt_message_payload
 * @param max_spin maximum spin attempts before giving up
 * @return 0 on success, -1 on full/invalid args or if max_spin reached
 */
static inline int c_mq_put_busy(message_queue* mq, evt_message_payload* msg, size_t max_spin);

/**
 * @brief Busy-looping get (spin up to max_spin times until item).
 * @param mq queue pointer
 * @param out_msg out parameter to receive evt_message_payload*
 * @param max_spin maximum spin attempts before giving up
 * @return 0 on success, -1 on empty/invalid args or if max_spin reached
 */
static inline int c_mq_get_busy(message_queue* mq, evt_message_payload** out_msg, size_t max_spin);

/**
 * @brief Hybrid put: busy-spin for a short while then block (timeout does not include spin time).
 * @param mq queue pointer
 * @param msg pointer to evt_message_payload
 * @param timeout_seconds maximum seconds to wait in blocking phase (<=0 means wait forever)
 * @return 0 on success, -1 on timeout/invalid args or error
 */
static inline int c_mq_put_hybrid(message_queue* mq, evt_message_payload* msg, size_t max_spin, double timeout_seconds);

/**
 * @brief Hybrid get: busy-spin for a short while then block (timeout does not include spin time).
 * @param mq queue pointer
 * @param out_msg out parameter to receive evt_message_payload*
 * @param timeout_seconds maximum seconds to wait in blocking phase (<=0 means wait forever)
 * @return 0 on success, -1 on timeout/invalid args or error
 */
static inline int c_mq_get_hybrid(message_queue* mq, evt_message_payload** out_msg, size_t max_spin, double timeout_seconds);

/**
 * @brief Get current occupied count of the queue.
 * @param mq queue pointer
 * @return number of occupied entries, or 0 on invalid arg
 */
static inline size_t c_mq_occupied(message_queue* mq);

/* ----------------------------------------------------------------------
 * Implementations
 * --------------------------------------------------------------------*/

 /* Helper: add seconds (fractional allowed) to timespec */
static inline void timespec_add_seconds(struct timespec* ts, double seconds) {
    time_t sec = (time_t) seconds;
    long nsec = (long) ((seconds - (double) sec) * 1e9);
    ts->tv_sec += sec;
    ts->tv_nsec += nsec;
    if (ts->tv_nsec >= 1000000000L) {
        ts->tv_sec += 1;
        ts->tv_nsec -= 1000000000L;
    }
    else if (ts->tv_nsec < 0) {
        ts->tv_sec -= 1;
        ts->tv_nsec += 1000000000L;
    }
}

/* Create a new queue. Returns NULL on allocation failure. */
static inline message_queue* c_mq_new(size_t capacity, evt_topic* topic, heap_allocator* allocator) {
    if (capacity == 0) return NULL;

    size_t total_bytes = sizeof(message_queue) + capacity * sizeof(evt_message_payload*);
    message_queue* mq;

    if (allocator) {
        mq = (message_queue*) c_heap_request(allocator, total_bytes, 1, &allocator->lock);
    }
    else {
        mq = (message_queue*) calloc(1, total_bytes);
    }
    if (!mq) return NULL;

    mq->capacity = capacity;
    mq->head = mq->tail = mq->count = 0;
    mq->topic = topic;
    mq->allocator = allocator;

    pthread_mutex_init(&mq->mutex, NULL);
    pthread_cond_init(&mq->not_empty, NULL);
    pthread_cond_init(&mq->not_full, NULL);

    return mq;
}

/* Destroy queue. Does not free message payloads pointed to by entries. */
static inline int c_mq_free(message_queue* mq, int free_self) {
    if (!mq) {
        return -1;
    }

    pthread_mutex_lock(&mq->mutex);
    pthread_mutex_unlock(&mq->mutex);
    pthread_cond_destroy(&mq->not_empty);
    pthread_cond_destroy(&mq->not_full);
    pthread_mutex_destroy(&mq->mutex);

    heap_allocator* allocator = mq->allocator;
    if (free_self) {
        if (allocator) {
            c_heap_free(mq, &allocator->lock);
        }
        else {
            free(mq);
        }
    }
    return 0;
}

/* Non-blocking put. Returns 0 on success, -1 on full/invalid args. */
static inline int c_mq_put(message_queue* mq, evt_message_payload* msg) {
    if (!mq || !msg) return -1;
    int ret = -1;
    pthread_mutex_lock(&mq->mutex);
    if (mq->count == mq->capacity) {
        ret = -1; /* full */
    }
    else {
        mq->buf[mq->tail] = msg;
        mq->tail = (mq->tail + 1) % mq->capacity;
        mq->count++;
        pthread_cond_signal(&mq->not_empty);
        ret = 0;
    }
    pthread_mutex_unlock(&mq->mutex);
    return ret;
}

/* Non-blocking get. On success *out_msg is set and returns 0. Returns -1 if empty/invalid args. */
static inline int c_mq_get(message_queue* mq, evt_message_payload** out_msg) {
    if (!mq || !out_msg) return -1;
    int ret = -1;
    pthread_mutex_lock(&mq->mutex);
    if (mq->count == 0) {
        ret = -1; /* empty */
    }
    else {
        *out_msg = mq->buf[mq->head];
        mq->buf[mq->head] = NULL;
        mq->head = (mq->head + 1) % mq->capacity;
        mq->count--;
        pthread_cond_signal(&mq->not_full);
        ret = 0;
    }
    pthread_mutex_unlock(&mq->mutex);
    return ret;
}

/* Blocking put. Waits until space is available. Returns 0 on success, -1 on error. */
static inline int c_mq_put_await(message_queue* mq, evt_message_payload* msg, double timeout_seconds) {
    if (!mq || !msg) return -1;
    pthread_mutex_lock(&mq->mutex);
    struct timespec ts;
    if (timeout_seconds > 0) {
        clock_gettime(CLOCK_REALTIME, &ts);
        timespec_add_seconds(&ts, timeout_seconds);
    }
    while (mq->count == mq->capacity) {
        if (timeout_seconds > 0) {
            int rc = pthread_cond_timedwait(&mq->not_full, &mq->mutex, &ts);
            if (rc == ETIMEDOUT) {
                pthread_mutex_unlock(&mq->mutex);
                return -1;
            }
            if (rc != 0 && rc != EINTR) {
                pthread_mutex_unlock(&mq->mutex);
                return -1;
            }
        }
        else {
            pthread_cond_wait(&mq->not_full, &mq->mutex);
        }
    }
    mq->buf[mq->tail] = msg;
    mq->tail = (mq->tail + 1) % mq->capacity;
    mq->count++;
    pthread_cond_signal(&mq->not_empty);
    pthread_mutex_unlock(&mq->mutex);
    return 0;
}

/* Blocking get. Waits until an item is available. Returns 0 on success, -1 on error. */
static inline int c_mq_get_await(message_queue* mq, evt_message_payload** out_msg, double timeout_seconds) {
    if (!mq || !out_msg) return -1;
    pthread_mutex_lock(&mq->mutex);
    struct timespec ts;
    if (timeout_seconds > 0) {
        clock_gettime(CLOCK_REALTIME, &ts);
        timespec_add_seconds(&ts, timeout_seconds);
    }
    while (mq->count == 0) {
        if (timeout_seconds > 0) {
            int rc = pthread_cond_timedwait(&mq->not_empty, &mq->mutex, &ts);
            if (rc == ETIMEDOUT) {
                pthread_mutex_unlock(&mq->mutex);
                return -1;
            }
            if (rc != 0 && rc != EINTR) {
                pthread_mutex_unlock(&mq->mutex);
                return -1;
            }
        }
        else {
            pthread_cond_wait(&mq->not_empty, &mq->mutex);
        }
    }
    *out_msg = mq->buf[mq->head];
    mq->buf[mq->head] = NULL;
    mq->head = (mq->head + 1) % mq->capacity;
    mq->count--;
    pthread_cond_signal(&mq->not_full);
    pthread_mutex_unlock(&mq->mutex);
    return 0;
}

/* Busy-looping put (spin up to max_spin times until space). */
static inline int c_mq_put_busy(message_queue* mq, evt_message_payload* msg, size_t max_spin) {
    if (!mq || !msg) return -1;
    for (size_t i = 0; i < max_spin; ++i) {
        pthread_mutex_lock(&mq->mutex);
        if (mq->count < mq->capacity) {
            mq->buf[mq->tail] = msg;
            mq->tail = (mq->tail + 1) % mq->capacity;
            mq->count++;
            pthread_cond_signal(&mq->not_empty);
            pthread_mutex_unlock(&mq->mutex);
            return 0;
        }
        pthread_mutex_unlock(&mq->mutex);
        sched_yield();
    }
    return -1;
}

/* Busy-looping get (spin up to max_spin times until item). */
static inline int c_mq_get_busy(message_queue* mq, evt_message_payload** out_msg, size_t max_spin) {
    if (!mq || !out_msg) return -1;
    for (size_t i = 0; i < max_spin; ++i) {
        pthread_mutex_lock(&mq->mutex);
        if (mq->count > 0) {
            *out_msg = mq->buf[mq->head];
            mq->buf[mq->head] = NULL;
            mq->head = (mq->head + 1) % mq->capacity;
            mq->count--;
            pthread_cond_signal(&mq->not_full);
            pthread_mutex_unlock(&mq->mutex);
            return 0;
        }
        pthread_mutex_unlock(&mq->mutex);
        sched_yield();
    }
    return -1;
}

/* Hybrid put: busy-spin for max_spin iterations then block */
static inline int c_mq_put_hybrid(message_queue* mq, evt_message_payload* msg, size_t max_spin, double timeout_seconds) {
    if (!mq || !msg) return -1;
    if (c_mq_put_busy(mq, msg, max_spin) == 0) {
        return 0;
    }
    // After spinning, fallback to blocking with timeout (timeout does not include spin time)
    return c_mq_put_await(mq, msg, timeout_seconds);
}

/* Hybrid get: busy-spin for max_spin iterations then block */
static inline int c_mq_get_hybrid(message_queue* mq, evt_message_payload** out_msg, size_t max_spin, double timeout_seconds) {
    if (!mq || !out_msg) return -1;
    if (c_mq_get_busy(mq, out_msg, max_spin) == 0) {
        return 0;
    }
    // After spinning, fallback to blocking with timeout (timeout does not include spin time)
    return c_mq_get_await(mq, out_msg, timeout_seconds);
}

/* Get current occupied count */
static inline size_t c_mq_occupied(message_queue* mq) {
    if (!mq) return 0;
    pthread_mutex_lock(&mq->mutex);
    size_t n = mq->count;
    pthread_mutex_unlock(&mq->mutex);
    return n;
}

#endif /* C_ENGINE_H */