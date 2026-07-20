from libc.stdlib cimport calloc

from cbase.allocator_protocol.c_heap_allocator cimport c_heap_allocator_new
from cbase.allocator_protocol.c_shm_comp cimport c_shm_allocator_new, AP_SHM_ALLOCATOR_DEFAULT_REGION_SIZE


cdef c_bool EE_CFG_LOCKED = False
cdef c_bool EE_CFG_SHARED = False
cdef c_bool EE_CFG_FREELIST = True


cdef class EEConfigContext(AllocatorConfigContext):
    cdef void c_bind(self, allocator_protocol* schematic=NULL):
        self.allocator_schematic = schematic if schematic else EE_DEFAULT_ALLOCATOR

    cdef void c_activate(self):
        if 'locked' in self.overrides:
            global EE_CFG_LOCKED
            EE_CFG_LOCKED = self.overrides['locked']

        if 'shared' in self.overrides:
            global EE_CFG_SHARED
            EE_CFG_SHARED = self.overrides['shared']

        if 'freelist' in self.overrides:
            global EE_CFG_FREELIST
            EE_CFG_FREELIST = self.overrides['freelist']

        AllocatorConfigContext.c_activate(self)

    cdef void c_deactivate(self):
        if 'locked' in self.originals:
            global EE_CFG_LOCKED
            EE_CFG_LOCKED = self.originals.get('locked')

        if 'shared' in self.originals:
            global EE_CFG_SHARED
            EE_CFG_SHARED = self.originals.get('shared')

        if 'freelist' in self.originals:
            global EE_CFG_FREELIST
            EE_CFG_FREELIST = self.originals.get('freelist')

        AllocatorConfigContext.c_deactivate(self)


# --- Module-level allocator singletons ---

cdef heap_allocator* EE_HEAP_ALLOCATOR_RAW = c_heap_allocator_new()
if not EE_HEAP_ALLOCATOR_RAW:
    raise OSError("Initialize EE heap allocator failed")

cdef shm_allocator_ctx* EE_SHM_ALLOCATOR_RAW = NULL

if not EE_LOCAL_ONLY:
    EE_SHM_ALLOCATOR_RAW = c_shm_allocator_new(AP_SHM_ALLOCATOR_DEFAULT_REGION_SIZE, <char*> b"c_ee_shm")
    if not EE_SHM_ALLOCATOR_RAW:
        raise OSError("Initialize EE SHM allocator failed (prefix='c_ee_shm')")


cdef allocator_protocol* EE_DEFAULT_ALLOCATOR = <allocator_protocol*> calloc(1, sizeof(allocator_protocol))
cdef allocator_protocol* EE_HEAP_ALLOCATOR    = <allocator_protocol*> calloc(1, sizeof(allocator_protocol))

EE_DEFAULT_ALLOCATOR.with_lock          = EE_CFG_LOCKED
EE_DEFAULT_ALLOCATOR.with_shm           = EE_CFG_SHARED
EE_DEFAULT_ALLOCATOR.with_freelist      = EE_CFG_FREELIST
EE_DEFAULT_ALLOCATOR.shm_allocator_ctx  = EE_SHM_ALLOCATOR_RAW
EE_DEFAULT_ALLOCATOR.shm_allocator      = EE_SHM_ALLOCATOR_RAW.shm_allocator if EE_SHM_ALLOCATOR_RAW != NULL else NULL
EE_DEFAULT_ALLOCATOR.heap_allocator     = EE_HEAP_ALLOCATOR_RAW

EE_HEAP_ALLOCATOR.with_lock             = True
EE_HEAP_ALLOCATOR.with_shm              = False
EE_HEAP_ALLOCATOR.with_freelist         = True
EE_HEAP_ALLOCATOR.shm_allocator_ctx     = NULL
EE_HEAP_ALLOCATOR.shm_allocator         = NULL
EE_HEAP_ALLOCATOR.heap_allocator        = EE_HEAP_ALLOCATOR_RAW

cdef allocator_protocol* EE_SHM_ALLOCATOR = NULL

if not EE_LOCAL_ONLY:
    EE_SHM_ALLOCATOR = <allocator_protocol*> calloc(1, sizeof(allocator_protocol))

    EE_SHM_ALLOCATOR.with_lock              = True
    EE_SHM_ALLOCATOR.with_shm               = True
    EE_SHM_ALLOCATOR.with_freelist          = True
    EE_SHM_ALLOCATOR.shm_allocator_ctx      = EE_SHM_ALLOCATOR_RAW
    EE_SHM_ALLOCATOR.shm_allocator          = EE_SHM_ALLOCATOR_RAW.shm_allocator
    EE_SHM_ALLOCATOR.heap_allocator         = NULL


cdef EEConfigContext EE_SHARED   = EEConfigContext(shared=True)
cdef EEConfigContext EE_LOCKED   = EEConfigContext(locked=True)
cdef EEConfigContext EE_LOCKFREE = EEConfigContext(locked=False)
cdef EEConfigContext EE_FREELIST = EEConfigContext(freelist=True)

globals()['EE_SHARED'] = EE_SHARED
globals()['EE_LOCKED'] = EE_LOCKED
globals()['EE_LOCKFREE'] = EE_LOCKFREE
globals()['EE_FREELIST'] = EE_FREELIST
