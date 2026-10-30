# ENLENS one-line install for Windows (0.10). Paste this in PowerShell (Start menu, type PowerShell):
#
#   powershell -ExecutionPolicy Bypass -c "irm https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.ps1 | iex"
#
# It needs no git, no Python and no administrator rights:
#   1. gets uv (a small tool from Astral that installs Python programs), unless it is already here;
#   2. downloads the ENLENS package of this release and checks it against the release's checksums;
#   3. installs ENLENS with uv, which brings its own Python (3.12) and keeps it apart from any other Python;
#   4. makes the ENLENS icon (Start menu and Desktop) and opens ENLENS.
# Running the same line again installs the newest release over this one (quit ENLENS first): your projects stay.
#
# Options, set before running the line ($env:NAME = "value"):
#   ENLENS_LOCAL_ONLY=1   nothing may leave this computer (no cloud AI; built into the icon)
#   ENLENS_HOME=<folder>  keep projects and settings in another folder (built into the icon)
#   ENLENS_VERSION=0.10.0 install that release instead of the one this script came with
#   ENLENS_WHEEL=<file>   install this package file instead of downloading one (for testing a build)
#   ENLENS_NO_OPEN=1      do not open ENLENS at the end

function Install-Enlens {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with its progress bar
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072 } catch { }

    $repo = if ($env:ENLENS_REPO) { $env:ENLENS_REPO } else { 'dvaud/claim_checker_demo' }
    $version = if ($env:ENLENS_VERSION) { $env:ENLENS_VERSION } else { '@ENLENS_VERSION@' }
    $extras = 'connector,fast,pdfminer,ocr'
    if ($version.StartsWith('@') -and -not $env:ENLENS_WHEEL) {
        throw "this copy of install.ps1 does not name a version. Use the one from a GitHub Release: https://github.com/$repo/releases"
    }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('enlens-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        # 1. uv -------------------------------------------------------------------------------
        function Find-Uv {
            $c = Get-Command uv -ErrorAction SilentlyContinue
            if ($c) { return $c.Source }
            foreach ($p in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
                if (Test-Path $p) { return $p }
            }
            return $null
        }
        $uv = Find-Uv
        if (-not $uv) {
            Write-Host '1/4  Getting uv, which installs ENLENS and its own Python...'
            powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
            $uv = Find-Uv
            if (-not $uv) { throw 'uv was installed, but cannot be found. Open a new PowerShell window and run the line again.' }
        } else {
            Write-Host "1/4  uv is here already ($uv)."
        }

        # 2. the package ----------------------------------------------------------------------
        if ($env:ENLENS_WHEEL) {
            if (-not (Test-Path $env:ENLENS_WHEEL)) { throw "no such file: $env:ENLENS_WHEEL" }
            $wheelName = Split-Path $env:ENLENS_WHEEL -Leaf
            $wheel = Join-Path $tmp $wheelName
            Copy-Item $env:ENLENS_WHEEL $wheel
            Write-Host "2/4  Using the package $wheelName."
        } else {
            $wheelName = "enlens_claims-$version-py3-none-any.whl"
            $base = "https://github.com/$repo/releases/download/v$version"
            $wheel = Join-Path $tmp $wheelName
            Write-Host "2/4  Downloading ENLENS $version..."
            try {
                Invoke-WebRequest -UseBasicParsing -Uri "$base/$wheelName" -OutFile $wheel
                Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS" -OutFile (Join-Path $tmp 'SHA256SUMS')
            } catch { throw "the download from $base did not work. Are you online? ($($_.Exception.Message))" }
            $want = ''
            foreach ($line in Get-Content (Join-Path $tmp 'SHA256SUMS')) {
                $parts = $line -split '\s+'
                if ($parts.Count -ge 2 -and $parts[1].TrimStart('*') -eq $wheelName) { $want = $parts[0].ToLower() }
            }
            $got = (Get-FileHash -Algorithm SHA256 $wheel).Hash.ToLower()
            if (-not $want -or $want -ne $got) {
                throw "the downloaded package does not match the release's checksum (nothing was installed). Try again later."
            }
        }

        # 3. install --------------------------------------------------------------------------
        Write-Host '3/4  Installing ENLENS (the first time this also fetches Python 3.12; a minute or two)...'
        $uri = ([System.Uri](Resolve-Path $wheel).Path).AbsoluteUri
        $env:UV_PYTHON_PREFERENCE = 'only-managed'
        & $uv tool install --force --quiet --python 3.12 "enlens-claims[$extras] @ $uri"
        if ($LASTEXITCODE -ne 0) {
            throw 'uv could not install ENLENS (see the lines above). If ENLENS is running, choose Quit ENLENS in it and run the line again.'
        }
        $bin = (& $uv tool dir --bin).Trim()
        $enlens = Join-Path $bin 'enlens.exe'
        if (-not (Test-Path $enlens)) { throw "ENLENS was installed, but $enlens is missing." }

        # 4. the icon, the Claude Code plugin, and open -------------------------------------------
        Write-Host '4/4  Making the ENLENS icon...'
        $postArgs = @('post-install', '--by', 'script')
        if ($env:ENLENS_HOME) { $postArgs += @('--home', $env:ENLENS_HOME) }
        if (-not $env:ENLENS_NO_OPEN) { $postArgs += '--open' }
        & $enlens @postArgs
        if ($LASTEXITCODE -ne 0) { throw 'the last step did not work (see above).' }
        Write-Host ''
        Write-Host 'Done. Next time, open ENLENS from its icon (Start menu or Desktop). To update it later, run the same line again.'
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

try {
    Install-Enlens
} catch {
    Write-Host ''
    Write-Host "ENLENS could not be installed: $($_.Exception.Message)" -ForegroundColor Red
    # `irm … | iex` runs this in the person's own window: never `exit`, which would close it
}
