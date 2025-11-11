#ifndef C_EVENT_H
#define C_EVENT_H

#include <stdlib.h>
#include <stdint.h>
#include <pthread.h>
#include <errno.h>
#include <string.h>
#include <stdatomic.h>

#include "c_topic.h"
#include "c_allocator.h"

/* @brief Message payload stored in the queue
 *
 * This structure holds the message data along with optional
 * metadata such as topic pointer, Python-compatible args/kwargs,
 * and a sequence identifier.
 */
typedef struct MessagePayload {
    Topic* topic;               // optional Topic pointer (borrowed or owned)
    void* args;                 // pointer compatible with Python "args"
    void* kwargs;               // pointer compatible with Python "kwargs"
    uint64_t seq_id;            // optional sequence id (0 if unused)
} MessagePayload;

/* @brief In-memory ring-buffer message queue
 *
 * The buffer is a flexible array member placed last so the whole queue + buffer
 * can be allocated in one block for better locality and simpler allocation.
 */
typedef struct MessageQueue {
    MemoryAllocator* allocator; // allocator for internal allocations
    size_t capacity;            // max number of entries
    size_t head;                // index to pop
    size_t tail;                // index to push
    size_t count;               // current count
    Topic* topic;               // topic this queue is bound to (may be NULL)

    pthread_mutex_t mutex;
    pthread_cond_t not_empty;
    pthread_cond_t not_full;

    MessagePayload* buf[];      // flexible array member: pointers to MessagePayload
} MessageQueue;

/* ----------------------------------------------------------------------
 * Signatures and Documentation
 * --------------------------------------------------------------------*/

/**
 * @brief Create a new message queue.
 * @param capacity maximum number of entries (must be > 0)
 * @param topic optional Topic to bind the queue to (may be NULL)
 * @param allocator optional MemoryAllocator for internal allocations (may be NULL)
 * @return pointer to newly allocated MessageQueue or NULL on allocation failure
 */
static inline MessageQueue* c_mq_new(size_t capacity, Topic* topic, MemoryAllocator* allocator);

/**
 * @brief Destroy a message queue.
 * @param mq pointer to MessageQueue to destroy
 * @param free_self if non-zero free the queue allocation as well (true)
 * @return 0 on success, -1 on invalid argument
 *
 * Note: does not free MessagePayload pointers still present in the buffer;
 * caller is responsible for draining/freeing them before calling with free_self=1.
 */
static inline int c_mq_free(MessageQueue* mq, int free_self);

/**
 * @brief Non-blocking put into the queue.
 * @param mq queue pointer
 * @param msg pointer to MessagePayload (caller-owned)
 * @return 0 on success, -1 if queue full or invalid args
 */
static inline int c_mq_put(MessageQueue* mq, MessagePayload* msg);

/**
 * @brief Non-blocking get from the queue.
 * @param mq queue pointer
 * @param out_msg out parameter to receive MessagePayload*
 * @return 0 on success, -1 if queue empty or invalid args
 */
static inline int c_mq_get(MessageQueue* mq, MessagePayload** out_msg);

/**
 * @brief Blocking put; waits until space available.
 * @param mq queue pointer
 * @param msg pointer to MessagePayload
 * @return 0 on success, -1 on invalid args or error
 */
static inline int c_mq_put_await(MessageQueue* mq, MessagePayload* msg);

/**
 * @brief Blocking get; waits until an item is available.
 * @param mq queue pointer
 * @param out_msg out parameter to receive MessagePayload*
 * @return 0 on success, -1 on invalid args or error
 */
static inline int c_mq_get_await(MessageQueue* mq, MessagePayload** out_msg);

/* ----------------------------------------------------------------------
 * Implementations
 * --------------------------------------------------------------------*/

 /* Create a new queue. Returns NULL on allocation failure. */
static inline MessageQueue* c_mq_new(size_t capacity, Topic* topic, MemoryAllocator* allocator) {
    if (capacity == 0) return NULL;

    size_t total_bytes = sizeof(MessageQueue) + capacity * sizeof(MessagePayload*);
    MessageQueue* mq;

    if (allocator && allocator->active) {
        mq = (MessageQueue*) c_heap_request(allocator, total_bytes);
    }
    else {
        mq = (MessageQueue*) calloc(total_bytes, sizeof(char));
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
static inline int c_mq_free(MessageQueue* mq, int free_self) {
    if (!mq) {
        return 1;
    }

    pthread_mutex_lock(&mq->mutex);
    pthread_mutex_unlock(&mq->mutex);
    pthread_cond_destroy(&mq->not_empty);
    pthread_cond_destroy(&mq->not_full);
    pthread_mutex_destroy(&mq->mutex);

    MemoryAllocator* allocator = mq->allocator;
    if (free_self) {
        if (allocator && allocator->active) {
            c_heap_recycle(allocator, mq);
        }
        else {
            free(mq);
        }
    }
}

/* Non-blocking put. Returns 0 on success, -1 if queue is full or invalid args. */
static inline int c_mq_put(MessageQueue* mq, MessagePayload* msg) {
    if (!mq || !msg) return -1;
    int ret = 0;
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

/* Non-blocking get. On success *out_msg is set and returns 0. Returns -1 if empty or invalid args. */
static inline int c_mq_get(MessageQueue* mq, MessagePayload** out_msg) {
    if (!mq || !out_msg) return -1;
    int ret = 0;
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
static inline int c_mq_put_await(MessageQueue* mq, MessagePayload* msg) {
    if (!mq || !msg) return -1;
    int ret = 0;
    pthread_mutex_lock(&mq->mutex);

    while (mq->count == mq->capacity) {
        pthread_cond_wait(&mq->not_full, &mq->mutex);
    }
    mq->buf[mq->tail] = msg;
    mq->tail = (mq->tail + 1) % mq->capacity;
    mq->count++;
    pthread_cond_signal(&mq->not_empty);

    pthread_mutex_unlock(&mq->mutex);
    return ret;
}

/* Blocking get. Waits until an item is available. Returns 0 on success, -1 on error. */
static inline int c_mq_get_await(MessageQueue* mq, MessagePayload** out_msg) {
    if (!mq || !out_msg) return -1;
    pthread_mutex_lock(&mq->mutex);

    while (mq->count == 0) {
        pthread_cond_wait(&mq->not_empty, &mq->mutex);
    }
    *out_msg = mq->buf[mq->head];
    mq->buf[mq->head] = NULL;
    mq->head = (mq->head + 1) % mq->capacity;
    mq->count--;
    pthread_cond_signal(&mq->not_full);

    pthread_mutex_unlock(&mq->mutex);
    return 0;
}

#endif /* C_EVENT_H */