#ifndef C_ALLOCATOR_H
#define C_ALLOCATOR_H

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// Default page size: 4 MiB, overridable via -DDEFAULT_ALLOC_PAGE=...
#ifndef DEFAULT_ALLOC_PAGE
#define DEFAULT_ALLOC_PAGE (4 * 1024 * 1024)
#endif

#if DEFAULT_ALLOC_PAGE == 0
#error "DEFAULT_ALLOC_PAGE must be positive"
#endif

/**
 * @brief Represents a freed memory block in the free list.
 *
 * When a block is recycled, its first `sizeof(MemoryBlock)` bytes are
 * overwritten to form this structure, enabling O(1) free-list linkage.
 */
typedef struct MemoryBlock {
    size_t size;              // Payload size (excluding this header)
    struct MemoryBlock* next; // Next in free list
} MemoryBlock;

/**
 * @brief A memory allocator optimized for high-frequency allocation/recycling.
 *
 * This allocator uses a hybrid approach:
 *   - A free list for recycled fixed/variable-size blocks.
 *   - Bump allocation from a tail page for new allocations.
 *   - Automatic page extension with exponential growth.
 *
 * Designed for low-latency systems where malloc/free must be avoided in hot paths.
 */
typedef struct MemoryPage {
    struct MemoryPage* prev;  // Only link backward (to older pages)
    size_t occupied;          // Bytes used in buffer (for bump allocation)
    size_t capacity;          // Total usable buffer size
    char* buffer;             // Actual storage
} MemoryPage;

typedef struct MemoryAllocator {
    int active;               // Whether usable
    MemoryPage* pages;        // Points to TAIL page (most recent)
    int owned;                // Whether it owns the pages (for cleanup)
    int extendable;           // Whether it can extend pages
    MemoryBlock* free_list;   // Head of free list
} MemoryAllocator;

/**
 * @brief Aligns a size up to the nearest pointer-sized boundary.
 *
 * This ensures allocations are properly aligned for any pointer-type access,
 * as required by the C standard for portable code.
 *
 * @param size The size to align.
 * @return The aligned size (>= size, multiple of sizeof(void*)).
 */
static inline size_t c_heap_align(size_t size) {
    const size_t align = sizeof(void*);
    return (size + align - 1) & ~(align - 1);
}

/**
 * @brief Extends the allocator with a new memory page.
 *
 * If page_size is 0, the allocator attempts to double the capacity of the
 * current tail page. If no pages exist, it uses DEFAULT_ALLOC_PAGE.
 *
 * @param allocator The allocator to extend.
 * @param page_size Requested page buffer size; 0 means use default/doubled size.
 * @return 0 on success, -1 on failure (e.g., OOM or invalid input).
 */
static inline int c_heap_extend(MemoryAllocator* allocator, size_t page_size) {
    if (!allocator || !allocator->active) return -1;

    if (!allocator->extendable) {
        return -1; // Not extendable
    }

    if (page_size == 0) {
        if (allocator->pages) {
            page_size = allocator->pages->capacity * 2;
        }
        else {
            page_size = DEFAULT_ALLOC_PAGE;
        }
    }
    if (page_size < sizeof(MemoryPage) + sizeof(void*)) {
        return -1;
    }

    // Allocate page header
    MemoryPage* page = (MemoryPage*) malloc(sizeof(MemoryPage));
    if (!page) return -1;

    // Allocate page buffer
    char* buffer = (char*) malloc(page_size);
    if (!buffer) {
        free(page);
        return -1;
    }

    // Initialize page
    page->buffer = buffer;
    page->capacity = page_size;
    page->occupied = 0;
    page->prev = allocator->pages;  // link to previous tail
    allocator->pages = page;        // update tail
    allocator->owned = 1;
    return 0;
}

/**
 * @brief Creates a new MemoryAllocator with an initial page.
 *
 * The allocator is ready for immediate use after creation.
 *
 * @param capacity Initial page buffer size; 0 uses DEFAULT_ALLOC_PAGE.
 * @return Pointer to a new MemoryAllocator, or NULL on failure.
 */
static inline MemoryAllocator* c_heap_new(size_t capacity) {
    MemoryAllocator* allocator = (MemoryAllocator*) malloc(sizeof(MemoryAllocator));
    if (!allocator) return NULL;

    allocator->active = 1;
    allocator->pages = NULL;
    allocator->extendable = 1;
    allocator->owned = 0;
    allocator->free_list = NULL;

    // Lazy page allocation
    if (!capacity) {
        return allocator;
    }

    // Pre-allocate first page
    if (c_heap_extend(allocator, capacity) != 0) {
        free(allocator);
        return NULL;
    }

    return allocator;
}

/**
 * @brief Internal helper: bump-allocates from the tail page, extending if needed.
 *
 * This function is used internally by c_heap_request to allocate raw space
 * for a block header + payload. It may trigger page extension.
 *
 * @param allocator The allocator to allocate from.
 * @param total_size Total bytes needed (header + payload).
 * @return Pointer to allocated space, or NULL on failure.
 */
static inline void* c_heap_alloc(MemoryAllocator* allocator, size_t total_size) {
    if (!allocator->pages) return NULL;
    MemoryPage* page = allocator->pages;

    // Check and extend memory page if needed
    if (page->occupied + total_size > page->capacity) {
        // Not extendable
        if (!allocator->extendable) {
            return NULL;
        }

        size_t new_capacity = page->capacity * 2;
        if (new_capacity < total_size) {
            new_capacity = total_size;
        }

        if (c_heap_extend(allocator, new_capacity) != 0) {
            return NULL; // OOM
        }
        page = allocator->pages;
    }

    void* ptr = page->buffer + page->occupied;
    page->occupied += total_size;
    return ptr;
}

/**
 * @brief Allocates a zero-initialized block of memory.
 *
 * Attempts to satisfy the request from the free list first (first-fit).
 * If no suitable block exists, falls back to bump allocation from the tail page.
 * Automatically extends memory if needed.
 *
 * @param allocator The allocator to use.
 * @param size Requested payload size (>= 1).
 * @return Pointer to zero-initialized payload, or NULL on failure.
 */
static inline void* c_heap_request(MemoryAllocator* allocator, size_t size) {
    if (!allocator || !allocator->active || size == 0) {
        return NULL;
    }

    size = c_heap_align(size);

    // Step 1. Try free list (first-fit)
    MemoryBlock** prev = &allocator->free_list;
    MemoryBlock* current = allocator->free_list;
    while (current) {
        if (current->size >= size) {
            // Found a usable block
            *prev = current->next;
            memset((void*) (current + 1), 0, size);
            return (void*) (current + 1); // skip header
        }
        prev = &current->next;
        current = current->next;
    }

    // Step 2. Try bump allocation from tail page
    const size_t total_size = sizeof(MemoryBlock) + size;
    void* ptr = c_heap_alloc(allocator, total_size);
    if (!ptr) {
        return NULL; // OOM
    }
    else {
        MemoryBlock* block = (MemoryBlock*) ptr;
        block->size = size;
        void* payload = (void*) (block + 1);
        memset(payload, 0, size);
        return payload;
    }
}

/**
 * @brief Recycles a previously allocated block back into the free list.
 *
 * The block must have been allocated by the same allocator.
 * The payload is zeroed for safety.
 *
 * @param allocator The allocator that owns the block.
 * @param ptr Pointer to the payload (as returned by c_heap_request).
 */
static inline void c_heap_recycle(MemoryAllocator* allocator, void* ptr) {
    if (allocator && allocator->active) {
        if (!ptr) {
            return; // Null pointer: nothing to do
        }
        else {
            MemoryBlock* block = ((MemoryBlock*) ptr) - 1;
            memset(ptr, 0, block->size);
            block->next = allocator->free_list;
            allocator->free_list = block;
        }
    }
    else {
        // Compatibility: free directly if allocator is invalid
        free(ptr);
    }
}

/**
 * @brief Destroys the allocator and frees all associated memory.
 *
 * If the allocator owns its pages (owned=1), all pages and buffers are freed.
 * The allocator struct itself is also freed.
 *
 * @param allocator The allocator to destroy.
 */
static inline void c_heap_free(MemoryAllocator* allocator) {
    if (!allocator || !allocator->active) return;

    // Not owned: just reset
    if (!allocator->owned) {
        allocator->active = 0;
        allocator->pages = NULL;
        allocator->free_list = NULL;
        free(allocator);
        return;
    }

    // Free all pages (walk backward from tail)
    MemoryPage* page = allocator->pages;
    while (page) {
        MemoryPage* prev = page->prev;
        free(page->buffer);
        free(page);
        page = prev;
    }

    allocator->active = 0;
    allocator->pages = NULL;
    allocator->free_list = NULL;
    allocator->owned = 0;
    free(allocator);
}

/**
 * @brief Returns the number of free bytes in the current (tail) page.
 *
 * This is an estimate of immediately available space for bump allocation.
 * It does not include space recoverable from the free list.
 *
 * @param allocator The allocator to inspect.
 * @return Available bytes in tail page, or 0 if invalid/inactive.
 */
static inline size_t c_heap_available(MemoryAllocator* allocator) {
    if (!allocator || !allocator->active || !allocator->pages) {
        return 0;
    }
    MemoryPage* page = allocator->pages;
    return page->capacity - page->occupied;
}

/**
 * @brief Returns the total capacity of the MemoryAllocator.
 *
 * This sums up the capacities of all memory pages managed by the allocator.
 * It does not account for used vs free space.
 *
 * @param allocator The allocator to inspect.
 * @return Total capacity in bytes, or 0 if invalid/inactive.
 */
static inline size_t c_heap_total_capacity(MemoryAllocator* allocator) {
    if (!allocator || !allocator->active) {
        return 0;
    }
    size_t total = 0;
    MemoryPage* page = allocator->pages;
    while (page) {
        total += page->capacity;
        page = page->prev;
    }
    return total;
}

#endif // C_ALLOCATOR_H