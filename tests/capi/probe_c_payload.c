/*
 * A standalone probe of the event engine's C payload path -- no Python in the
 * process at all. It answers one question before Quark builds on it: can a C
 * producer publish an arbitrary C struct on an exact topic, and can a pure C
 * consumer receive it from the engine loop, with the payload's own release?
 *
 * Build (from the repository root):
 *
 *   gcc -O2 -o /tmp/probe_c_payload tests/capi/probe_c_payload.c \
 *       -I "$PWD" -I "$HOME/Projects/PyCyBase" -lpthread -lm
 *
 * The probe prints what it saw and exits non-zero on any mismatch.
 */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE  /* before any libc header: c_engine.h needs the affinity calls */
#endif

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <event_engine/capi/c_engine.h>
#include <event_engine/capi/c_event.h>
#include <event_engine/capi/c_topic.h>

typedef struct probe_msg {
    int    value;
    double price;
    char   text[16];
} probe_msg;

static evt_engine* g_engine = NULL;
static size_t      g_received = 0;
static probe_msg   g_last;
static int         g_ret_code = 0;

/* The consumer: a plain C function, registered with EVT_CALLBACK_WITH_ARGS. The
 * argument is the producer's `args` pointer, borrowed for the call. */
static void probe_on_msg(void* args) {
    probe_msg* msg = (probe_msg*) args;
    if (!msg) {
        g_ret_code = -2;
        return;
    }

    g_last = *msg;
    g_received++;
    printf("[probe] received value=%d price=%.3f text=%s\n", msg->value, msg->price, msg->text);

    if (g_engine) c_evt_engine_set_active(g_engine, false);
}

/* The payload's release: the producer owns `args`, and the engine calls this
 * after dispatch (or on a failed publish). */
static void probe_payload_free(evt_message_payload* payload) {
    if (!payload) return;
    free(payload->args);
    free(payload);
}

static void* probe_loop(void* arg) {
    c_evt_engine_loop((evt_engine*) arg);
    return NULL;
}

int main(void) {
    g_engine = c_evt_engine_new(NULL);
    if (!g_engine) {
        printf("[probe] engine allocation failed\n");
        return 1;
    }

    /* A fresh engine starts INACTIVE, and the loop is "while active" - without
     * this the loop thread returns before the first message is even published. */
    c_evt_engine_set_active(g_engine, true);

    const char* topic_key = "probe.c.action";
    evt_topic*  topic = c_topic_new(topic_key, strlen(topic_key), NULL);
    if (!topic) {
        printf("[probe] topic allocation failed\n");
        return 1;
    }

    int ret_code = c_evt_engine_register_handler(g_engine, topic, (const void*) probe_on_msg, EVT_CALLBACK_WITH_ARGS, NULL, false);
    if (ret_code != EVT_RET_OK) {
        printf("[probe] register_handler failed: %d\n", ret_code);
        return 1;
    }

    pthread_t thread;
    if (pthread_create(&thread, NULL, probe_loop, g_engine) != 0) {
        printf("[probe] loop thread failed\n");
        return 1;
    }

    evt_message_payload* payload = (evt_message_payload*) calloc(1, sizeof(evt_message_payload));
    probe_msg*           msg = (probe_msg*) calloc(1, sizeof(probe_msg));
    if (!payload || !msg) {
        printf("[probe] payload allocation failed\n");
        return 1;
    }

    msg->value = 42;
    msg->price = 3.1415926;
    snprintf(msg->text, sizeof msg->text, "long");

    payload->args = msg;
    payload->topic = topic;
    payload->fn_dealloc = probe_payload_free;

    ret_code = c_evt_engine_publish(g_engine, payload, true, 0, 1.0);
    printf("[probe] publish ret=%d\n", ret_code);
    if (ret_code != EVT_RET_OK) return 1;

    pthread_join(thread, NULL);

    if (g_received != 1 || g_last.value != 42 || g_last.price != 3.1415926 || strcmp(g_last.text, "long") != 0) {
        printf("[probe] MISMATCH received=%zu value=%d price=%.3f text=%s code=%d\n", g_received, g_last.value, g_last.price, g_last.text, g_ret_code);
        return 2;
    }

    printf("[probe] OK: one C payload, published and received in the pure C loop\n");
    return 0;
}
