# Native GammaOS Core port for R36H

This CI branch now develops a direct port from the pinned GammaOS Android TV 13
source. The earlier external Android port, its kernel artifacts and its SD image
are not inputs to this build. `develop` remains the original source branch.

The Windows X64 self-hosted runner uses its existing Ubuntu-24.04 WSL installation.
Both CI files and the large Android checkout live on Linux paths to avoid the
Windows archive extractor's path limits. Linux source is cached at
`/var/cache/gammaos-r36h-native/android`. The workflow excludes committed `.repo`,
`out`, Darwin and Windows prebuilts, verifies selected LFS objects by their
committed SHA-256, and uses separate native build outputs.

The full workflow builds Rockchip 5.10 with a native GPIO/ADC gamepad driver,
U-Boot, GammaOS Android TV 13, an RK3326 vendor image, the RK817 audio HAL and a
first-stage ramdisk. It then creates a new GPT SD image with BOOT, system, vendor
and 8 GiB userdata. No existing Android SD image is an assembly input. Kernel
compilation defaults to 16 workers; Android defaults to 8 for this 32 GiB runner.

An image artifact is uploaded only after compilation, ext4 checks, native init
and HAL checks, wired-only kernel audit, and primary/backup GPT validation pass.
The image is a **hardware-untested userdebug build with permissive SELinux**.
Use a spare microSD of at least 16 GB. Its default public reference profile is
R36H V21; edit `BOOT/extlinux/extlinux.conf` to select the included V20 reference.
The U-Boot bring-up starts from its ODROID Go2 RK3326 configuration; it is not a
claim of a validated R36H bootloader. Physical boot testing is still required.

Native setup installs GammaOS's launcher and APKs without restoring another
device's Magisk data, running its RK3566 input remapper, or flashing its boot
image. Emulator cores/content and app settings can be configured in each app.
Build metadata and source pins are in `port/r36h/SOURCES.json` and the artifact
manifest. A passing build establishes structure and compilation, not board
compatibility.

Hardware remains unverified: public R36H V20/V21 board reference files exist,
but the user's board and panel have not been identified. The port must retain
USB RNDIS host, USB Ethernet and PPP, with all wireless kernel drivers disabled.
