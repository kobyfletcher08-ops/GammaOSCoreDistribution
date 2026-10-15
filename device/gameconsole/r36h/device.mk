# SPDX-License-Identifier: Apache-2.0
LOCAL_PATH := device/gameconsole/r36h

PRODUCT_PACKAGES += \
    TvProvision LeanbackIME \
    hwcomposer.drm \
    android.hardware.graphics.composer@2.4-service \
    android.hardware.graphics.allocator-V1-service \
    android.hardware.graphics.mapper@4.0-impl-bifrost \
    libGLES_mali \
    android.hardware.health@2.1-service \
    android.hardware.health@2.1-impl \
    android.hardware.gatekeeper@1.0-service.software \
    android.hardware.keymaster@4.1-service \
    android.hardware.audio.service \
    android.hardware.audio@7.1-impl \
    android.hardware.audio.effect@7.0-impl \
    audio.primary.r36h audio.usb.default audio.r_submix.default \
    android.hardware.lights-service.rockchip \
    android.hardware.power-service.rockchip \
    r36h-netdiag r36h_busybox pppd pppol2tp-android pppopptp-android \
    tinyplay tinycap tinymix tinypcminfo \
    e2fsck resize2fs

PRODUCT_COPY_FILES += \
    $(LOCAL_PATH)/fstab.r36h:$(TARGET_COPY_OUT_RAMDISK)/first_stage_ramdisk/fstab.r36h \
    $(LOCAL_PATH)/fstab.r36h:$(TARGET_COPY_OUT_VENDOR)/etc/fstab.r36h \
    $(LOCAL_PATH)/init.r36h.rc:$(TARGET_COPY_OUT_VENDOR)/etc/init/hw/init.r36h.rc \
    $(LOCAL_PATH)/ueventd.rc:$(TARGET_COPY_OUT_VENDOR)/etc/ueventd.rc \
    $(LOCAL_PATH)/R36H_Gamepad.kl:$(TARGET_COPY_OUT_VENDOR)/usr/keylayout/R36H_Gamepad.kl \
    $(LOCAL_PATH)/audio_policy_configuration.xml:$(TARGET_COPY_OUT_VENDOR)/etc/audio_policy_configuration.xml \
    frameworks/av/services/audiopolicy/config/usb_audio_policy_configuration.xml:$(TARGET_COPY_OUT_VENDOR)/etc/usb_audio_policy_configuration.xml \
    frameworks/av/services/audiopolicy/config/r_submix_audio_policy_configuration.xml:$(TARGET_COPY_OUT_VENDOR)/etc/r_submix_audio_policy_configuration.xml \
    frameworks/av/services/audiopolicy/config/audio_policy_volumes.xml:$(TARGET_COPY_OUT_VENDOR)/etc/audio_policy_volumes.xml \
    frameworks/av/services/audiopolicy/config/default_volume_tables.xml:$(TARGET_COPY_OUT_VENDOR)/etc/default_volume_tables.xml \
    frameworks/native/data/etc/android.hardware.usb.host.xml:$(TARGET_COPY_OUT_VENDOR)/etc/permissions/android.hardware.usb.host.xml \
    frameworks/native/data/etc/android.hardware.gamepad.xml:$(TARGET_COPY_OUT_VENDOR)/etc/permissions/android.hardware.gamepad.xml

# The GPU is the RK3326's Mali-G31 (tDVx), not an RK3566 Mali-G52.
include vendor/rockchip/common/gpu/MaliTDVx.mk
