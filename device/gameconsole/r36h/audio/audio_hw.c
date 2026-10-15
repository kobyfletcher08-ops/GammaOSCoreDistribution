/* SPDX-License-Identifier: Apache-2.0 */
/* Minimal PCM playback HAL for the RK817 codec; USB audio uses AOSP's HAL. */
#define LOG_TAG "audio_hw_r36h"
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <cutils/log.h>
#include <cutils/str_parms.h>
#include <hardware/audio.h>
#include <tinyalsa/asoundlib.h>

#define RATE 48000u
#define CHANNELS 2u
#define PERIOD 240u
#define PERIODS 4u
#define FRAME_BYTES 4u

struct r36h_output {
    struct audio_stream_out stream;
    pthread_mutex_t lock;
    struct pcm *pcm;
    struct mixer *mixer;
    unsigned int card;
    audio_devices_t devices;
    uint64_t frames;
};
struct r36h_device {
    struct audio_hw_device device;
    pthread_mutex_t lock;
    struct r36h_output *output;
};
static const struct pcm_config config = {
    .channels = CHANNELS, .rate = RATE, .period_size = PERIOD,
    .period_count = PERIODS, .format = PCM_FORMAT_S16_LE,
    .start_threshold = PERIOD, .stop_threshold = PERIOD * PERIODS,
    .silence_threshold = 0,
};

static unsigned int codec_card(void) {
    for (unsigned int card = 0; card < 16; ++card) {
        char path[80], id[160] = {0};
        snprintf(path, sizeof(path), "/sys/class/sound/card%u/id", card);
        FILE *f = fopen(path, "re");
        if (!f) continue;
        bool found = fgets(id, sizeof(id), f) && strstr(id, "rk817");
        fclose(f);
        if (found) return card;
    }
    return 0;
}
static void route_locked(struct r36h_output *out, bool enabled) {
    if (!out->mixer) out->mixer = mixer_open(out->card);
    if (!out->mixer) return;
    struct mixer_ctl *ctl = mixer_get_ctl_by_name(out->mixer, "Playback Path");
    bool headphones = out->devices & (AUDIO_DEVICE_OUT_WIRED_HEADPHONE | AUDIO_DEVICE_OUT_WIRED_HEADSET);
    const char *path = enabled ? (headphones ? "HP_NO_MIC" : "SPK") : "OFF";
    if (!ctl || mixer_ctl_set_enum_by_string(ctl, path) < 0)
        ALOGE("Cannot select RK817 playback path %s", path);
}
static void standby_locked(struct r36h_output *out) {
    if (out->pcm) { pcm_close(out->pcm); out->pcm = NULL; }
    route_locked(out, false);
    if (out->mixer) { mixer_close(out->mixer); out->mixer = NULL; }
    out->frames = 0;
}
static uint32_t sample_rate(const struct audio_stream *s) { return RATE; }
static int set_sample_rate(struct audio_stream *s, uint32_t rate) { return rate == RATE ? 0 : -EINVAL; }
static size_t buffer_size(const struct audio_stream *s) { return PERIOD * FRAME_BYTES; }
static audio_channel_mask_t channels(const struct audio_stream *s) { return AUDIO_CHANNEL_OUT_STEREO; }
static audio_format_t format(const struct audio_stream *s) { return AUDIO_FORMAT_PCM_16_BIT; }
static int set_format(struct audio_stream *s, audio_format_t f) { return f == AUDIO_FORMAT_PCM_16_BIT ? 0 : -EINVAL; }
static int standby(struct audio_stream *s) {
    struct r36h_output *out = (struct r36h_output *)s;
    pthread_mutex_lock(&out->lock);
    standby_locked(out);
    pthread_mutex_unlock(&out->lock);
    return 0;
}
static int dump_stream(const struct audio_stream *s, int fd) {
    const struct r36h_output *out = (const struct r36h_output *)s;
    dprintf(fd, "R36H RK817 PCM: card=%u rate=%u channels=%u\n", out->card, RATE, CHANNELS);
    return 0;
}
static int set_parameters(struct audio_stream *s, const char *pairs) {
    struct r36h_output *out = (struct r36h_output *)s;
    struct str_parms *parms = str_parms_create_str(pairs);
    if (!parms) return -ENOMEM;
    int devices;
    if (str_parms_get_int(parms, AUDIO_PARAMETER_STREAM_ROUTING, &devices) >= 0 && devices) {
        pthread_mutex_lock(&out->lock);
        out->devices = (audio_devices_t)devices;
        if (out->pcm) route_locked(out, true);
        pthread_mutex_unlock(&out->lock);
    }
    str_parms_destroy(parms);
    return 0;
}
static char *get_parameters(const struct audio_stream *s, const char *keys) { return strdup(""); }
static int effect(const struct audio_stream *s, effect_handle_t e) { return 0; }
static uint32_t latency(const struct audio_stream_out *s) { return PERIOD * PERIODS * 1000 / RATE; }
static int volume(struct audio_stream_out *s, float left, float right) { return -ENOSYS; }
static ssize_t write_pcm(struct audio_stream_out *s, const void *buffer, size_t bytes) {
    struct r36h_output *out = (struct r36h_output *)s;
    if (bytes % FRAME_BYTES) return -EINVAL;
    pthread_mutex_lock(&out->lock);
    if (!out->pcm) {
        struct pcm_config pcm_settings = config;
        out->pcm = pcm_open(out->card, 0, PCM_OUT | PCM_MONOTONIC, &pcm_settings);
        if (!out->pcm || !pcm_is_ready(out->pcm)) {
            ALOGE("RK817 pcm_open failed: %s", out->pcm ? pcm_get_error(out->pcm) : "no PCM handle");
            standby_locked(out);
            pthread_mutex_unlock(&out->lock);
            usleep((uint64_t)bytes * 1000000 / (RATE * FRAME_BYTES));
            return -EIO;
        }
        route_locked(out, true);
    }
    int rc = pcm_write(out->pcm, buffer, bytes);
    if (rc < 0) {
        ALOGE("RK817 PCM write failed: %s", pcm_get_error(out->pcm));
        standby_locked(out);
    } else {
        out->frames += bytes / FRAME_BYTES;
    }
    pthread_mutex_unlock(&out->lock);
    if (rc < 0) {
        usleep((uint64_t)bytes * 1000000 / (RATE * FRAME_BYTES));
        return -EIO;
    }
    return bytes;
}
static int render_position(const struct audio_stream_out *s, uint32_t *frames) {
    struct r36h_output *out = (struct r36h_output *)s;
    pthread_mutex_lock(&out->lock);
    *frames = (uint32_t)out->frames;
    pthread_mutex_unlock(&out->lock);
    return 0;
}
static int next_timestamp(const struct audio_stream_out *s, int64_t *time) { return -ENOSYS; }
static int presentation_position(const struct audio_stream_out *s, uint64_t *frames, struct timespec *timestamp) {
    struct r36h_output *out = (struct r36h_output *)s;
    unsigned int available;
    int rc = -ENODATA;
    pthread_mutex_lock(&out->lock);
    if (out->pcm && pcm_get_htimestamp(out->pcm, &available, timestamp) == 0) {
        uint64_t queued = available < PERIOD * PERIODS ? PERIOD * PERIODS - available : 0;
        if (out->frames >= queued) { *frames = out->frames - queued; rc = 0; }
    }
    pthread_mutex_unlock(&out->lock);
    return rc;
}
static int open_output(struct audio_hw_device *device, audio_io_handle_t handle,
                       audio_devices_t devices, audio_output_flags_t flags,
                       struct audio_config *requested, struct audio_stream_out **stream,
                       const char *address) {
    *stream = NULL;
    if ((requested->sample_rate && requested->sample_rate != RATE) ||
        (requested->channel_mask && requested->channel_mask != AUDIO_CHANNEL_OUT_STEREO) ||
        (requested->format && requested->format != AUDIO_FORMAT_PCM_16_BIT)) {
        requested->sample_rate = RATE;
        requested->channel_mask = AUDIO_CHANNEL_OUT_STEREO;
        requested->format = AUDIO_FORMAT_PCM_16_BIT;
        return -EINVAL;
    }
    struct r36h_device *dev = (struct r36h_device *)device;
    pthread_mutex_lock(&dev->lock);
    if (dev->output) { pthread_mutex_unlock(&dev->lock); return -EBUSY; }
    struct r36h_output *out = calloc(1, sizeof(*out));
    if (!out) { pthread_mutex_unlock(&dev->lock); return -ENOMEM; }
    pthread_mutex_init(&out->lock, NULL);
    out->card = codec_card();
    out->devices = devices ? devices : AUDIO_DEVICE_OUT_SPEAKER;
    out->stream.common = (struct audio_stream) {
        .get_sample_rate = sample_rate, .set_sample_rate = set_sample_rate,
        .get_buffer_size = buffer_size, .get_channels = channels,
        .get_format = format, .set_format = set_format, .standby = standby,
        .dump = dump_stream, .set_parameters = set_parameters,
        .get_parameters = get_parameters, .add_audio_effect = effect, .remove_audio_effect = effect,
    };
    out->stream.get_latency = latency;
    out->stream.set_volume = volume;
    out->stream.write = write_pcm;
    out->stream.get_render_position = render_position;
    out->stream.get_next_write_timestamp = next_timestamp;
    out->stream.get_presentation_position = presentation_position;
    requested->sample_rate = RATE;
    requested->channel_mask = AUDIO_CHANNEL_OUT_STEREO;
    requested->format = AUDIO_FORMAT_PCM_16_BIT;
    dev->output = out;
    *stream = &out->stream;
    pthread_mutex_unlock(&dev->lock);
    return 0;
}
static void close_output(struct audio_hw_device *device, struct audio_stream_out *stream) {
    struct r36h_device *dev = (struct r36h_device *)device;
    struct r36h_output *out = (struct r36h_output *)stream;
    pthread_mutex_lock(&dev->lock);
    standby(&out->stream.common);
    dev->output = NULL;
    pthread_mutex_destroy(&out->lock);
    free(out);
    pthread_mutex_unlock(&dev->lock);
}
static int init_check(const struct audio_hw_device *d) { return 0; }
static int voice_volume(struct audio_hw_device *d, float v) { return -ENOSYS; }
static int master_volume(struct audio_hw_device *d, float v) { return -ENOSYS; }
static int mode(struct audio_hw_device *d, audio_mode_t m) { return 0; }
static int mic_mute(struct audio_hw_device *d, bool mute) { return -ENOSYS; }
static int get_mic_mute(const struct audio_hw_device *d, bool *mute) { *mute = true; return 0; }
static int device_parameters(struct audio_hw_device *d, const char *p) { return 0; }
static char *device_get_parameters(const struct audio_hw_device *d, const char *p) { return strdup(""); }
static size_t input_size(const struct audio_hw_device *d, const struct audio_config *c) { return 0; }
static int open_input(struct audio_hw_device *d, audio_io_handle_t h, audio_devices_t devices,
                      struct audio_config *c, struct audio_stream_in **s, audio_input_flags_t f,
                      const char *address, audio_source_t source) { *s = NULL; return -ENOSYS; }
static void close_input(struct audio_hw_device *d, struct audio_stream_in *s) {}
static int device_dump(const struct audio_hw_device *d, int fd) {
    dprintf(fd, "R36H native RK817 playback HAL; no built-in microphone advertised\n");
    return 0;
}
static int close_device(struct hw_device_t *device) {
    struct r36h_device *dev = (struct r36h_device *)device;
    if (dev->output) close_output(&dev->device, &dev->output->stream);
    pthread_mutex_destroy(&dev->lock);
    free(dev);
    return 0;
}
static int open_device(const struct hw_module_t *module, const char *name, struct hw_device_t **device) {
    if (strcmp(name, AUDIO_HARDWARE_INTERFACE)) return -EINVAL;
    struct r36h_device *dev = calloc(1, sizeof(*dev));
    if (!dev) return -ENOMEM;
    pthread_mutex_init(&dev->lock, NULL);
    dev->device.common = (struct hw_device_t) {
        .tag = HARDWARE_DEVICE_TAG, .version = AUDIO_DEVICE_API_VERSION_2_0,
        .module = (struct hw_module_t *)module, .close = close_device,
    };
    dev->device.init_check = init_check;
    dev->device.set_voice_volume = voice_volume;
    dev->device.set_master_volume = master_volume;
    dev->device.set_mode = mode;
    dev->device.set_mic_mute = mic_mute;
    dev->device.get_mic_mute = get_mic_mute;
    dev->device.set_parameters = device_parameters;
    dev->device.get_parameters = device_get_parameters;
    dev->device.get_input_buffer_size = input_size;
    dev->device.open_output_stream = open_output;
    dev->device.close_output_stream = close_output;
    dev->device.open_input_stream = open_input;
    dev->device.close_input_stream = close_input;
    dev->device.dump = device_dump;
    *device = &dev->device.common;
    return 0;
}
static struct hw_module_methods_t methods = { .open = open_device };
struct audio_module HAL_MODULE_INFO_SYM = {
    .common = {
        .tag = HARDWARE_MODULE_TAG,
        .module_api_version = AUDIO_MODULE_API_VERSION_0_1,
        .hal_api_version = HARDWARE_HAL_API_VERSION,
        .id = AUDIO_HARDWARE_MODULE_ID,
        .name = "R36H RK817 PCM audio", .author = "GammaOS R36H port",
        .methods = &methods,
    },
};
