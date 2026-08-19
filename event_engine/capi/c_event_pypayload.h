#ifndef C_EVENTENGINE_EVENT_PYPAYLOAD_H
#define C_EVENTENGINE_EVENT_PYPAYLOAD_H

#include <stdbool.h>
#include <stddef.h>

#include <Python.h>

#include <event_engine/capi/c_event.h>
#include <event_engine/capi/c_topic.h>

// ========== Constants ==========

#ifndef TOPIC_FIELD_NAME
#define TOPIC_FIELD_NAME "topic"
#endif

static PyObject* PY_TOPIC_FIELD_NAME = NULL;
static PyObject* PY_EMPTY_ARGS = NULL;
static PyObject* PY_EMPTY_KWARGS = NULL;

// ========== Structs ==========

/**
 * @brief C-layer representation of the cython Topic cdef class.
 */
typedef struct evt_py_topic {
    PyObject   py_base;
    void*      cy_vtab;
    evt_topic* header;
    int        owner;
} evt_py_topic;

typedef struct evt_py_payload {
    evt_py_topic* py_topic;
    PyObject*     py_args;
    PyObject*     py_kwargs;
    PyObject*     py_kwargs_aggregated;
} evt_py_payload;

typedef struct evt_py_callable {
    PyObject*               fn;
    PyObject*               logger;
    size_t                  idx;
    bool                    with_topic;
    struct evt_py_callable* next;
} evt_py_callable;

typedef struct evt_hook_stats {
    size_t n_calls;
    double ts_call_start;
    double ts_call_complete;
    double elapsed_seconds;
} evt_hook_stats;

/**
 * @brief C-layer representation of the cython EventHook cdef class.
 */
typedef struct evt_py_hook {
    PyObject         py_base;
    void*            cy_vtab;
    evt_hook*        header;
    evt_py_callable* callables;
    evt_py_topic*    topic;
    PyObject*        logger;
} evt_py_hook;

typedef struct evt_py_hook_ex {
    evt_py_hook    py_hook;
    evt_hook_stats hook_stats;
} evt_py_hook_ex;

// ========== Forward Declarations ==========

static inline void                 c_evt_pypayload_init_constants(void);
static inline evt_message_payload* c_evt_pypayload_new(evt_py_topic* py_topic, PyObject* py_args, PyObject* py_kwargs, allocator_protocol* allocator);
static inline void                 c_evt_pypayload_free(evt_message_payload* payload);
static inline bool                 c_evt_pycallable_same(PyObject* a, PyObject* b);

// ========== Utility Functions ==========

/**
 * @brief Lazily initialize the module-wide Python constants.
 *
 * PY_TOPIC_FIELD_NAME ("topic"), PY_EMPTY_ARGS (empty tuple) and
 * PY_EMPTY_KWARGS (empty dict) are process-lifetime references; callers
 * must hold the GIL.
 */
static inline void c_evt_pypayload_init_constants(void) {
    if (!PY_TOPIC_FIELD_NAME || PY_TOPIC_FIELD_NAME == Py_None) {
        PY_TOPIC_FIELD_NAME = PyUnicode_FromString(TOPIC_FIELD_NAME);
        if (PY_TOPIC_FIELD_NAME == NULL) Py_FatalError("Failed to initialize PY_TOPIC_FIELD_NAME");
    }

    if (!PY_EMPTY_ARGS || PY_EMPTY_ARGS == Py_None) {
        PY_EMPTY_ARGS = PyTuple_New(0);
        if (PY_EMPTY_ARGS == NULL) Py_FatalError("Failed to initialize PY_EMPTY_ARGS");
    }

    if (!PY_EMPTY_KWARGS || PY_EMPTY_KWARGS == Py_None) {
        PY_EMPTY_KWARGS = PyDict_New();
        if (PY_EMPTY_KWARGS == NULL) Py_FatalError("Failed to initialize PY_EMPTY_KWARGS");
    }
}

// ========== Public Interfaces ==========

/**
 * @brief Create an evt_message_payload with a Python-facing payload tail.
 *
 * Allocates one block holding evt_message_payload + evt_py_payload via the
 * allocator protocol. Stores and owns one reference each to py_topic,
 * py_args and py_kwargs; py_kwargs_aggregated owns the reference returned
 * by PyDict_Copy() and carries the injected "topic" field.
 *
 * @param py_topic Python Topic wrapper (must not be NULL).
 * @param py_args Positional args; must be a tuple, or None/NULL for empty args.
 * @param py_kwargs Keyword args; must be a dict, or None/NULL for empty kwargs.
 * @param allocator Allocator protocol used for the payload block.
 * @return New payload, or NULL with a Python exception set on invalid input or OOM.
 */
static inline evt_message_payload* c_evt_pypayload_new(evt_py_topic* py_topic, PyObject* py_args, PyObject* py_kwargs, allocator_protocol* allocator) {
    if (!py_topic) {
        PyErr_SetString(PyExc_ValueError, "topic must not be NULL");
        return NULL;
    }

    if (py_args == Py_None) py_args = NULL;
    if (py_kwargs == Py_None) py_kwargs = NULL;

    if (py_args && !PyTuple_Check(py_args)) {
        PyErr_SetString(PyExc_TypeError, "args must be tuple");
        return NULL;
    }

    if (py_kwargs && !PyDict_Check(py_kwargs)) {
        PyErr_SetString(PyExc_TypeError, "kwargs must be dict");
        return NULL;
    }

    c_evt_pypayload_init_constants();

    py_args = py_args ? py_args : PY_EMPTY_ARGS;
    py_kwargs = py_kwargs ? py_kwargs : PY_EMPTY_KWARGS;

    evt_message_payload* c_payload = (evt_message_payload*) c_ap_alloc(sizeof(evt_message_payload) + sizeof(evt_py_payload), allocator);
    if (!c_payload) {
        PyErr_NoMemory();
        return NULL;
    }

    evt_py_payload* py_payload = (evt_py_payload*) (c_payload + 1);
    PyObject*       kwargs_aggregated = PyDict_Copy(py_kwargs);
    if (!kwargs_aggregated) {
        c_ap_free(c_payload);
        return NULL;
    }

    if (PyDict_SetDefault(kwargs_aggregated, PY_TOPIC_FIELD_NAME, (PyObject*) py_topic) == NULL) {
        Py_DECREF(kwargs_aggregated);
        c_ap_free(c_payload);
        return NULL;
    }

    py_payload->py_topic = py_topic;
    py_payload->py_args = py_args;
    py_payload->py_kwargs = py_kwargs;
    py_payload->py_kwargs_aggregated = kwargs_aggregated;

    Py_INCREF(py_topic);
    Py_XINCREF(py_args);
    Py_XINCREF(py_kwargs);
    // kwargs_aggregated already owns one reference from PyDict_Copy()

    c_payload->args = py_payload;
    c_payload->topic = py_topic->header;

    return c_payload;
}

/**
 * @brief Free a payload created by c_evt_pypayload_new.
 *
 * Releases the Python references owned by the payload tail, then frees the
 * payload block. NULL-safe.
 *
 * @param payload Payload to free (may be NULL).
 */
static inline void c_evt_pypayload_free(evt_message_payload* payload) {
    if (!payload) return;

    evt_py_payload* py_payload = (evt_py_payload*) (payload + 1);

    Py_XDECREF(py_payload->py_topic);
    Py_XDECREF(py_payload->py_args);
    Py_XDECREF(py_payload->py_kwargs);
    Py_XDECREF(py_payload->py_kwargs_aggregated);

    c_ap_free(payload);
}

/**
 * @brief Compare two Python callables for handler-registration equality.
 *
 * Bound methods are equal when their __self__ and __func__ match; otherwise
 * identity comparison applies. NULL-safe.
 *
 * @param a First callable (may be NULL).
 * @param b Second callable (may be NULL).
 * @return true when a and b refer to the same handler.
 */
static inline bool c_evt_pycallable_same(PyObject* a, PyObject* b) {
    if (a == b) return true;
    if (!a || !b) return false;

    if (PyMethod_Check(a) && PyMethod_Check(b)) {
        return PyMethod_GET_SELF(a) == PyMethod_GET_SELF(b) &&
               PyMethod_GET_FUNCTION(a) == PyMethod_GET_FUNCTION(b);
    }
    return false;
}

#endif  // C_EVENTENGINE_EVENT_PYPAYLOAD_H