# SPDX-License-Identifier: Apache-2.0
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit.mk)
$(call inherit-product, device/google/atv/products/atv_generic_system.mk)
$(call inherit-product, device/google/atv/products/atv_system_ext.mk)
$(call inherit-product, device/google/atv/products/atv_product.mk)
# GammaOS loads the Lineage platform library in system_server. Install its
# library, resources and service permissions using the source tree's config.
include vendor/lineage/config/lineage_sdk_common.mk
$(call inherit-product, device/gameconsole/r36h/device.mk)

PRODUCT_NAME := gamma_r36h
PRODUCT_DEVICE := r36h
PRODUCT_BRAND := GammaOS
PRODUCT_MODEL := R36H GammaOS Core Experimental
PRODUCT_MANUFACTURER := GameConsole
# This is an experimental port for an older board, using the Android 11 HAL
# compatibility level. Android, vendor libraries and ramdisk build from this
# same GammaOS Android 13 source tree.
PRODUCT_SHIPPING_API_LEVEL := 30
PRODUCT_USE_DYNAMIC_PARTITIONS := false
PRODUCT_USE_DYNAMIC_PARTITION_SIZE := true
PRODUCT_BUILD_BOOT_IMAGE := true
PRODUCT_BUILD_VENDOR_IMAGE := true
PRODUCT_BUILD_USERDATA_IMAGE := true
PRODUCT_BUILD_RECOVERY_IMAGE := false
PRODUCT_BUILD_SUPER_PARTITION := false
PRODUCT_BUILD_SUPER_EMPTY_IMAGE := false
PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := false
PRODUCT_ARTIFACT_PATH_REQUIREMENT_ALLOWED_LIST += vendor/% root/%
PRODUCT_PACKAGE_OVERLAYS += device/gameconsole/r36h/overlay
PRODUCT_ENFORCE_RRO_EXCLUDED_OVERLAYS += device/gameconsole/r36h/overlay
PRODUCT_SYSTEM_PROPERTIES += \
    ro.sf.lcd_density=160 \
    ro.gamma.r36h.experimental=true \
    ro.config.low_ram=true
PRODUCT_VENDOR_PROPERTIES += \
    ro.hardware=r36h \
    ro.soc.manufacturer=Rockchip \
    ro.soc.model=RK3326 \
    ro.hardware.egl=mali \
    ro.hardware.hwcomposer=drm \
    ro.hardware.gralloc=bifrost \
    ro.opengles.version=196610 \
    vendor.gralloc.no_afbc_for_fb_target_layer=1

