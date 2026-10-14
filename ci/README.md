# R36H builds on a Windows self-hosted runner

The workflow targets the default runner labels `self-hosted`, `Windows`, `X64`.
Windows PowerShell 5.1 handles the job. Linux compiler and image tools run in an
existing Ubuntu WSL distribution, or in Docker Desktop with its Linux engine.
Kernel sources and objects are kept on Linux storage; only inputs, artifacts and
logs cross the Windows filesystem. The pinned kernel, panel references, PPP and
USB/RNDIS support are unchanged. Wireless and Bluetooth drivers stay disabled.

## Prepare the runner once

Use either option under the Windows account that runs the GitHub runner.

1. **WSL:** install Ubuntu 24.04 with `wsl --install -d Ubuntu-24.04`, restart
   Windows if requested, and launch Ubuntu once to complete setup. Confirm that
   `wsl -d Ubuntu-24.04 -u root --exec uname -m` prints `x86_64` from that account.
   Ubuntu 22.04 is also supported. A distribution installed for another Windows
   user may not be visible to the runner service.
2. **Docker:** start Docker Desktop using Linux containers. Confirm that
   `docker info --format '{{.OSType}}'` prints `linux` from the runner account.

Start the runner with `run.cmd` or its configured service. WSL is tried first;
Docker is used when no supported Ubuntu distribution is available. Dependencies
are installed inside Linux automatically. The workflow does not enable Windows
features, restart Windows, or install Docker Desktop.

Provide at least 10 GiB free in the Linux filesystem for the kernel job. Image
assembly needs additional space for both input images, a writable output image,
compression and copies to Windows. Four compiler workers are used by default.

Optional repository **Actions variables**:

- `R36H_RUNTIME`: `auto` (default), `wsl`, or `docker`.
- `R36H_WSL_DISTRO`: the exact installed Ubuntu distribution name.
- `R36H_BUILD_JOBS`: compiler workers from 1 to 64.

The workflow runs on pushes to `r36h-build-ci`. Use the existing CI branch for
updates; it contains only build infrastructure and should not be merged as a
replacement for the Android source branch. A push builds the kernel and seven
reference DTBs. It does not compile a complete GammaOS Android system or confirm
that a panel DTB boots an R36H.

The optional `assemble` mode needs a working Treble SD base and an ARM64 GammaOS
system download, both with SHA-256s. Keep the base DTB unless the device's panel
is positively identified. The output remains experimental.

Build outputs and logs are uploaded as Actions artifacts. Temporary Windows
staging files are removed after upload; each Linux task removes its own temporary
source and object directory. If a job reports that neither runtime is available,
complete the setup above under the runner account and rerun that job.
