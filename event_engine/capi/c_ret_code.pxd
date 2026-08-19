cdef extern from "event_engine/capi/c_ret_code.h":

    ctypedef enum evt_ret_code:
        EVT_RET_OK
        EVT_RET_ERR_INVALID_INPUT
        EVT_RET_ERR_OOM
        EVT_RET_ERR_DUPLICATE
        EVT_RET_ERR_UNINITIALIZED
        EVT_RET_ERR_FULL
        EVT_RET_ERR_EMPTY
        EVT_RET_ERR_TIMEOUT
        EVT_RET_ERR_NOT_FOUND
        EVT_RET_ERR_INVALID_TOPIC
