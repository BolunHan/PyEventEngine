#ifndef C_EVENT_H
#define C_EVENT_H

#include "c_allocator.h"
#include "c_topic.h"

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
    MemoryAllocator* allocator; // allocator for payload data (may be NULL)
} MessagePayload;

#endif /* C_EVENT_H */