#ifndef C_EVENT_ENGINE_ALLOCATOR_PROTOCOL_H
#define C_EVENT_ENGINE_ALLOCATOR_PROTOCOL_H

/**
 * @brief EventEngine-local allocator protocol header.
 *
 * Wraps PyCyBase's allocator_protocol with an EE_LOCAL_ONLY compile-time
 * switch.  When EE_LOCAL_ONLY is 1 (default, thread-local engine), only the
 * heap-allocator branch is available and SHM is excluded.  Set to 0 to
 * enable the full shared-memory allocator stack.
 */

#ifndef EE_LOCAL_ONLY
#define EE_LOCAL_ONLY 1
#endif

#include <cbase/allocator_protocol/c_allocator_protocol.h>

#if !EE_LOCAL_ONLY
#include <cbase/allocator_protocol/c_shm_comp.h>
#endif

#endif /* C_EVENT_ENGINE_ALLOCATOR_PROTOCOL_H */
