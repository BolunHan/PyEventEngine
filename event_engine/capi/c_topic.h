#ifndef C_TOPIC_H
#define C_TOPIC_H

#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>
#include <regex.h>

#include "c_heap_allocator.h"
#include "c_strmap.h"
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

#ifndef DEFAULT_WILDCARD_BRACKETS
#define DEFAULT_WILDCARD_BRACKETS "{}"
#endif

#ifndef DEFAULT_WILDCARD_MARKER
#define DEFAULT_WILDCARD_MARKER '+'
#endif

#ifndef DEFAULT_PATTERN_DELIM
#define DEFAULT_PATTERN_DELIM '/'
#endif

static strmap* GLOBAL_INTERNAL_MAP = NULL;

typedef enum evt_topic_type {
    TOPIC_PART_EXACT = 0,
    TOPIC_PART_ANY = 1,
    TOPIC_PART_RANGE = 2,
    TOPIC_PART_PATTERN = 3
} evt_topic_type;

union evt_topic_part_variant;

// Common header — must be first in every variant
typedef struct evt_topic_part {
    evt_topic_type ttype;
    union evt_topic_part_variant* next;
} evt_topic_part;

// Exact match: literal string segment
typedef struct evt_topic_exact {
    evt_topic_part header;
    char* part;
    size_t part_len;
} evt_topic_exact;

// Wildcard: matches any single segment (e.g., '+')
// Optional name for binding (e.g., "+user_id")
typedef struct evt_topic_any {
    evt_topic_part header;
    char* name;      // may be NULL
    size_t name_len;
} evt_topic_any;

// Range: matches one of several literals, like "(user|admin|guest)"
typedef struct evt_topic_range {
    evt_topic_part header;
    char** options;         // array of option string.
    size_t* option_length;  // length of each option
    size_t num_options;     // count
    char* literal;          // original literal string (for reference)
    size_t literal_len;     // length of literal string
} evt_topic_range;

// Pattern: full regex on the entire topic key (not per-part!)
// NOTE: Typically only allowed as a *single* part in a topic,
//       e.g., evt_topic = [ evt_topic_pattern ]
typedef struct evt_topic_pattern {
    evt_topic_part header;
    char* pattern;
    size_t pattern_len;
} evt_topic_pattern;

// Unified evt_topic_part_variant as a tagged union
typedef union evt_topic_part_variant {
    evt_topic_part header;
    evt_topic_exact exact;
    evt_topic_any any;
    evt_topic_range range;
    evt_topic_pattern pattern;
} evt_topic_part_variant;

// Full topic = sequence of parts + metadata
typedef struct evt_topic {
    evt_topic_part_variant* parts;        // head of linked list
    size_t n;                // number of parts
    uint64_t hash;           // cached hash (for fast compare)
    char* key;               // interned key string, e.g., "a.b.c"
    size_t key_len;
    int is_exact;
    heap_allocator* allocator;  // allocator used for all internal allocations
} evt_topic;

typedef struct evt_topic_match {
    int matched;                        // 1 if matched, for this part alone, 0 otherwise
    evt_topic_part_variant* part_a;                  // matched part from topic_a
    evt_topic_part_variant* part_b;                  // matched part from topic_b
    char* literal;                      // matched literal string, which is a borrowed pointer from part_a or part_b, if there is any.
    size_t literal_len;                 // length of matched literal
    struct evt_topic_match* next;  // next match result in linked list
    heap_allocator* allocator;         // allocator used for this result
} evt_topic_match;

// --- Function Declarations ---

/*
* @brief Get the global internal map for topic key deduplication.
*
* @param allocator The heap_allocator to use if the map needs to be created.
* @param with_lock Whether to use mutex.
* @return The global ByteMapHeader for internalized topics.
*/
static inline strmap* c_get_global_internal_map(heap_allocator* allocator, int with_lock);

/*
* @brief Create a new evt_topic from a key string using the given allocator.
*
* @param key The topic key string.
* @param key_len The length of the key string. If 0, the length is determined using strlen.
* @param allocator The heap_allocator to use for internal allocations. If NULL, standard malloc/free are used.
* @param with_lock Whether to use mutex.
* @return Pointer to a new evt_topic on success; NULL on failure.
*/
static inline evt_topic* c_topic_new(const char* key, size_t key_len, heap_allocator* allocator, int with_lock);

/*
* @brief Free a evt_topic and all its parts
*
* @param topic The evt_topic to free.
* @param free_self Whether to free the evt_topic structure itself (1) or just its parts
* @param with_lock Whether to use mutex.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_free(evt_topic* topic, int free_self, int with_lock);

/*
* @brief Internalize the topic key string into a global map for deduplication.
*
* @param topic The evt_topic to internalize.
* @param key The topic key string.
* @param key_len The length of the key string.
* @param with_lock Whether to use mutex.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_internalize(evt_topic* topic, const char* key, size_t key_len, int with_lock);

/*
* @brief Append a part to the evt_topic.
* For a manual control of initializing evt_topic parts.
* Note that in this way, the evt_topic is not internalized automatically and key literal is not updated.
*
* @param topic The evt_topic to append to.
* @param s The part string.
* @param len The length of the part string. If 0, the length is determined using strlen.
* @param ttype The evt_topic_type of the part.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_append(evt_topic* topic, const char* s, size_t len, evt_topic_type ttype, int with_lock);

/*
* @brief Parse a topic key string into its constituent parts and populate the evt_topic structure.
*
* @note for a Range topic part, the option[] array does not owns the memory, but the literal field does.
*
* @param topic The evt_topic to populate.
* @param key The topic key string.
* @param key_len The length of the key string. If 0, the length is determined using strlen.
* @param with_lock Whether to use mutex.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_parse(evt_topic* topic, const char* key, size_t key_len, int with_lock);

/*
* @brief Assign a new key to an existing evt_topic, re-parsing and internalizing it.
* Suitable for lazy initialization or reassignment.
*
* @param topic The evt_topic to assign to.
* @param key The new topic key string.
* @param key_len The length of the key string. If 0, the length is determined using strlen.
* @param with_lock Whether to use mutex.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_assign(evt_topic* topic, const char* key, size_t key_len, int with_lock);

/*
* @brief Update the internalized key literal of the evt_topic based on its parts.
* Useful after manual modifications to the parts.
*
* @param topic The evt_topic to update.
* @param with_lock Whether to use mutex.
* @return 0 on success, -1 on failure.
*/
static inline int c_topic_update_literal(evt_topic* topic, int with_lock);

/*
* @brief Match two evt_topics and produce a linked list of evt_topic_match.
*
* @param topic_a The first evt_topic to match.
* @param topic_b The second evt_topic to match.
* @param out Pointer to store the head of the resulting evt_topic_match linked list. If NULL, a new list is created, with the allocator from topic_a.
* @param with_lock Whether to use mutex.
*/
static inline evt_topic_match* c_topic_match(evt_topic* topic_a, evt_topic* topic_b, evt_topic_match* out, int with_lock);

/*
* @brief New a evt_topic_match and link to the previous node, if provided.
*
* @param prev The previous node, can be NULL if there is not any.
* @param allocator The allocator used for this
* @param with_lock Whether to use mutex.
*/
static inline evt_topic_match* c_topic_match_new(evt_topic_match* prev, heap_allocator* allocator, int with_lock);

/*
* @brief Free a linked list of evt_topic_match.
*
* @param res The head of the evt_topic_match linked list to free.
* @param with_lock Whether to use mutex.
*/
static inline void c_topic_match_free(evt_topic_match* res, int with_lock);

/*
* @brief Efficiently match two evt_topics and return 1 if they match, 0 otherwise.
* This function does not allocate or fill match result structures.
*
* @param topic_a The first evt_topic to match.
* @param topic_b The second evt_topic to match.
* @return 1 if matched, 0 otherwise.
* @param with_lock Whether to use mutex.
*/
static inline int c_topic_match_bool(evt_topic* topic_a, evt_topic* topic_b);

// --- Implementations ---

static inline strmap* c_get_global_internal_map(heap_allocator* allocator, int with_lock) {
    if (!GLOBAL_INTERNAL_MAP) {
        GLOBAL_INTERNAL_MAP = c_strmap_new(0, allocator, with_lock);
    }
    return GLOBAL_INTERNAL_MAP;
}

static inline int c_heap_lock(heap_allocator* allocator, int with_lock) {
    if (!with_lock || !allocator) return 0;
    pthread_mutex_t* lock = &allocator->lock;
    if (pthread_mutex_lock(lock)) return -1;
    return 0;
}

static inline void c_heap_unlock(heap_allocator* allocator, int with_lock) {
    if (!with_lock || !allocator) return;
    pthread_mutex_t* lock = &allocator->lock;
    pthread_mutex_unlock(lock);
}

static inline evt_topic* c_topic_new(const char* key, size_t key_len, heap_allocator* allocator, int with_lock) {
    // Note that when key is NULL, key_len is ignored
    if (key && key_len == 0) {
        key_len = strlen(key);
    }
    else if (!key) {
        key_len = 0;
    }

    if (key && GLOBAL_INTERNAL_MAP) {
        evt_topic* internalized = NULL;
        if (c_strmap_get(GLOBAL_INTERNAL_MAP, key, key_len, (void**) &internalized) == STRMAP_OK) return internalized;
    }

    evt_topic* topic;
    c_heap_lock(allocator, with_lock);

    if (allocator) {
        topic = (evt_topic*) c_heap_request(allocator, sizeof(evt_topic), 1, NULL);
    }
    else {
        topic = (evt_topic*) malloc(sizeof(evt_topic));
    }
    if (!topic) goto unlock_and_exit;

    topic->parts = NULL;
    topic->n = 0;
    topic->hash = 0;
    topic->key = NULL;
    topic->key_len = 0;
    topic->is_exact = 1; // Always initialize as exact
    topic->allocator = allocator;

    // If no key provided, return empty topic and not internalized
    if (!key || key_len == 0) {
        goto unlock_and_exit;
    }

    if (c_topic_parse(topic, key, key_len, 0) != 0) {
        c_topic_free(topic, 1, 0);
        topic = NULL;
        goto unlock_and_exit;
    }

    // Assign and internalize key
    if (c_topic_internalize(topic, key, key_len, 0) != 0) {
        c_topic_free(topic, 1, 0);
        topic = NULL;
    }

unlock_and_exit:
    c_heap_unlock(allocator, with_lock);
    return topic;
}

static inline int c_topic_free(evt_topic* topic, int free_self, int with_lock) {
    if (!topic) return -1;

    heap_allocator* allocator = topic->allocator;
    c_heap_lock(allocator, with_lock);

    evt_topic_part_variant* curr = topic->parts;
    while (curr) {
        evt_topic_part_variant* next = curr->header.next;

        switch (curr->header.ttype) {
            case TOPIC_PART_EXACT:
            {
                if (allocator) {
                    c_heap_free(curr->exact.part, NULL);
                    c_heap_free(curr, NULL);
                }
                else {
                    free(curr->exact.part);
                    free(curr);
                }
                break;
            }
            case TOPIC_PART_ANY:
            {
                if (allocator) {
                    c_heap_free(curr->any.name, NULL);
                    c_heap_free(curr, NULL);
                }
                else {
                    free(curr->any.name);
                    free(curr);
                }
                break;
            }
            case TOPIC_PART_RANGE:
            {
                if (allocator) {
                    c_heap_free(curr->range.options, NULL);
                    c_heap_free(curr->range.literal, NULL);
                    c_heap_free(curr, NULL);
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
                if (allocator) {
                    c_heap_free(curr->pattern.pattern, NULL);
                    c_heap_free(curr, NULL);
                }
                else {
                    free(curr->pattern.pattern);
                    free(curr);
                }
                break;
            }
            default:
                // Unknown type
                if (allocator) {
                    c_heap_free(curr, NULL);
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
        evt_topic* internalized = NULL;
        if (c_strmap_get(GLOBAL_INTERNAL_MAP, topic->key, topic->key_len, (void**) &internalized) == STRMAP_OK && internalized == topic) {
            c_strmap_pop(GLOBAL_INTERNAL_MAP, topic->key, topic->key_len, NULL, 0);
        }
    }

    topic->key = NULL;
    topic->parts = NULL;
    topic->n = 0;
    topic->hash = 0;
    topic->is_exact = 1; // Always reset to exact

    if (free_self) {
        if (allocator) {
            c_heap_free(topic, 0);
        }
        else {
            free(topic);
        }
    }

    c_heap_unlock(allocator, with_lock);
    return 0;
}

static inline int c_topic_internalize(evt_topic* topic, const char* key, size_t key_len, int with_lock) {
    if (!topic || !key) return -1;

    heap_allocator* allocator = topic->allocator;
    c_heap_lock(allocator, with_lock);
    int ret_code = -1;

    // Step 1: Get global internal map
    if (!GLOBAL_INTERNAL_MAP) {
        c_get_global_internal_map(topic->allocator, 0);
        if (!GLOBAL_INTERNAL_MAP) goto unlock_and_exit;
    }

    // Step 2: Deregister previous key if any
    if (topic->key) {
        evt_topic* existing = NULL;
        c_strmap_get(GLOBAL_INTERNAL_MAP, topic->key, topic->key_len, (void**) &existing);
        if (existing == topic) {
            c_strmap_pop(GLOBAL_INTERNAL_MAP, topic->key, topic->key_len, NULL, 0);
        }
        // To avoid dangling pointers on c_strmap_set failed, clear previous key info.
        topic->key = NULL;
        topic->key_len = 0;
        topic->hash = 0;
    }

    // Step 3: Register topic
    strmap_entry* entry = NULL;
    if (c_strmap_set(GLOBAL_INTERNAL_MAP, key, key_len, (void*) topic, &entry, 0) != STRMAP_OK) goto unlock_and_exit;

    // Step 3: Log the internalized key
    topic->key = (char*) entry->key;
    topic->key_len = entry->key_length;
    topic->hash = entry->hash;

    // Already internalized
    ret_code = 0;

unlock_and_exit:
    c_heap_unlock(allocator, with_lock);
    return ret_code;
}

static inline int c_topic_append(evt_topic* topic, const char* s, size_t len, evt_topic_type ttype, int with_lock) {
    if (!topic || !s) return -1;
    if (len == 0) len = strlen(s);
    if (!len) return -1;

    heap_allocator* allocator = topic->allocator;
    c_heap_lock(allocator, with_lock);
    int ret_code = -1;

    char* internal;
    if (allocator) {
        internal = (char*) c_heap_request(allocator, len + 1, 1, NULL);
    }
    else {
        internal = (char*) malloc(len + 1);
    }

    if (!internal) goto unlock_and_exit;
    memcpy(internal, s, len);
    internal[len] = '\0';

    // Append to topic parts
    evt_topic_part_variant* tp;
    if (allocator) {
        tp = (evt_topic_part_variant*) c_heap_request(allocator, sizeof(evt_topic_part_variant), 1, NULL);
        if (!tp) {
            if (allocator) {
                c_heap_free(internal, 0);
            }
            else {
                free(internal);
            }
            goto unlock_and_exit;
        }
    }
    else {
        tp = (evt_topic_part_variant*) malloc(sizeof(evt_topic_part_variant));
        if (!tp) {
            free(internal);
            goto unlock_and_exit;
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
            if (allocator) {
                options = (char**) c_heap_request(allocator, option_count * (sizeof(char*) + sizeof(size_t)), 1, NULL);
            }
            else {
                options = (char**) malloc(option_count * (sizeof(char*) + sizeof(size_t)));
            }
            if (!options) {
                if (allocator) {
                    c_heap_free(internal, 0);
                    c_heap_free(tp, 0);
                }
                else {
                    free(internal);
                    free(tp);
                }
                goto unlock_and_exit;
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
            if (allocator) {
                c_heap_free(internal, 0);
                c_heap_free(tp, 0);
            }
            else {
                free(internal);
                free(tp);
            }
            goto unlock_and_exit;
        }
    }

    // Append to linked list
    if (!topic->parts) {
        topic->parts = tp;
    }
    else {
        evt_topic_part_variant* curr = topic->parts;
        while (curr->header.next) {
            curr = curr->header.next;
        }
        curr->header.next = tp;
    }

    topic->n += 1;
    if (ttype != TOPIC_PART_EXACT) {
        topic->is_exact = 0;
    }
    ret_code = 0;

unlock_and_exit:
    c_heap_unlock(allocator, with_lock);
    return ret_code;
}

static inline int c_topic_parse(evt_topic* topic, const char* key, size_t key_len, int with_lock) {
    if (!topic || !key) return -1;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return -1;

    heap_allocator* allocator = topic->allocator;
    c_heap_lock(allocator, with_lock);
    int ret_code = -1;

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
                    if (c_topic_append(topic, key + content_start, content_len, TOPIC_PART_PATTERN, with_lock) != 0) {
                        goto unlock_and_exit;
                    }
                    i = j + 2; /* advance past "/." */
                    found_close = 1;
                    break;
                }
                j++;
            }

            if (!found_close) {
                goto unlock_and_exit; /* unclosed pattern */
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
                if (c_topic_append(topic, tok + 1, token_len - 1, TOPIC_PART_ANY, with_lock) != 0) {
                    goto unlock_and_exit;
                }
            }
            else if (token_len >= 3 &&
                tok[0] == DEFAULT_WILDCARD_BRACKETS[0] &&
                tok[token_len - 1] == DEFAULT_WILDCARD_BRACKETS[1]) {
                if (c_topic_append(topic, tok + 1, token_len - 2, TOPIC_PART_ANY, with_lock) != 0) {
                    goto unlock_and_exit;
                }
            }
            else if (token_len >= 3 &&
                tok[0] == DEFAULT_RANGE_BRACKETS[0] &&
                tok[token_len - 1] == DEFAULT_RANGE_BRACKETS[1]) {
                if (c_topic_append(topic, tok + 1, token_len - 2, TOPIC_PART_RANGE, with_lock) != 0) {
                    goto unlock_and_exit;
                }
            }
            else {
                if (c_topic_append(topic, tok, token_len, TOPIC_PART_EXACT, with_lock) != 0) {
                    goto unlock_and_exit;
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
    ret_code = 0;

unlock_and_exit:
    c_heap_unlock(allocator, with_lock);
    return ret_code;
}

static inline int c_topic_assign(evt_topic* topic, const char* key, size_t key_len, int with_lock) {
    if (!topic || !key) return -1;

    heap_allocator* allocator = topic->allocator;
    c_heap_lock(allocator, with_lock);
    int ret_code = -1;

    // Free existing parts
    c_topic_free(topic, 0, 0);

    topic->parts = NULL;
    topic->n = 0;
    topic->hash = 0;
    topic->key = NULL;
    topic->key_len = 0;

    // Parse new key
    if (c_topic_parse(topic, key, key_len, 0) != 0) {
        goto unlock_and_exit;
    }

    // Internalize new key
    if (c_topic_internalize(topic, key, key_len, 0) != 0) {
        goto unlock_and_exit;
    }
    ret_code = 0;

unlock_and_exit:
    c_heap_unlock(allocator, with_lock);
    return ret_code;
}

static inline int c_topic_update_literal(evt_topic* topic, int with_lock) {
    if (!topic) return -1;

    heap_allocator* allocator = topic->allocator;
    c_heap_lock(allocator, with_lock);
    int ret_code = -1;

    // Reconstruct key literal from parts
    size_t total_len = 0;
    evt_topic_part_variant* curr = topic->parts;
    while (curr) {
        switch (curr->header.ttype) {
            case TOPIC_PART_EXACT:
                total_len += curr->exact.part_len;
                break;
                // case TOPIC_PART_ANY:
                //     total_len += 1 + curr->any.name_len; // + for wildcard marker
                //     break;
            case TOPIC_PART_ANY:
                total_len += 2 + curr->any.name_len; // + for wildcard marker
                break;
            case TOPIC_PART_RANGE:
                total_len += 2 + curr->range.literal_len; // +2 for brackets
                break;
            case TOPIC_PART_PATTERN:
                total_len += 2 + curr->pattern.pattern_len; // +2 for delimiters
                break;
            default:
                goto unlock_and_exit;
        }
        if (curr->header.next) {
            total_len += 1; // for separator
        }
        curr = curr->header.next;
    }

    char* key_literal;
    heap_allocator* heap_allocator = topic->allocator;
    if (heap_allocator) {
        key_literal = (char*) c_heap_request(heap_allocator, total_len + 1, 1, 0);
    }
    else {
        key_literal = (char*) malloc(total_len + 1);
    }
    if (!key_literal) goto unlock_and_exit;

    size_t pos = 0;
    curr = topic->parts;
    while (curr) {
        switch (curr->header.ttype) {
            case TOPIC_PART_EXACT:
                memcpy(&key_literal[pos], curr->exact.part, curr->exact.part_len);
                pos += curr->exact.part_len;
                break;
                // case TOPIC_PART_ANY:
                //     key_literal[pos++] = DEFAULT_WILDCARD_MARKER;
                //     memcpy(&key_literal[pos], curr->any.name, curr->any.name_len);
                //     pos += curr->any.name_len;
                //     break;
            case TOPIC_PART_ANY:
                key_literal[pos++] = DEFAULT_WILDCARD_BRACKETS[0];
                memcpy(&key_literal[pos], curr->any.name, curr->any.name_len);
                pos += curr->any.name_len;
                key_literal[pos++] = DEFAULT_WILDCARD_BRACKETS[1];
                break;
            case TOPIC_PART_RANGE:
                key_literal[pos++] = DEFAULT_RANGE_BRACKETS[0];
                memcpy(&key_literal[pos], curr->range.literal, curr->range.literal_len);
                // literal of the range part has been modified replacing '|' with '\0', so we need to reconstruct it here.
                for (size_t i = 0; i < curr->range.literal_len; i++) {
                    if (key_literal[pos + i] == '\0') {
                        key_literal[pos + i] = DEFAULT_OPTION_SEP;
                    }
                }
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
                if (allocator) {
                    c_heap_free(key_literal, NULL);
                }
                else {
                    free(key_literal);
                }
                goto unlock_and_exit;
        }
        if (curr->header.next) {
            key_literal[pos++] = DEFAULT_TOPIC_SEP;
        }
        curr = curr->header.next;
    }
    key_literal[pos] = '\0';

    // Internalize new key, the temp key_literal must be freed afterwards
    if (c_topic_internalize(topic, key_literal, total_len, 0) != 0) {
        if (allocator) {
            c_heap_free(key_literal, NULL);
        }
        else {
            free(key_literal);
        }
        goto unlock_and_exit;
    }
    // c_topic_internalize will always create a copy in the global map for safety,
    // so we can free the temporary key_literal here.
    if (allocator) {
        c_heap_free(key_literal, NULL);
    }
    else {
        free(key_literal);
    }
    ret_code = 0;

unlock_and_exit:
    c_heap_unlock(allocator, with_lock);
    return ret_code;
}

static inline evt_topic_match* c_topic_match(evt_topic* topic_a, evt_topic* topic_b, evt_topic_match* out, int with_lock) {
    if (!topic_a || !topic_b) {
        return NULL;
    }

    heap_allocator* allocator = topic_a->allocator;

    // Short-circuit 0: Same topic address or same topic literal
    if (topic_a == topic_b || (topic_a->key && topic_b->key && topic_a->key_len && topic_a->key_len == topic_b->key_len && !strcmp(topic_a->key, topic_b->key))) {
        if (out) {
            out->part_a = topic_a->parts;
            out->part_b = topic_b->parts;
            c_topic_match_free(out->next, with_lock);
            out->next = NULL;
            out->matched = 1;
            out->literal = topic_a->key;
            out->literal_len = topic_a->key_len;
            return out;
        }

        evt_topic_match* res = c_topic_match_new(NULL, allocator, with_lock);
        if (!res) return NULL;

        res->part_a = topic_a->parts;
        res->part_b = topic_b->parts;
        res->next = NULL;
        res->matched = 1;
        res->literal = topic_a->key;
        res->literal_len = topic_a->key_len;
        return res;
    }

    evt_topic_part_variant* part_a = topic_a->parts;
    evt_topic_part_variant* part_b = topic_b->parts;
    evt_topic_match* res = out;
    evt_topic_match* tmp_alloc = NULL;
    evt_topic_match* head = res;
    evt_topic_match* tail = NULL;
    evt_topic_part_variant* part_exact;
    evt_topic_part_variant* part_other;
    c_heap_lock(allocator, with_lock);

    while (part_a && part_b) {
        // Step 0: Prepare out node
        if (!res) {
            res = c_topic_match_new(NULL, allocator, 0);
            if (!res) {
                if (tmp_alloc) c_topic_match_free(tmp_alloc, 0);
                goto unlock_and_null;
            }

            // Link to tail if exists
            if (tail) {
                tail->next = res;
            }

            // Track head and tail and temp allocations
            if (!head) head = res;

            if (!tmp_alloc) {
                tmp_alloc = res;
            }
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
            goto unlock_and_return;
        }

        // Step 2: Match exact part against other part
        switch (part_other->header.ttype) {
            case TOPIC_PART_EXACT:
            {
                if (part_exact->exact.part_len == part_other->exact.part_len &&
                    memcmp(part_exact->exact.part, part_other->exact.part, part_exact->exact.part_len) == 0) {
                    res->matched = 1;
                    res->literal = part_exact->exact.part;
                    res->literal_len = part_exact->exact.part_len;
                }
                else {
                    res->matched = 0;
                    goto unlock_and_return;
                }
                break;
            }
            case TOPIC_PART_ANY:
            {
                res->matched = 1;
                res->literal = part_exact->exact.part;
                res->literal_len = part_exact->exact.part_len;
                break;
            }
            case TOPIC_PART_RANGE:
            {
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
                    goto unlock_and_return;
                }
                break;
            }
            case TOPIC_PART_PATTERN:
            {
                regex_t regex;
                int compile_ret = regcomp(&regex, part_other->pattern.pattern, REG_EXTENDED);
                if (compile_ret) {
                    res->matched = 0;
                    goto unlock_and_return;
                }

                int regex_ret = regexec(&regex, part_exact->exact.part, 0, NULL, 0);
                regfree(&regex);
                if (!regex_ret) {
                    res->matched = 1;
                }
                else {
                    res->matched = 0;
                    goto unlock_and_return;
                }
                break;
            }
            default:
            {
                res->matched = 0;
                goto unlock_and_return;
            }
        }

        // Step 3: Onward the loops
        part_a = part_a->header.next;
        part_b = part_b->header.next;
        tail = res;
        res = res->next;
    }

    // Any residual part is consider a mis-match
    if (part_a || part_b) {
        if (!res) {
            res = c_topic_match_new(NULL, allocator, 0);
            if (!res) {
                if (tmp_alloc) c_topic_match_free(tmp_alloc, 0);
                goto unlock_and_null;
            }

            // Link to tail if exists
            if (tail) {
                tail->next = res;
            }

            // Track head and tail and temp allocations
            if (!head) head = res;
        }

        res->part_a = part_a;
        res->part_b = part_b;
        res->matched = 0;
    }

unlock_and_return:
    c_heap_unlock(allocator, with_lock);
    return head;

unlock_and_null:
    c_heap_unlock(allocator, with_lock);
    return NULL;
}

static inline evt_topic_match* c_topic_match_new(evt_topic_match* prev, heap_allocator* allocator, int with_lock) {
    evt_topic_match* res;
    if (allocator) {
        res = (evt_topic_match*) c_heap_request(allocator, sizeof(evt_topic_match), 1, with_lock ? &allocator->lock : NULL);
    }
    else {
        res = (evt_topic_match*) calloc(1, sizeof(evt_topic_match));
    }

    if (!res) return NULL;

    res->allocator = allocator;
    if (prev) prev->next = res;
    return res;
}

static inline void c_topic_match_free(evt_topic_match* res, int with_lock) {
    if (!res) return;

    evt_topic_match* curr = res;
    while (curr) {
        evt_topic_match* next = curr->next;
        heap_allocator* allocator = curr->allocator;

        if (allocator) {
            c_heap_free(curr, with_lock ? &allocator->lock : NULL);
        }
        else {
            free(curr);
        }

        curr = next;
    }
}

static inline int c_topic_match_bool(evt_topic* topic_a, evt_topic* topic_b) {
    if (!topic_a || !topic_b) {
        return 0;
    }
    // Short-circuit: Same topic address or same topic literal
    if (topic_a == topic_b || (topic_a->key && topic_b->key && topic_a->key_len && topic_a->key_len == topic_b->key_len && !strcmp(topic_a->key, topic_b->key))) {
        return 1;
    }
    evt_topic_part_variant* part_a = topic_a->parts;
    evt_topic_part_variant* part_b = topic_b->parts;
    evt_topic_part_variant* part_exact;
    evt_topic_part_variant* part_other;
    while (part_a && part_b) {
        // Determine which part is exact
        if (part_a->header.ttype == TOPIC_PART_EXACT) {
            part_exact = part_a;
            part_other = part_b;
        }
        else if (part_b->header.ttype == TOPIC_PART_EXACT) {
            part_exact = part_b;
            part_other = part_a;
        }
        else {
            // If neither is exact, match fails
            return 0;
        }
        // Match exact part against other part
        switch (part_other->header.ttype) {
            case TOPIC_PART_EXACT:
                if (part_exact->exact.part_len == part_other->exact.part_len &&
                    memcmp(part_exact->exact.part, part_other->exact.part, part_exact->exact.part_len) == 0) {
                    // matched
                }
                else {
                    return 0;
                }
                break;
            case TOPIC_PART_ANY:
                // always matches
                break;
            case TOPIC_PART_RANGE:
            {
                int found = 0;
                for (size_t i = 0; i < part_other->range.num_options; i++) {
                    if (part_other->range.option_length[i] == part_exact->exact.part_len && memcmp(part_other->range.options[i], part_exact->exact.part, part_exact->exact.part_len) == 0) {
                        found = 1;
                        break;
                    }
                }
                if (!found) {
                    return 0;
                }
                break;
            }
            case TOPIC_PART_PATTERN:
            {
                regex_t regex;
                int compile_ret = regcomp(&regex, part_other->pattern.pattern, REG_EXTENDED);
                if (compile_ret) {
                    return 0;
                }
                int regex_ret = regexec(&regex, part_exact->exact.part, 0, NULL, 0);
                regfree(&regex);
                if (regex_ret) {
                    return 0;
                }
                break;
            }
            default:
                return 0;
        }
        part_a = part_a->header.next;
        part_b = part_b->header.next;
    }
    // Any residual part is a mismatch
    if (part_a || part_b) {
        return 0;
    }
    return 1;
}

#endif // C_TOPIC_H