#ifndef C_EVENTENGINE_RET_CODE_H
#define C_EVENTENGINE_RET_CODE_H

// clang-format off

/**
 * @enum evt_ret_code
 * @brief Global return codes shared by all event_engine modules.
 *
 * 0 is always success; negative values are errors. Every function in the
 * capi layer reports its result with this enum so callers can check codes
 * uniformly across modules.
 */
typedef enum evt_ret_code {
    EVT_RET_OK                = 0,   // operation succeeded
    EVT_RET_ERR_INVALID_INPUT = -1,  // NULL pointer or invalid argument
    EVT_RET_ERR_OOM           = -2,  // allocation failed
    EVT_RET_ERR_DUPLICATE     = -3,  // duplicate entry rejected
    EVT_RET_ERR_UNINITIALIZED = -4,  // struct not initialized
    EVT_RET_ERR_FULL          = -5,  // queue is full
    EVT_RET_ERR_EMPTY         = -6,  // queue is empty
    EVT_RET_ERR_TIMEOUT       = -7,  // blocking wait timed out
    EVT_RET_ERR_NOT_FOUND     = -8,  // entry not found in registry
    EVT_RET_ERR_INVALID_TOPIC = -9,  // topic string is invalid
} evt_ret_code;

// clang-format on

#endif  // C_EVENTENGINE_RET_CODE_H
