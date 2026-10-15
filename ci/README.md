# Native GammaOS Core port for R36H

This CI branch now develops a direct port from the pinned GammaOS Android TV 13
source. The earlier external Android port, its kernel artifacts and its SD image
are not inputs to this build. `develop` remains the original source branch.

The Windows X64 self-hosted runner uses its existing Ubuntu-24.04 WSL installation.
Linux source is cached at `/var/cache/gammaos-r36h-native/android`. The workflow
excludes committed `.repo`, `out`, Darwin and Windows prebuilts and uses fresh
native build outputs. Source preparation is explicitly separate from producing
a complete image.

Hardware remains unverified: public R36H V20/V21 board reference files exist,
but the user's board and panel have not been identified. The port must retain
USB RNDIS host, USB Ethernet and PPP, with all wireless kernel drivers disabled.
