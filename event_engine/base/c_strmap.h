#ifndef C_STRMAP_H
#define C_STRMAP_H

#include <string.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <time.h>

#include "xxh3.h"
#include "c_heap_allocator.h"

// ========== Configuration ==========

#ifndef MIN_STRMAP_CAPACITY
#define MIN_STRMAP_CAPACITY 16U
#endif

#ifndef DEFAULT_STRMAP_CAPACITY
#define DEFAULT_STRMAP_CAPACITY 64U
#endif

// ========== Constants ==========

#define STRMAP_OK                0
#define STRMAP_ERR_INVALID_BUF  -1
#define STRMAP_ERR_INVALID_KEY  -2
#define STRMAP_ERR_NOT_FOUND    -3
#define STRMAP_ERR_FULL         -4
#define STRMAP_ERR_EMPTY        -5

// ========== Structs ==========

/**
 * @brief A single open-addressing table slot for the string map.
 */
typedef struct strmap_entry {
    const char* key;              /**< Cloned key bytes (owned by the map, NUL-terminated). */
    size_t key_length;            /**< Length of key (excludes NUL). */
    void* value;                  /**< Opaque value pointer stored by the caller. */
    uint64_t hash;                /**< Cached hash of key for faster probing/rehash. */
    int occupied;                 /**< 1 if slot holds a live entry. */
    int removed;                  /**< 1 if slot is a tombstone (keeps probe chains intact). */
    struct strmap_entry* prev;    /**< Previous entry in insertion-order list. */
    struct strmap_entry* next;    /**< Next entry in insertion-order list. */
} strmap_entry;

/**
 * @brief String-keyed hash map with open addressing and tombstones.
 */
typedef struct strmap {
    heap_allocator* heap_allocator; /**< Optional custom allocator; NULL uses system heap. */
    strmap_entry* table;            /**< Backing array of slots; zeroed on allocation. */
    size_t capacity;                /**< Number of slots in `table`. */
    size_t size;                    /**< Used-slot count since last rehash (live + tombstones). */
    size_t occupied;                /**< Number of live entries. */
    strmap_entry* first;            /**< Head of insertion-order doubly linked list. */
    strmap_entry* last;             /**< Tail of insertion-order doubly linked list. */
    uint64_t salt;                  /**< Per-map hash salt for XXH3. */
} strmap;

#ifndef MAX_STRMAP_CAPACITY
#define MAX_STRMAP_CAPACITY ((size_t)(SIZE_MAX / sizeof(strmap_entry) / 2))
#endif

// ========== Forward Declarations (Public API) ==========

/**
 * @brief Create a new string-keyed open-addressing hash map.
 *
 * Allocates the `strmap` structure and its backing table. When a custom
 * `heap_allocator` is provided, allocator-managed memory is used (already
 * zero-initialized by the allocator). Otherwise, standard heap is used.
 *
 * @param capacity     Initial capacity hint (rounded up to internal minimums).
 *                     Pass 0 to use DEFAULT_STRMAP_CAPACITY. Values below
 *                     MIN_STRMAP_CAPACITY are clamped up. Values above
 *                     MAX_STRMAP_CAPACITY return NULL.
 * @param heap_allocator Optional allocator; pass NULL to use `calloc/free`.
 * @param with_lock    Non-zero to use the allocator's mutex for allocator
 *                     operations performed inside this call.
 * @return Pointer to a new `strmap` on success; NULL on failure.
 */
static inline strmap* c_strmap_new(size_t capacity, heap_allocator* heap_allocator, int with_lock);

/**
 * @brief Remove all entries from the map, freeing cloned keys.
 *
 * Leaves the map and its table allocated but resets iteration links and
 * counters. Table slots are zeroed and ready for reuse.
 *
 * @param map          Map instance (NULL is a no-op).
 */
static inline void c_strmap_clear(strmap* map, int with_lock);

/**
 * @brief Free the map's resources.
 *
 * Frees all cloned keys and the table. If `free_self` is non-zero, also frees
 * the `strmap` struct itself. When a custom `heap_allocator` is used, freeing
 * is performed via that allocator and may be optionally locked via
 * `with_lock`.
 *
 * @param map          Map instance (NULL is a no-op).
 * @param free_self    Non-zero to free the `strmap` object itself.
 * @param with_lock    Non-zero to use the allocator's mutex during frees.
 */
static inline void c_strmap_free(strmap* map, int free_self, int with_lock);

/**
 * @brief Look up a value by key.
 *
 * Performs linear-probing search that correctly traverses tombstones.
 *
 * @param map          Map instance.
 * @param key          NUL-terminated key string.
 * @param key_len      Key length; pass 0 to compute with `strlen`.
 * @param out          Out-parameter for the value on success (must be non-NULL).
 * @return `STRMAP_OK` on success; `STRMAP_ERR_NOT_FOUND` if absent; a negative
 *         error code on invalid arguments.
 */
static inline int c_strmap_get(strmap* map, const char* key, size_t key_len, void** out);

/**
 * @brief Test whether a key exists.
 *
 * @param map          Map instance.
 * @param key          NUL-terminated key string.
 * @param key_len      Key length; pass 0 to compute with `strlen`.
 * @return 1 if present, 0 if absent; negative error code on invalid arguments.
 */
static inline int c_strmap_contains(strmap* map, const char* key, size_t key_len);

/**
 * @brief Rehash the map to a new capacity.
 *
 * Rebuilds the table without tombstones, preserving insertion order links.
 * Typically not needed by callers because `c_strmap_set` grows automatically.
 *
 * @param map          Map instance.
 * @param new_capacity Target capacity (must be > 0 and <= MAX_STRMAP_CAPACITY).
 * @param with_lock    Non-zero to use the allocator's mutex during allocation/free.
 * @return `STRMAP_OK` on success; negative error code on failure/invalid args.
 */
static inline int c_strmap_rehash(strmap* map, size_t new_capacity, int with_lock);

/**
 * @brief Insert or update a key/value pair.
 *
 * Linear-probing with tombstones: scans until an opening to ensure the key
 * does not exist later in the cluster, remembers the first tombstone (if any),
 * and inserts preferentially into the earliest tombstone to reduce probe
 * lengths. Clones and owns the key memory internally.
 *
 * Automatically triggers growth and rehashing when the table becomes too
 * utilized (based on used-slot count, including tombstones).
 *
 * @param map          Map instance.
 * @param key          NUL-terminated key string.
 * @param key_len      Key length; pass 0 to compute with `strlen`.
 * @param value        Value pointer to store (opaque to the map).
 * @param out_entry   Optional out-parameter to receive the strmap_entry pointer.
 * @param with_lock    Non-zero to use the allocator's mutex for allocations.
 * @return `STRMAP_OK` on success; negative error code on invalid args or OOM;
 *         `STRMAP_ERR_FULL` if no slot found (extremely unlikely with growth).
 */
static inline int c_strmap_set(strmap* map, const char* key, size_t key_len, void* value, strmap_entry** out_entry, int with_lock);

/**
 * @brief Remove a key, returning its value if present.
 *
 * Marks the slot as a tombstone (keeps probe-chain integrity) and unlinks the
 * entry from the insertion-order doubly-linked list.
 *
 * @param map          Map instance.
 * @param key          NUL-terminated key string.
 * @param key_len      Key length; pass 0 to compute with `strlen`.
 * @param out          Out-parameter set to the removed value on success; set to
 *                     NULL on not found (when `out` is non-NULL).
 * @param with_lock    Non-zero to use the allocator's mutex for allocations.
 * @return `STRMAP_OK` on success; `STRMAP_ERR_NOT_FOUND` if absent; negative
 *         error code on invalid arguments.
 */
static inline int c_strmap_pop(strmap* map, const char* key, size_t key_len, void** out, int with_lock);

// ========== Iteration Helpers (Forward Declarations) ==========

/**
 * @brief Get the first entry in insertion order.
 * @param map Map instance.
 * @return Pointer to the first live entry, or NULL if empty/NULL map.
 */
static inline strmap_entry* c_strmap_first(strmap* map);

/**
 * @brief Get the last entry in insertion order.
 * @param map Map instance.
 * @return Pointer to the last live entry, or NULL if empty/NULL map.
 */
static inline strmap_entry* c_strmap_last(strmap* map);

/**
 * @brief Get the next entry in insertion order.
 * @param entry Current entry.
 * @return Next live entry or NULL.
 */
static inline strmap_entry* c_strmap_next(strmap_entry* entry);

/**
 * @brief Get the previous entry in insertion order.
 * @param entry Current entry.
 * @return Previous live entry or NULL.
 */
static inline strmap_entry* c_strmap_prev(strmap_entry* entry);

// ========== Utility Functions ==========

static inline uint64_t c_strmap_hash(strmap* map, const char* key, size_t key_len) {
    if (!key) return 0;
    if (!key_len) {
        key_len = strlen(key);
        if (!key_len) return 0;
    }
    if (map->salt) {
        return XXH3_64bits_withSeed(key, key_len, map->salt);
    }
    return XXH3_64bits(key, key_len);
}

static inline const char* c_strmap_clone_key(strmap* map, const char* key, size_t key_len, int with_lock) {
    if (!map || !key) return NULL;

    if (!key_len) {
        key_len = strlen(key);
        if (!key_len) return NULL;
    }

    char* buf;
    heap_allocator* allocator = map->heap_allocator;

    if (allocator) {
        buf = (char*) c_heap_request(allocator, key_len + 1, 1, with_lock ? &allocator->lock : NULL);
    }
    else {
        buf = (char*) calloc(key_len + 1, 1);
    }
    if (!buf) return NULL;
    memcpy(buf, key, key_len);
    return buf;
}

static inline void c_strmap_free_key(strmap* map, const char* key, int with_lock) {
    if (!key) return;
    heap_allocator* allocator = map->heap_allocator;
    if (allocator) {
        c_heap_free((void*) key, with_lock ? &allocator->lock : NULL);
    }
    else {
        free((void*) key);
    }
}

// ========== Public APIs ==========

static inline strmap* c_strmap_new(size_t capacity, heap_allocator* heap_allocator, int with_lock) {
    if (capacity == 0) capacity = DEFAULT_STRMAP_CAPACITY;
    if (capacity < MIN_STRMAP_CAPACITY) capacity = MIN_STRMAP_CAPACITY;
    if (capacity > MAX_STRMAP_CAPACITY) return NULL;

    strmap* map;
    strmap_entry* table;

    if (heap_allocator) {
        pthread_mutex_t* lock = with_lock ? &heap_allocator->lock : NULL;
        map = (strmap*) c_heap_request(heap_allocator, sizeof(strmap), 1, lock);
        if (!map) return NULL;
        map->heap_allocator = heap_allocator;
        table = (strmap_entry*) c_heap_request(heap_allocator, capacity * sizeof(strmap_entry), 1, lock);
        if (!table) {
            c_heap_free((void*) map, lock);
            return NULL;
        }
    }
    else {
        map = (strmap*) calloc(1, sizeof(strmap));
        if (!map) return NULL;
        table = (strmap_entry*) calloc(capacity, sizeof(strmap_entry));
        if (!table) {
            free((void*) map);
            return NULL;
        }
    }
    map->table = table;
    map->capacity = capacity;
    uint64_t seed = (uint64_t) (uintptr_t) map ^ (uint64_t) capacity;
    map->salt = XXH3_64bits(&seed, sizeof(seed)) ^ 0x9E3779B97F4A7C15ULL;
    return map;
}

static inline void c_strmap_clear(strmap* map, int with_lock) {
    if (!map || !map->table) return;

    heap_allocator* heap_allocator = map->heap_allocator;
    pthread_mutex_t* lock = heap_allocator ? &heap_allocator->lock : NULL;
    int locked = 0;

    if (lock && with_lock) {
        if (pthread_mutex_lock(lock) == 0) {
            locked = 1;
        }
    }

    for (size_t i = 0; i < map->capacity; ++i) {
        strmap_entry* e = &map->table[i];
        if (e->occupied) {
            c_strmap_free_key(map, e->key, with_lock);
        }
        memset(e, 0, sizeof(strmap_entry));
    }

    if (locked) {
        pthread_mutex_unlock(lock);
    }

    map->first = map->last = NULL;
    map->size = 0;
    map->occupied = 0;
}

static inline void c_strmap_free(strmap* map, int free_self, int with_lock) {
    if (!map) return;

    heap_allocator* heap_allocator = map->heap_allocator;
    c_strmap_clear(map, with_lock);

    if (heap_allocator) {
        pthread_mutex_t* lock = with_lock ? &heap_allocator->lock : NULL;
        if (map->table) {
            c_heap_free((void*) map->table, lock);
            map->table = NULL;
        }
        if (free_self) {
            c_heap_free((void*) map, lock);
        }
    }
    else {
        if (map->table) {
            free((void*) map->table);
            map->table = NULL;
        }
        if (free_self) {
            free((void*) map);
        }
    }

    return;
}

static inline int c_strmap_get(strmap* map, const char* key, size_t key_len, void** out) {
    if (!map || !map->table || !key) return STRMAP_ERR_INVALID_BUF;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return STRMAP_ERR_INVALID_KEY;

    uint64_t hash = c_strmap_hash(map, key, key_len);
    size_t idx = hash % map->capacity;
    size_t start = idx;
    strmap_entry* entry = &map->table[idx];

    while (entry->occupied || entry->removed) {
        if (entry->occupied &&
            entry->key_length == key_len &&
            memcmp(entry->key, key, key_len) == 0) {
            *out = entry->value;
            return STRMAP_OK;
        }
        idx = (idx + 1) % map->capacity;
        entry = &map->table[idx];
        if (idx == start) break;
    }
    return STRMAP_ERR_NOT_FOUND;
}

static inline int c_strmap_contains(strmap* map, const char* key, size_t key_len) {
    if (!map || !map->table || !key) return STRMAP_ERR_INVALID_BUF;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return STRMAP_ERR_INVALID_KEY;

    uint64_t hash = c_strmap_hash(map, key, key_len);
    size_t idx = hash % map->capacity;
    size_t start = idx;
    strmap_entry* entry = &map->table[idx];

    while (entry->occupied || entry->removed) {
        if (entry->occupied &&
            entry->key_length == key_len &&
            memcmp(entry->key, key, key_len) == 0) {
            return 1;
        }
        idx = (idx + 1) % map->capacity;
        entry = &map->table[idx];
        if (idx == start) break;
    }
    return 0;
}

static inline int c_strmap_rehash(strmap* map, size_t new_capacity, int with_lock) {
    if (!map || new_capacity == 0 || new_capacity > MAX_STRMAP_CAPACITY) return STRMAP_ERR_INVALID_BUF;

    heap_allocator* heap_allocator = map->heap_allocator;
    strmap_entry* new_table;

    if (heap_allocator) {
        new_table = (strmap_entry*) c_heap_request(heap_allocator, new_capacity * sizeof(strmap_entry), 1, with_lock ? &heap_allocator->lock : NULL);
    }
    else {
        new_table = (strmap_entry*) calloc(new_capacity, sizeof(strmap_entry));
    }
    if (!new_table) return STRMAP_ERR_INVALID_BUF;

    strmap_entry* new_first = NULL;
    strmap_entry* new_last = NULL;

    for (strmap_entry* e = map->first; e; e = e->next) {
        size_t idx = e->hash % new_capacity;
        while (new_table[idx].occupied) {
            idx = (idx + 1) % new_capacity;
        }
        new_table[idx] = *e;

        new_table[idx].prev = new_last;
        new_table[idx].next = NULL;
        if (new_last) {
            new_last->next = &new_table[idx];
        }
        else {
            new_first = &new_table[idx];
        }
        new_last = &new_table[idx];
    }

    if (heap_allocator) {
        c_heap_free((void*) map->table, with_lock ? &heap_allocator->lock : NULL);
    }
    else {
        free((void*) map->table);
    }

    map->table = new_table;
    map->capacity = new_capacity;
    map->size = map->occupied;
    map->first = new_first;
    map->last = new_last;
    return STRMAP_OK;
}

static inline int c_strmap_set(strmap* map, const char* key, size_t key_len, void* value, strmap_entry** out_entry, int with_lock) {
    if (!map || !key) return STRMAP_ERR_INVALID_BUF;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return STRMAP_ERR_INVALID_KEY;

    if (map->size * 2 >= map->capacity) {
        size_t new_cap = map->capacity ? map->capacity * 4 : MIN_STRMAP_CAPACITY;
        if (new_cap < map->capacity || new_cap > MAX_STRMAP_CAPACITY) return STRMAP_ERR_INVALID_BUF;
        if (c_strmap_rehash(map, new_cap, with_lock) != STRMAP_OK) return STRMAP_ERR_INVALID_BUF;
    }

    uint64_t hash = c_strmap_hash(map, key, key_len);
    size_t idx = hash % map->capacity;
    size_t start = idx;
    strmap_entry* tombstone = NULL;
    strmap_entry* entry = &map->table[idx];

    while (entry->occupied || entry->removed) {
        if (!entry->occupied && !tombstone) {
            tombstone = entry;
        }
        else if (entry->occupied &&
            entry->key_length == key_len &&
            memcmp(entry->key, key, key_len) == 0) {
            entry->value = value;
            if (out_entry) *out_entry = entry;
            return STRMAP_OK;
        }
        idx = (idx + 1) % map->capacity;
        entry = &map->table[idx];
        if (idx == start) {
            if (!tombstone) return STRMAP_ERR_FULL;
            break;
        }
    }

    if (!tombstone) map->size++;
    entry = tombstone ? tombstone : entry;

    const char* key_copy = c_strmap_clone_key(map, key, key_len, with_lock);
    if (!key_copy) return STRMAP_ERR_INVALID_BUF;

    entry->key = key_copy;
    entry->key_length = key_len;
    entry->value = value;
    entry->hash = hash;
    entry->occupied = 1;
    entry->removed = 0;

    entry->prev = map->last;
    entry->next = NULL;
    if (map->last) {
        map->last->next = entry;
    }
    else {
        map->first = entry;
    }
    map->last = entry;
    map->occupied++;
    if (out_entry) *out_entry = entry;
    return STRMAP_OK;
}

static inline int c_strmap_pop(strmap* map, const char* key, size_t key_len, void** out, int with_lock) {
    if (!map || !key) return STRMAP_ERR_INVALID_BUF;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return STRMAP_ERR_INVALID_KEY;

    uint64_t hash = c_strmap_hash(map, key, key_len);
    size_t idx = hash % map->capacity;
    size_t start = idx;

    while (1) {
        strmap_entry* entry = &map->table[idx];
        if (!entry->occupied && !entry->removed) break;
        if (entry->occupied &&
            entry->key_length == key_len &&
            memcmp(entry->key, key, key_len) == 0) {
            if (out) *out = entry->value;

            if (entry->prev) entry->prev->next = entry->next;
            else map->first = entry->next;
            if (entry->next) entry->next->prev = entry->prev;
            else map->last = entry->prev;

            c_strmap_free_key(map, entry->key, with_lock);
            memset(entry, 0, sizeof(strmap_entry));
            entry->removed = 1;
            map->occupied--;
            return STRMAP_OK;
        }
        idx = (idx + 1) % map->capacity;
        if (idx == start) break;
    }
    if (out) *out = (void*) NULL;
    return STRMAP_ERR_NOT_FOUND;
}

// ========== Iteration Helpers (Definitions) ==========

static inline strmap_entry* c_strmap_first(strmap* map) {
    return map ? map->first : NULL;
}

static inline strmap_entry* c_strmap_last(strmap* map) {
    return map ? map->last : NULL;
}

static inline strmap_entry* c_strmap_next(strmap_entry* entry) {
    return entry ? entry->next : NULL;
}

static inline strmap_entry* c_strmap_prev(strmap_entry* entry) {
    return entry ? entry->prev : NULL;
}

#endif // C_STRMAP_H