#ifndef C_BYTEMAP_H
#define C_BYTEMAP_H

#include <string.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <time.h>

#include "xxh3.h"
#include "c_allocator.h"

// --- Configuration ---

#ifndef MIN_BYTEMAP_CAPACITY
#define MIN_BYTEMAP_CAPACITY 16U
#endif

#ifndef DEFAULT_BYTEMAP_CAPACITY
#define DEFAULT_BYTEMAP_CAPACITY 64U
#endif

// --- Sentinel for "not found" when value can be NULL ---
// Unique address of this symbol is used.
static const void* const C_BYTEMAP_NOT_FOUND = (const void*) &C_BYTEMAP_NOT_FOUND;

// --- Data Structures ---

typedef struct MapEntry {
    char* key;
    size_t key_length;
    void* value;
    uint64_t hash;
    int occupied;
    int removed;
    struct MapEntry* prev;
    struct MapEntry* next;
} MapEntry;

typedef struct ByteMapHeader {
    MemoryAllocator* allocator;
    MapEntry* table;
    size_t capacity;
    size_t size;        // number of live elements
    size_t occupied;    // number of physical occupied slots (entry->occupied == 1)
    MapEntry* first;
    MapEntry* last;
    uint64_t salt;
} ByteMapHeader;

#ifndef MAX_BYTEMAP_CAPACITY
#define MAX_BYTEMAP_CAPACITY ((size_t)(SIZE_MAX / sizeof(MapEntry) / 2))
#endif

// --- Hash helper: support null-terminated strings if key_len == 0 ---
static inline uint64_t c_bytemap_hash(ByteMapHeader* map, const char* key, size_t key_len) {
    if (!key) {
        return 0;
    }

    if (!key_len) {
        key_len = strlen(key);
        if (!key_len) return 0;
    }
    if (map->salt) {
        return XXH3_64bits_withSeed(key, key_len, map->salt);
    }
    else {
        return XXH3_64bits(key, key_len);
    }
}

// --- Key memory management ---
static inline char* c_bytemap_clone_key(MemoryAllocator* allocator, const char* key, size_t key_len) {
    char* buf;

    if (!key_len) {
        key_len = strlen(key);
        if (!key_len) return NULL;
    }

    if (allocator && allocator->active) {
        buf = (char*) c_heap_request(allocator, key_len + 1);
    }
    else {
        buf = (char*) calloc(key_len + 1, 1);
    }

    if (!buf) return NULL;
    memcpy(buf, key, key_len);
    return buf;
}

static inline void c_bytemap_free_key(MemoryAllocator* allocator, char* key) {
    if (!key) return;
    if (allocator && allocator->active) {
        c_heap_recycle(allocator, key);
    }
    else {
        free(key);
    }
}

// --- Constructor ---
static inline ByteMapHeader* c_bytemap_new(size_t capacity, MemoryAllocator* allocator) {
    if (capacity == 0) capacity = DEFAULT_BYTEMAP_CAPACITY;
    if (capacity < MIN_BYTEMAP_CAPACITY) capacity = MIN_BYTEMAP_CAPACITY;

    ByteMapHeader* map;
    MapEntry* table;

    if (allocator && allocator->active) {
        map = (ByteMapHeader*) c_heap_request(allocator, sizeof(ByteMapHeader));
        if (!map) {
            return NULL;
        }

        table = (MapEntry*) c_heap_request(allocator, capacity * sizeof(MapEntry));
        if (!table) {
            c_heap_recycle(allocator, map);
            return NULL;
        }
    }
    else {
        map = (ByteMapHeader*) calloc(1, sizeof(ByteMapHeader));
        if (!map) {
            return NULL;
        }

        table = (MapEntry*) calloc(capacity, sizeof(MapEntry));
        if (!table) {
            free(map);
            return NULL;
        }
    }

    // Explicit init is safe and clear (even if zero-filled)
    // for (size_t i = 0; i < capacity; ++i) {
    //    table[i].occupied = 0;
    //    table[i].removed = 0;
    //    table[i].prev = NULL;
    //    table[i].next = NULL;
    // }

    map->allocator = allocator;
    map->table = table;
    map->capacity = capacity;
    // map->size = 0;
    // map->occupied = 0;
    // map->first = NULL;
    // map->last = NULL;
    uint64_t seed = (uint64_t) (uintptr_t) map ^ (uint64_t) capacity;
    map->salt = XXH3_64bits(&seed, sizeof(seed)) ^ 0x9E3779B97F4A7C15ULL;
    return map;
}

static inline void c_bytemap_clear(ByteMapHeader* map) {
    if (!map || !map->table) return;
    for (size_t i = 0; i < map->capacity; ++i) {
        MapEntry* e = &map->table[i];
        if (e->occupied) {
            c_bytemap_free_key(map->allocator, e->key);
        }
        memset(e, 0, sizeof(MapEntry));
    }
    map->first = map->last = NULL;
    map->size = 0;
    map->occupied = 0;
}

// --- Destructor ---
static inline void c_bytemap_free(ByteMapHeader* map, int free_self) {
    if (!map) {
        return;
    }

    if (map->table) {
        for (size_t i = 0; i < map->capacity; ++i) {
            MapEntry* entry = map->table + i;
            if (entry->occupied) {
                c_bytemap_free_key(map->allocator, entry->key);
            }
        }

        if (map->allocator && map->allocator->active) {
            c_heap_recycle(map->allocator, map->table);
        }
        else {
            free(map->table);
        }
        map->table = NULL;
    }

    if (free_self) {
        if (map->allocator && map->allocator->active) {
            c_heap_recycle(map->allocator, map);
        }
        else {
            free(map);
        }
    }
}

// --- Separate get & contains (without relying on ambiguous NULL) ---

static inline void* c_bytemap_get(ByteMapHeader* map, const char* key, size_t key_len) {
    if (!map || !map->table || !key) return (void*) C_BYTEMAP_NOT_FOUND;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return (void*) C_BYTEMAP_NOT_FOUND;

    uint64_t hash = c_bytemap_hash(map, key, key_len);
    size_t idx = (size_t) (hash % map->capacity);
    size_t start = idx;
    MapEntry* entry = map->table + idx;

    while (entry->occupied || entry->removed) {
        if (entry->occupied &&
            entry->key_length == key_len &&
            memcmp(entry->key, key, key_len) == 0) {
            return entry->value;
        }

        idx = (idx + 1) % map->capacity;
        entry = map->table + idx;
        if (idx == start) {
            break;
        }
    }
    return (void*) C_BYTEMAP_NOT_FOUND;
}

static inline int c_bytemap_contains(ByteMapHeader* map, const char* key, size_t key_len) {
    if (!map || !map->table || !key) return 0;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return 0;

    uint64_t hash = c_bytemap_hash(map, key, key_len);
    size_t idx = (size_t) (hash % map->capacity);
    size_t start = idx;
    MapEntry* entry = map->table + idx;

    while (entry->occupied || entry->removed) {
        if (entry->occupied &&
            entry->key_length == key_len &&
            memcmp(entry->key, key, key_len) == 0) {
            return 1;
        }

        idx = (idx + 1) % map->capacity;
        entry = map->table + idx;
        if (idx == start) {
            break;
        }
    }
    return 0;
}

// --- Rehash ---
static inline int c_bytemap_rehash(ByteMapHeader* map, size_t new_capacity) {
    if (!map || new_capacity == 0 || new_capacity > MAX_BYTEMAP_CAPACITY) return -1;

    MemoryAllocator* alloc = map->allocator;
    MapEntry* new_table;

    if (alloc && alloc->active) {
        new_table = (MapEntry*) c_heap_request(alloc, new_capacity * sizeof(MapEntry));
    }
    else {
        new_table = (MapEntry*) calloc(new_capacity, sizeof(MapEntry));
    }

    if (!new_table) return -1;

    // memset(new_table, 0, new_capacity * sizeof(MapEntry));

    MapEntry* new_first = NULL;
    MapEntry* new_last = NULL;

    for (MapEntry* e = map->first; e != NULL; e = e->next) {
        size_t idx = (size_t) (e->hash % new_capacity);
        while (new_table[idx].occupied) {
            idx = (idx + 1) % new_capacity;
        }
        new_table[idx] = *e; // shallow copy (key/value pointers reused)

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

    if (alloc && alloc->active) {
        c_heap_recycle(alloc, map->table);
    }
    else {
        free(map->table);
    }

    map->table = new_table;
    map->capacity = new_capacity;
    map->size = map->occupied;
    map->first = new_first;
    map->last = new_last;
    return 0;
}

// --- Set ---
static inline MapEntry* c_bytemap_set(ByteMapHeader* map, const char* key, size_t key_len, void* value) {
    if (!map || !key) return NULL;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return NULL;

    if (map->size * 2 >= map->capacity) {
        size_t new_cap = map->capacity ? (map->capacity * 4) : MIN_BYTEMAP_CAPACITY;
        if (new_cap < map->capacity || new_cap > MAX_BYTEMAP_CAPACITY) {
            return NULL; // overflow or max capacity reached
        }
        if (c_bytemap_rehash(map, new_cap) != 0) {
            return NULL;
        }
    }

    uint64_t hash = c_bytemap_hash(map, key, key_len);
    size_t idx = (size_t) (hash % map->capacity);
    size_t start = idx;
    MapEntry* tombstone = NULL;
    MapEntry* entry = map->table + idx;

    while (entry->occupied || entry->removed) {
        if (!entry->occupied) {
            // Tombstone: remember first one
            if (!tombstone) {
                tombstone = entry;
            }
        }
        else {
            // Live entry: check key
            if (entry->key_length == key_len &&
                memcmp(entry->key, key, key_len) == 0) {
                entry->value = value;
                return entry;
            }
        }

        idx = (idx + 1) % map->capacity;
        entry = map->table + idx;
        if (idx == start) {
            if (tombstone) {
                break;
            }
            else {
                return NULL; // Should not happen: full table without tombstone
            }
        }
    }

    // Insert to tombstone if available
    if (tombstone) {
        entry = tombstone;
    }
    else {
        map->size++;
    }

    char* key_copy = c_bytemap_clone_key(map->allocator, key, key_len);
    if (!key_copy) return NULL;

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
    return entry;
}

// --- Pop ---
static inline int c_bytemap_pop(ByteMapHeader* map, const char* key, size_t key_len, void** out) {
    if (!map || !key) return -1;
    if (key_len == 0) key_len = strlen(key);
    if (key_len == 0) return -1;

    uint64_t hash = c_bytemap_hash(map, key, key_len);
    size_t idx = (size_t) (hash % map->capacity);
    size_t start = idx;

    while (1) {
        MapEntry* entry = &map->table[idx];
        if (!entry->occupied && !entry->removed) {
            break;
        }
        if (entry->occupied &&
            entry->key_length == key_len &&
            memcmp(entry->key, key, key_len) == 0) {
            if (out) *out = entry->value;

            if (entry->prev) entry->prev->next = entry->next;
            else map->first = entry->next;
            if (entry->next) entry->next->prev = entry->prev;
            else map->last = entry->prev;

            c_bytemap_free_key(map->allocator, entry->key);

            memset(entry, 0, sizeof(MapEntry));
            entry->removed = 1;
            map->occupied--;
            return 0;
        }

        idx = (idx + 1) % map->capacity;
        if (idx == start) break;
    }
    if (out) *out = (void*) C_BYTEMAP_NOT_FOUND;
    return -1;
}

static inline void* c_bytemap_notfound() {
    return (void*) C_BYTEMAP_NOT_FOUND;
}

#endif // C_BYTEMAP_H