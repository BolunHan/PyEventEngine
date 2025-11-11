#ifndef C_TOPIC_H
#define C_TOPIC_H

#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>
#include <regex.h>

#include "c_allocator.h"
#include "c_bytemap.h"
#include "xxh3.h"

#ifndef DEFAULT_TOPIC_SEP
#define DEFAULT_TOPIC_SEP '.'
#endif

#ifndef DEFAULT_OPTION_SEP
#define DEFAULT_OPTION_SEP '|'
#endif

#ifndef DEFAULT_RANGE_BRACKETS
#define DEFAULT_RANGE_BRACKETS "()"
#endif

#ifndef DEFAULT_WILDCARD_MARKER
#define DEFAULT_WILDCARD_MARKER '+'
#endif

#ifndef DEFAULT_PATTERN_DELIM
#define DEFAULT_PATTERN_DELIM '/'
#endif

static ByteMapHeader* GLOBAL_INTERNAL_MAP = NULL;

typedef enum TopicType {
    TOPIC_PART_EXACT = 0,
    TOPIC_PART_ANY = 1,
    TOPIC_PART_RANGE = 2,
    TOPIC_PART_PATTERN = 3
} TopicType;

union TopicPart;

// Common header — must be first in every variant
typedef struct TopicPartHeader {
    TopicType ttype;
    union TopicPart* next;
} TopicPartHeader;

// Exact match: literal string segment
typedef struct TopicPartExact {
    TopicPartHeader header;
    char* part;
    size_t part_len;
} TopicPartExact;

// Wildcard: matches any single segment (e.g., '+')
// Optional name for binding (e.g., "+user_id")
typedef struct TopicPartAny {
    TopicPartHeader header;
    char* name;      // may be NULL
    size_t name_len;
} TopicPartAny;

// Range: matches one of several literals, like "(user|admin|guest)"
typedef struct TopicPartRange {
    TopicPartHeader header;
    char** options;         // array of option string.
    size_t* option_length;  // length of each option
    size_t num_options;     // count
    char* literal;          // original literal string (for reference)
    size_t literal_len;     // length of literal string
} TopicPartRange;

// Pattern: full regex on the entire topic key (not per-part!)
// NOTE: Typically only allowed as a *single* part in a topic,
//       e.g., Topic = [ TopicPartPattern ]
typedef struct TopicPartPattern {
    TopicPartHeader header;
    char* pattern;
    size_t pattern_len;
} TopicPartPattern;

// Unified TopicPart as a tagged union
typedef union TopicPart {
    TopicPartHeader header;
    TopicPartExact exact;
    TopicPartAny any;
    TopicPartRange range;
    TopicPartPattern pattern;
} TopicPart;

// Full topic = sequence of parts + metadata
typedef struct Topic {
    TopicPart* parts;        // head of linked list
    size_t n;                // number of parts
    uint64_t hash;           // cached hash (for fast compare)
    char* key;               // interned key string, e.g., "a.b.c"
    size_t key_len;
    MemoryAllocator* allocator;  // allocator used for all internal allocations
} Topic;

typedef struct TopicPartMatchResult {
    int matched;                        // 1 if matched, for this part alone, 0 otherwise
    TopicPart* part_a;                  // matched part from topic_a
    TopicPart* part_b;                  // matched part from topic_b
    char* literal;                      // matched literal string, which is a borrowed pointer from part_a or part_b, if there is any.
    size_t literal_len;                 // length of matched literal
    struct TopicPartMatchResult* next;  // next match result in linked list
    MemoryAllocator* allocator;         // allocator used for this result
} TopicPartMatchResult;

// --- Function Declarations ---

/*
* @brief Get the global internal map for topic key deduplication.
*
* @param allocator The MemoryAllocator to use if the map needs to be created.
* @return The global ByteMapHeader for internalized topics.
*/
static inline ByteMapHeader* c_get_global_internal_map(MemoryAllocator* allocator);

/*
* @brief Create a new Topic from a key string using the given allocator.
*
* @param key The topic key string.
* @param key_len The length of the key string. If 0, the length is determined using strlen.
* @param allocator The MemoryAllocator to use for internal allocations. If NULL, standard malloc/free are used.
*/
static inline Topic* c_topic_new(const char* key, size_t key_len, MemoryAllocator* allocator);

/*
* @brief Free a Topic and all its parts
*
* @param topic The Topic to free.
* @param free_self Whether to free the Topic structure itself (1) or just its parts
*/
static inline int c_topic_free(Topic* topic, int free_self);

/*
* @brief Internalize the topic key string into a global map for deduplication.
*
* @param topic The Topic to internalize.
* @param key The topic key string.
* @param key_len The length of the key string.
*/
static inline int c_topic_internalize(Topic* topic, const char* key, size_t key_len);

/*
* @brief Append a part to the Topic.
* For a manual control of initializing Topic parts.
* Note that in this way, the Topic is not internalized automatically and key literal is not updated.
*
* @param topic The Topic to append to.
* @param s The part string.
* @param len The length of the part string. If 0, the length is determined using strlen.
* @param ttype The TopicType of the part.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_append(Topic* topic, const char* s, size_t len, TopicType ttype);

/*
* @brief Parse a topic key string into its constituent parts and populate the Topic structure.
*
* @note for a Range topic part, the option[] array does not owns the memory, but the literal field does.
*
* @param topic The Topic to populate.
* @param key The topic key string.
* @param key_len The length of the key string. If 0, the length is determined using strlen.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_parse(Topic* topic, const char* key, size_t key_len);

/*
* @brief Assign a new key to an existing Topic, re-parsing and internalizing it.
* Suitable for lazy initialization or reassignment.
*
* @param topic The Topic to assign to.
* @param key The new topic key string.
* @param key_len The length of the key string. If 0, the length is determined using strlen.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_assign(Topic* topic, const char* key, size_t key_len);

/*
* @brief Update the internalized key literal of the Topic based on its parts.
* Useful after manual modifications to the parts.
*
* @param topic The Topic to update.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_update_literal(Topic* topic);

/*
* @brief Match two Topics and produce a linked list of TopicPartMatchResult.
*
* @param topic_a The first Topic to match.
* @param topic_b The second Topic to match.
* @param out Pointer to store the head of the resulting TopicPartMatchResult linked list. If NULL, a new list is created, with the allocator from topic_a.
*/
static inline TopicPartMatchResult* c_topic_match(Topic* topic_a, Topic* topic_b, TopicPartMatchResult* out);

/*
* @brief New a TopicPartMatchResult and link to the previous node, if provided.
*
* @param prev The previous node, can be NULL if there is not any.
* @param allocator The allocator used for this
*/
static inline TopicPartMatchResult* c_topic_match_new(TopicPartMatchResult* prev, MemoryAllocator* allocator);

/*
* @brief Free a linked list of TopicPartMatchResult.
*
* @param res The head of the TopicPartMatchResult linked list to free.
*/
static inline void c_topic_match_free(TopicPartMatchResult* res);

// --- Implementations ---

static inline ByteMapHeader* c_get_global_internal_map(MemoryAllocator* allocator) {
    if (!GLOBAL_INTERNAL_MAP) {
        GLOBAL_INTERNAL_MAP = c_bytemap_new(DEFAULT_BYTEMAP_CAPACITY, allocator);
    }
    return GLOBAL_INTERNAL_MAP;
}

static inline Topic* c_topic_new(const char* key, size_t key_len, MemoryAllocator* allocator) {
    // Note that when key is NULL, key_len is ignored
    if (key && key_len == 0) {
        key_len = strlen(key);
    }
    else if (!key) {
        key_len = 0;
    }

    if (key && GLOBAL_INTERNAL_MAP) {
        void* internalized = c_bytemap_get(GLOBAL_INTERNAL_MAP, key, key_len);
        if (internalized != C_BYTEMAP_NOT_FOUND) return (Topic*) internalized;
    }

    Topic* topic;
    if (allocator && allocator->active) {
        topic = (Topic*) c_heap_request(allocator, sizeof(Topic));
    }
    else {
        topic = (Topic*) malloc(sizeof(Topic));
    }
    if (!topic) return NULL;

    topic->parts = NULL;
    topic->n = 0;
    topic->hash = 0;
    topic->key = NULL;
    topic->key_len = 0;
    topic->allocator = allocator;

    // If no key provided, return empty topic and not internalized
    if (!key || key_len == 0) {
        return topic;
    }

    if (c_topic_parse(topic, key, key_len) != 0) {
        c_topic_free(topic, 1);
        return NULL;
    }

    // Assign and internalize key
    if (c_topic_internalize(topic, key, key_len) != 0) {
        c_topic_free(topic, 1);
        return NULL;
    }

    return topic;
}

static inline int c_topic_free(Topic* topic, int free_self) {
    if (!topic) return -1;

    MemoryAllocator* allocator = topic->allocator;

    TopicPart* curr = topic->parts;
    while (curr) {
        TopicPart* next = curr->header.next;

        switch (curr->header.ttype) {
            case TOPIC_PART_EXACT:
            {
                if (allocator && allocator->active) {
                    c_heap_recycle(allocator, curr->exact.part);
                    c_heap_recycle(allocator, curr);
                }
                else {
                    free(curr->exact.part);
                    free(curr);
                }
                break;
            }
            case TOPIC_PART_ANY:
            {
                if (allocator && allocator->active) {
                    c_heap_recycle(allocator, curr->any.name);
                    c_heap_recycle(allocator, curr);
                }
                else {
                    free(curr->any.name);
                    free(curr);
                }
                break;
            }
            case TOPIC_PART_RANGE:
            {
                if (allocator && allocator->active) {
                    c_heap_recycle(allocator, curr->range.options);
                    c_heap_recycle(allocator, curr->range.literal);
                    c_heap_recycle(allocator, curr);
                }
                else {
                    free(curr->range.options);
                    free(curr->range.literal);
                    free(curr);
                }
                break;
            }
            case TOPIC_PART_PATTERN:
            {
                if (allocator && allocator->active) {
                    c_heap_recycle(allocator, curr->pattern.pattern);
                    c_heap_recycle(allocator, curr);
                }
                else {
                    free(curr->pattern.pattern);
                    free(curr);
                }
                break;
            }
            default:
                // Unknown type
                if (allocator && allocator->active) {
                    c_heap_recycle(allocator, curr);
                }
                else {
                    free(curr);
                }
                break;
        }

        curr = next;
    }

    if (GLOBAL_INTERNAL_MAP) {
        // Note: c_bytemap_pop will also free the key string from the map.
        Topic* internalized = (Topic*) c_bytemap_get(GLOBAL_INTERNAL_MAP, topic->key, topic->key_len);
        if (internalized == topic) {
            c_bytemap_pop(GLOBAL_INTERNAL_MAP, topic->key, topic->key_len, NULL);
        }
    }

    topic->key = NULL;
    topic->parts = NULL;
    topic->n = 0;
    topic->hash = 0;

    if (free_self) {
        if (allocator && allocator->active) {
            c_heap_recycle(allocator, topic);
        }
        else {
            free(topic);
        }
    }

    return 0;
}

static inline int c_topic_internalize(Topic* topic, const char* key, size_t key_len) {
    if (!topic || !key) {
        return -1;
    }

    // Step 1: Get global internal map
    if (!GLOBAL_INTERNAL_MAP) {
        c_get_global_internal_map(topic->allocator);
        if (!GLOBAL_INTERNAL_MAP) {
            return -1;
        }
    }

    // Step 2: Register topic
    MapEntry* entry = c_bytemap_set(GLOBAL_INTERNAL_MAP, key, key_len, (void*) topic);
    if (!entry) return -1;

    // Step 3: Log the internalized key
    topic->key = (char*) entry->key;
    topic->key_len = entry->key_length;
    topic->hash = entry->hash;

    // Already internalized
    return 0;
}

static inline int c_topic_append(Topic* topic, const char* s, size_t len, TopicType ttype) {
    if (!topic || !s) return -1;
    if (len == 0) len = strlen(s);
    if (!len) return -1;

    MemoryAllocator* allocator = topic->allocator;

    char* internal;
    if (allocator && allocator->active) {
        // Use custom allocator
        internal = (char*) c_heap_request(allocator, len + 1);
    }
    else {
        internal = (char*) malloc(len + 1);
    }

    if (!internal) return -1;
    memcpy(internal, s, len);
    internal[len] = '\0';

    // Append to topic parts
    TopicPart* tp;
    if (allocator && allocator->active) {
        tp = (TopicPart*) c_heap_request(allocator, sizeof(TopicPart));
        if (!tp) {
            if (allocator && allocator->active) {
                c_heap_recycle(allocator, internal);
            }
            else {
                free(internal);
            }
            return -1;
        }
    }
    else {
        tp = (TopicPart*) malloc(sizeof(TopicPart));
        if (!tp) {
            free(internal);
            return -1;
        }
    }

    switch (ttype) {
        case TOPIC_PART_EXACT:
        {
            tp->header.ttype = TOPIC_PART_EXACT;
            tp->header.next = NULL;
            tp->exact.part = internal;
            tp->exact.part_len = len;
            break;
        }
        case TOPIC_PART_ANY:
        {
            tp->header.ttype = TOPIC_PART_ANY;
            tp->header.next = NULL;
            tp->any.name = internal;
            tp->any.name_len = len;
            break;
        }
        case TOPIC_PART_RANGE:
        {
            // Note: Options are expected to be separated by DEFAULT_OPTION_SEP = '|' or '\0' if reconstructed from internal string.
            // The Options array are allocated with a quick count of DEFAULT_OPTION_SEP or NUL, the allocated buffer might be larger than needed
            size_t option_count = 1;
            for (size_t i = 0; i < len; i++) {
                if (internal[i] == DEFAULT_OPTION_SEP || internal[i] == '\0') {
                    option_count++;
                }
            }

            // Allocate options array
            char** options;
            if (allocator && allocator->active) {
                options = (char**) c_heap_request(allocator, option_count * (sizeof(char*) + sizeof(size_t)));
            }
            else {
                options = (char**) malloc(option_count * (sizeof(char*) + sizeof(size_t)));
            }
            if (!options) {
                if (allocator && allocator->active) {
                    c_heap_recycle(allocator, internal);
                    c_heap_recycle(allocator, tp);
                }
                else {
                    free(internal);
                    free(tp);
                }
                return -1;
            }

            // Assign options array pointing to internal strings
            size_t* option_length = (size_t*) ((char*) options + option_count * sizeof(char*));
            size_t opt_idx = 0;
            char* start = internal;
            option_count = 0; // Reset counting
            for (size_t i = 0; i <= len; i++) {
                if (i == len || internal[i] == DEFAULT_OPTION_SEP || internal[i] == '\0') {
                    size_t opt_len = &internal[i] - start;
                    // Case 1: valid option string
                    if (opt_len) {
                        options[opt_idx] = start;
                        option_length[opt_idx] = opt_len;
                        option_count++;
                        opt_idx++;
                    }
                    // an empty string
                    else {
                        ;
                    }
                    // If DEFAULT_OPTION_SEP is not NUL, which normally is not.
                    // The internal literal string is modified to make each char* option to be nul-terminated.
                    internal[i] = '\0';
                    if (i < len) {
                        start = &internal[i + 1];
                    }
                }
            }

            tp->header.ttype = TOPIC_PART_RANGE;
            tp->header.next = NULL;
            tp->range.options = options;
            tp->range.option_length = option_length;
            tp->range.num_options = option_count;
            tp->range.literal = internal;
            tp->range.literal_len = len;
            break;
        }
        case TOPIC_PART_PATTERN:
        {
            tp->header.ttype = TOPIC_PART_PATTERN;
            tp->header.next = NULL;
            tp->pattern.pattern = internal;
            tp->pattern.pattern_len = len;
            break;
        }
        default:
        {
            // Unknown type
            if (allocator && allocator->active) {
                c_heap_recycle(allocator, internal);
                c_heap_recycle(allocator, tp);
            }
            else {
                free(internal);
                free(tp);
            }
            return -1;
        }
    }

    // Append to linked list
    if (!topic->parts) {
        topic->parts = tp;
    }
    else {
        TopicPart* curr = topic->parts;
        while (curr->header.next) {
            curr = curr->header.next;
        }
        curr->header.next = tp;
    }

    topic->n += 1;
    return 0;
}

static inline int c_topic_parse(Topic* topic, const char* key, size_t key_len) {
    if (!topic || !key) return -1;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return -1;

    size_t i = 0;
    while (i < key_len) {
        /* Check for pattern: "./" */
        if ((i == 0 && key[0] == DEFAULT_PATTERN_DELIM) ||
            (i + 1 < key_len && key[i] == DEFAULT_TOPIC_SEP && key[i + 1] == DEFAULT_PATTERN_DELIM)) {

            size_t content_start = key[i] == DEFAULT_TOPIC_SEP ? i + 2 : 1;
            size_t j = content_start;
            uint8_t found_close = 0;

            while (j < key_len) {
                if ((j == key_len - 1 && key[j] == DEFAULT_PATTERN_DELIM) ||
                    (j + 1 < key_len && key[j] == DEFAULT_PATTERN_DELIM && key[j + 1] == DEFAULT_TOPIC_SEP)) {
                    /* Found closing "/." */
                    size_t content_len = j - content_start;
                    if (c_topic_append(topic, key + content_start, content_len, TOPIC_PART_PATTERN) != 0) {
                        return -1;
                    }
                    i = j + 2; /* advance past "/." */
                    found_close = 1;
                    break;
                }
                j++;
            }

            if (!found_close) {
                return -1; /* unclosed pattern */
            }
            continue;
        }

        /* Parse normal token up to next '.' that is not part of "./" */
        size_t token_start = i;
        size_t token_len = 0;

        while (i < key_len) {
            if (key[i] == DEFAULT_TOPIC_SEP) {
                /* If next char is '/', this '.' is part of "./" → stop here */
                if (i + 1 < key_len && key[i + 1] == DEFAULT_PATTERN_DELIM) {
                    break;
                }
                /* Otherwise, this '.' ends the current token */
                break;
            }
            i++;
            token_len++;
        }

        /* Append token if non-empty */
        if (token_len > 0) {
            const char* tok = key + token_start;

            if (token_len >= 2 &&
                tok[0] == DEFAULT_WILDCARD_MARKER) {
                if (c_topic_append(topic, tok + 1, token_len - 1, TOPIC_PART_ANY) != 0) {
                    return -1;
                }
            }
            else if (token_len >= 3 &&
                tok[0] == DEFAULT_RANGE_BRACKETS[0] &&
                tok[token_len - 1] == DEFAULT_RANGE_BRACKETS[1]) {
                if (c_topic_append(topic, tok + 1, token_len - 2, TOPIC_PART_RANGE) != 0) {
                    return -1;
                }
            }
            else {
                if (c_topic_append(topic, tok, token_len, TOPIC_PART_EXACT) != 0) {
                    return -1;
                }
            }
        }

        /* Consume the terminating '.' only if it's not part of "./" */
        if (i < key_len && key[i] == DEFAULT_TOPIC_SEP) {
            if (i + 1 >= key_len || key[i + 1] != DEFAULT_PATTERN_DELIM) {
                i++; /* consume the separator */
            }
            /* else: leave i at '.' so next loop sees "./" */
        }
    }

    return 0;
}

static inline int c_topic_assign(Topic* topic, const char* key, size_t key_len) {
    if (!topic || !key) return -1;

    // Free existing parts
    c_topic_free(topic, 0);

    topic->parts = NULL;
    topic->n = 0;
    topic->hash = 0;
    topic->key = NULL;
    topic->key_len = 0;

    // Parse new key
    if (c_topic_parse(topic, key, key_len) != 0) {
        return -1;
    }

    // Internalize new key
    if (c_topic_internalize(topic, key, key_len) != 0) {
        return -1;
    }

    return 0;
}

static inline int c_topic_update_literal(Topic* topic) {
    if (!topic) return -1;

    // Reconstruct key literal from parts
    size_t total_len = 0;
    TopicPart* curr = topic->parts;
    while (curr) {
        switch (curr->header.ttype) {
            case TOPIC_PART_EXACT:
                total_len += curr->exact.part_len;
                break;
            case TOPIC_PART_ANY:
                total_len += 1 + curr->any.name_len; // + for wildcard marker
                break;
            case TOPIC_PART_RANGE:
                total_len += 2 + curr->range.literal_len; // +2 for brackets
                break;
            case TOPIC_PART_PATTERN:
                total_len += 2 + curr->pattern.pattern_len; // +2 for delimiters
                break;
            default:
                return -1;
        }
        if (curr->header.next) {
            total_len += 1; // for separator
        }
        curr = curr->header.next;
    }

    char* key_literal;
    if (topic->allocator && topic->allocator->active) {
        key_literal = (char*) c_heap_request(topic->allocator, total_len + 1);
    }
    else {
        key_literal = (char*) malloc(total_len + 1);
    }
    if (!key_literal) return -1;

    size_t pos = 0;
    curr = topic->parts;
    while (curr) {
        switch (curr->header.ttype) {
            case TOPIC_PART_EXACT:
                memcpy(&key_literal[pos], curr->exact.part, curr->exact.part_len);
                pos += curr->exact.part_len;
                break;
            case TOPIC_PART_ANY:
                key_literal[pos++] = DEFAULT_WILDCARD_MARKER;
                memcpy(&key_literal[pos], curr->any.name, curr->any.name_len);
                pos += curr->any.name_len;
                break;
            case TOPIC_PART_RANGE:
                key_literal[pos++] = DEFAULT_RANGE_BRACKETS[0];
                memcpy(&key_literal[pos], curr->range.literal, curr->range.literal_len);
                pos += curr->range.literal_len;
                key_literal[pos++] = DEFAULT_RANGE_BRACKETS[1];
                break;
            case TOPIC_PART_PATTERN:
                key_literal[pos++] = DEFAULT_PATTERN_DELIM;
                memcpy(&key_literal[pos], curr->pattern.pattern, curr->pattern.pattern_len);
                pos += curr->pattern.pattern_len;
                key_literal[pos++] = DEFAULT_PATTERN_DELIM;
                break;
            default:
                if (topic->allocator && topic->allocator->active) {
                    c_heap_recycle(topic->allocator, key_literal);
                }
                else {
                    free(key_literal);
                }
                return -1;
        }
        if (curr->header.next) {
            key_literal[pos++] = DEFAULT_TOPIC_SEP;
        }
        curr = curr->header.next;
    }
    key_literal[pos] = '\0';

    // Internalize new key, the temp key_literal must be freed afterwards
    if (c_topic_internalize(topic, key_literal, total_len) != 0) {
        if (topic->allocator && topic->allocator->active) {
            c_heap_recycle(topic->allocator, key_literal);
        }
        else {
            free(key_literal);
        }
        return -1;
    }
    // c_topic_internalize will always create a copy in the global map for safety,
    // so we can free the temporary key_literal here.
    if (topic->allocator && topic->allocator->active) {
        c_heap_recycle(topic->allocator, key_literal);
    }
    else {
        free(key_literal);
    }
    return 0;
}

static inline TopicPartMatchResult* c_topic_match(Topic* topic_a, Topic* topic_b, TopicPartMatchResult* out) {
    if (!topic_a || !topic_b) {
        return NULL;
    }

    MemoryAllocator* allocator = topic_a->allocator;

    // Short-circuit 0: Same topic address or same topic literal
    if (topic_a == topic_b || (topic_a->key && topic_b->key && topic_a->key_len && topic_a->key_len == topic_b->key_len && !strcmp(topic_a->key, topic_b->key))) {
        if (out) {
            out->part_a = topic_a->parts;
            out->part_b = topic_b->parts;
            c_topic_match_free(out->next);
            out->next = NULL;
            out->matched = 1;
            out->literal = topic_a->key;
            out->literal_len = topic_a->key_len;
            return out;
        }

        TopicPartMatchResult* res = c_topic_match_new(NULL, allocator);
        if (!res) return NULL;

        res->part_a = topic_a->parts;
        res->part_b = topic_b->parts;
        res->next = NULL;
        res->matched = 1;
        res->literal = topic_a->key;
        res->literal_len = topic_a->key_len;
        return res;
    }

    TopicPart* part_a = topic_a->parts;
    TopicPart* part_b = topic_b->parts;
    TopicPartMatchResult* res = out;
    TopicPartMatchResult* tmp_alloc = NULL;
    TopicPartMatchResult* head = res;
    TopicPartMatchResult* tail = NULL;
    TopicPart* part_exact;
    TopicPart* part_other;

    while (part_a && part_b) {
        // Step 0: Prepare out node
        if (!res) {
            res = c_topic_match_new(tail, allocator);
            if (!res) {
                if (tmp_alloc) c_topic_match_free(tmp_alloc);
                return NULL;
            }

            // Track head and tail and temp allocations
            if (!head) head = res;

            if (!tail) tail = res; // the c_topic_match_free auto link to tail, if there is any.

            if (!tmp_alloc) {
                tmp_alloc = res;
            }
            else {
                tmp_alloc->next = res;
            }
        }
        else {
            tail = res;
        }
        res->part_a = part_a;
        res->part_b = part_b;
        res->matched = 0;

        // Step 1: Determine which part is exact
        if (part_a->header.ttype == TOPIC_PART_EXACT) {
            part_exact = part_a;
            part_other = part_b;
        }
        else if (part_b->header.ttype == TOPIC_PART_EXACT) {
            part_exact = part_b;
            part_other = part_a;
        }
        else {
            // Either part is an exact, match fails and early exits
            res->matched = 0;
            return head;
        }

        // Step 2: Match exact part against other part
        switch (part_other->header.ttype) {
            case TOPIC_PART_EXACT:
                if (part_exact->exact.part_len == part_other->exact.part_len &&
                    memcmp(part_exact->exact.part, part_other->exact.part, part_exact->exact.part_len) == 0) {
                    res->matched = 1;
                    res->literal = part_exact->exact.part;
                    res->literal_len = part_exact->exact.part_len;
                }
                else {
                    res->matched = 0;
                    return head;
                }
                break;
            case TOPIC_PART_ANY:
                res->matched = 1;
                res->literal = part_exact->exact.part;
                res->literal_len = part_exact->exact.part_len;
                break;
            case TOPIC_PART_RANGE:
                int found = 0;
                for (size_t i = 0; i < part_other->range.num_options; i++) {
                    if (part_other->range.option_length[i] == part_exact->exact.part_len && memcmp(part_other->range.options[i], part_exact->exact.part, part_exact->exact.part_len) == 0) {
                        res->matched = 1;
                        res->literal = part_exact->exact.part;
                        res->literal_len = part_exact->exact.part_len;
                        found = 1;
                        break;
                    }
                }
                if (!found) {
                    res->matched = 0;
                    return head;
                }
                break;
            case TOPIC_PART_PATTERN:
                regex_t regex;
                int compile_ret = regcomp(&regex, part_other->pattern.pattern, REG_EXTENDED);
                if (compile_ret) {
                    res->matched = 0;
                    return head;
                }

                int regex_ret = regexec(&regex, part_exact->exact.part, 0, NULL, 0);
                if (!regex_ret) {
                    res->matched = 1;
                }
                else {
                    res->matched = 0;
                    return head;
                }
                break;
            default:
                res->matched = 0;
                return head;
        }

        // Step 3: Onward the loops
        part_a = part_a->header.next;
        part_b = part_b->header.next;
        res = res->next;
    }

    // Any residual part is consider a mis-match
    if (part_a || part_b) {
        if (!res) {
            res = c_topic_match_new(tail, allocator);
            if (!res) {
                if (tmp_alloc) c_topic_match_free(tmp_alloc);
                return NULL;
            }

            // Track head and tail and temp allocations
            if (!head) head = res;

            if (!tail) tail = res; // the c_topic_match_free auto link to tail, if there is any.

            if (!tmp_alloc) {
                tmp_alloc = res;
            }
            else {
                tmp_alloc->next = res;
            }
        }

        res->part_a = part_a;
        res->part_b = part_b;
        res->matched = 0;
    }

    return head;
}

static inline TopicPartMatchResult* c_topic_match_new(TopicPartMatchResult* prev, MemoryAllocator* allocator) {
    TopicPartMatchResult* res;
    if (allocator && allocator->active) {
        res = (TopicPartMatchResult*) c_heap_request(allocator, sizeof(TopicPartMatchResult));
    }
    else {
        res = (TopicPartMatchResult*) calloc(1, sizeof(TopicPartMatchResult));
    }

    if (!res) return NULL;

    res->allocator = allocator;
    if (prev) prev->next = res;
    return res;
}

static inline void c_topic_match_free(TopicPartMatchResult* res) {
    if (!res) return;

    TopicPartMatchResult* curr = res;
    while (curr) {
        TopicPartMatchResult* next = curr->next;
        MemoryAllocator* allocator = curr->allocator;

        if (allocator && allocator->active) {
            c_heap_recycle(allocator, curr);
        }
        else {
            free(curr);
        }

        curr = next;
    }
}

#endif // C_TOPIC_H