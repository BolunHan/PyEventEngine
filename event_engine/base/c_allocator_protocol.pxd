from libcpp cimport bool as c_bool

from cbase.allocator_protocol.c_allocator_protocol cimport AllocatorConfigContext, allocator_protocol
from cbase.allocator_protocol.c_heap_allocator cimport heap_allocator
from cbase.allocator_protocol.c_shm_comp cimport shm_allocator_ctx


cdef extern from "event_engine/base/c_allocator_protocol.h":
    const c_bool EE_LOCAL_ONLY


cdef c_bool EE_CFG_LOCKED
cdef c_bool EE_CFG_SHARED
cdef c_bool EE_CFG_FREELIST


cdef class EEConfigContext(AllocatorConfigContext):
    pass


cdef heap_allocator* EE_HEAP_ALLOCATOR_RAW
cdef shm_allocator_ctx* EE_SHM_ALLOCATOR_RAW

cdef allocator_protocol* EE_DEFAULT_ALLOCATOR
cdef allocator_protocol* EE_SHM_ALLOCATOR
cdef allocator_protocol* EE_HEAP_ALLOCATOR

cdef EEConfigContext EE_SHARED
cdef EEConfigContext EE_LOCKED
cdef EEConfigContext EE_LOCKFREE
cdef EEConfigContext EE_FREELIST
