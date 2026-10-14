# SPDX-License-Identifier: Apache-2.0
# Windows PowerShell 5.1 compatible. Compile on Linux storage, not NTFS.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('checks', 'kernel', 'image')]
    [string]$Task
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# PowerShell 7 can otherwise throw before we handle a native probe's exit code.
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if ($env:RUNNER_OS -ne 'Windows' -or $env:RUNNER_ARCH -ne 'X64') {
    throw 'This workflow requires a self-hosted Windows X64 runner.'
}
foreach ($name in @('RUNNER_TEMP', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'R36H_STAGE', 'SUPPORT_SHA256')) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Missing runner environment variable: $name"
    }
}
if ($env:SUPPORT_SHA256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'Invalid build-support SHA-256.'
}
if ($env:GITHUB_RUN_ID -notmatch '^\d+$' -or $env:GITHUB_RUN_ATTEMPT -notmatch '^\d+$') {
    throw 'Invalid workflow run identity.'
}
$expectedStage = [IO.Path]::GetFullPath((Join-Path $env:RUNNER_TEMP "r36h-$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT)-$Task"))
$stage = [IO.Path]::GetFullPath($env:R36H_STAGE)
if ($stage -ne $expectedStage) {
    throw 'R36H_STAGE must point to the temporary directory for this workflow job.'
}
$inputDir = Join-Path $stage 'input'
$outputDir = Join-Path $stage "output/$Task"
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null
if (Test-Path -LiteralPath $outputDir) {
    Remove-Item -LiteralPath $outputDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$supportFile = Join-Path $inputDir 'r36h-build-support.zip'
if ($Task -eq 'checks') {
    if ([string]::IsNullOrWhiteSpace($env:SUPPORT_ZIP)) {
        throw 'Missing embedded build-support ZIP.'
    }
    [IO.File]::WriteAllBytes($supportFile, [Convert]::FromBase64String($env:SUPPORT_ZIP))
}
if (-not (Test-Path -LiteralPath $supportFile -PathType Leaf)) {
    throw 'The verified build-support artifact was not downloaded.'
}
if ((Get-FileHash -LiteralPath $supportFile -Algorithm SHA256).Hash -ne $env:SUPPORT_SHA256) {
    throw 'Build-support checksum mismatch.'
}
$jobs = 16
if (-not [string]::IsNullOrWhiteSpace($env:BUILD_JOBS)) {
    if ($env:BUILD_JOBS -notmatch '^\d{1,2}$') { throw 'BUILD_JOBS must be an integer from 1 to 64.' }
    $jobs = [int]$env:BUILD_JOBS
    if ($jobs -lt 1 -or $jobs -gt 64) { throw 'BUILD_JOBS must be from 1 to 64.' }
}
$mode = 'kernel'
if (-not [string]::IsNullOrWhiteSpace($env:MODE)) { $mode = $env:MODE }
$panel = 'keep'
if (-not [string]::IsNullOrWhiteSpace($env:PANEL)) { $panel = $env:PANEL }
$config = @{
    mode = $mode; panel = $panel; build_jobs = $jobs
    base_url = $env:BASE_URL; base_sha256 = $env:BASE_SHA
    system_url = $env:SYSTEM_URL; system_sha256 = $env:SYSTEM_SHA
    support_sha256 = $env:SUPPORT_SHA256
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $stage 'inputs.json'), ($config | ConvertTo-Json), $utf8)
$driver = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'windows-build.sh')).Replace("`r`n", "`n")
[IO.File]::WriteAllText((Join-Path $stage 'windows-build.sh'), $driver, $utf8)

$runtime = 'auto'
if (-not [string]::IsNullOrWhiteSpace($env:R36H_RUNTIME)) { $runtime = $env:R36H_RUNTIME.ToLowerInvariant() }
if ($runtime -notin @('auto', 'wsl', 'docker')) { throw 'R36H_RUNTIME must be auto, wsl or docker.' }

if ($runtime -in @('auto', 'wsl')) {
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($null -ne $wsl) {
        $oldPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $listing = & $wsl.Source --list --quiet 2>$null
        $listExit = $LASTEXITCODE
        $ErrorActionPreference = $oldPreference
        if ($listExit -eq 0) {
            $distros = @($listing | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
            if (-not [string]::IsNullOrWhiteSpace($env:R36H_WSL_DISTRO)) {
                $distros = @($distros | Where-Object { $_ -eq $env:R36H_WSL_DISTRO })
            }
            foreach ($distro in $distros) {
                if ($distro -like 'docker-desktop*') { continue }
                $ErrorActionPreference = 'Continue'
                $release = (& $wsl.Source --distribution $distro --user root --exec cat /etc/os-release 2>$null | Out-String) -replace "`0", ''
                $releaseExit = $LASTEXITCODE
                $arch = (& $wsl.Source --distribution $distro --user root --exec uname -m 2>$null | Out-String).Trim()
                $archExit = $LASTEXITCODE
                $ErrorActionPreference = $oldPreference
                if ($releaseExit -ne 0 -or $archExit -ne 0 -or $arch -ne 'x86_64') { continue }
                if ($release -notmatch '(?m)^ID="?ubuntu"?\s*$' -or $release -notmatch '(?m)^VERSION_ID="?(22\.04|24\.04)"?\s*$') { continue }
                $linuxStage = (& $wsl.Source --distribution $distro --user root --exec wslpath -a -u $stage | Out-String).Trim()
                if ($LASTEXITCODE -ne 0 -or -not $linuxStage.StartsWith('/')) { throw 'Cannot access the runner temporary directory from WSL.' }
                Write-Host "Using WSL Ubuntu distribution: $distro"
                & $wsl.Source --distribution $distro --user root --exec bash "$linuxStage/windows-build.sh" $linuxStage $Task
                $buildExit = $LASTEXITCODE
                if ($buildExit -ne 0) { throw "Linux $Task task failed with exit code $buildExit. See the build log artifact." }
                exit 0
            }
        }
    }
    if ($runtime -eq 'wsl' -or -not [string]::IsNullOrWhiteSpace($env:R36H_WSL_DISTRO)) {
        throw 'Install Ubuntu 24.04 for WSL under the Windows account running the runner. See ci/README.md.'
    }
}

if ($runtime -in @('auto', 'docker')) {
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -ne $docker) {
        $oldPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $osType = (& $docker.Source info --format '{{.OSType}}' 2>$null | Out-String).Trim()
        $dockerExit = $LASTEXITCODE
        $ErrorActionPreference = $oldPreference
        if ($dockerExit -eq 0 -and $osType -eq 'linux') {
            if ($stage.Contains(',')) { throw 'Docker bind-mount paths cannot contain commas; choose another runner work folder.' }
            $container = "r36h-$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT)-$Task-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
            Write-Host 'Using Docker Linux engine with Ubuntu 24.04.'
            try {
                & $docker.Source run --rm --name $container --mount "type=bind,source=$stage,target=/stage" --env DEBIAN_FRONTEND=noninteractive ubuntu:24.04 bash /stage/windows-build.sh /stage $Task
                $buildExit = $LASTEXITCODE
                if ($buildExit -ne 0) { throw "Linux $Task task failed with exit code $buildExit. See the build log artifact." }
            }
            finally {
                $ErrorActionPreference = 'Continue'
                & $docker.Source rm --force $container 2>$null | Out-Null
                $ErrorActionPreference = $oldPreference
                $global:LASTEXITCODE = 0
            }
            exit 0
        }
    }
}
throw 'This Windows runner needs Ubuntu 22.04/24.04 in WSL, or a running Docker Desktop Linux engine accessible to its service account. See ci/README.md.'
