$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$build = Join-Path $root "build_win"
$dist = Join-Path $build "dist"
$env:ADAPTER_SOURCE_ROOT = $root

python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
New-Item -ItemType Directory -Path $build -Force | Out-Null
Copy-Item (Join-Path $PSScriptRoot "entry_adapter.py") $build -Force
Copy-Item (Join-Path $PSScriptRoot "adapter.spec") $build -Force
Push-Location $build
try {
    python -m PyInstaller --noconfirm --clean --distpath dist --workpath work adapter.spec
} finally {
    Pop-Location
}

$node = python -c "import os,playwright; print(os.path.join(os.path.dirname(playwright.__file__), 'driver', 'node.exe'))"
if (-not (Test-Path $node)) {
    throw "Playwright node.exe was not found at $node"
}
Copy-Item $node (Join-Path $dist "node.exe") -Force
Copy-Item (Join-Path $root ".env.example") $dist -Force
Copy-Item (Join-Path $PSScriptRoot "使用说明.txt") $dist -Force
Copy-Item (Join-Path $PSScriptRoot "启动连接器.bat") $dist -Force

$envFile = Join-Path $dist ".env"
@"
RABBITMQ_HOST=127.0.0.1
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_PORT=1
ADAPTER_GATEWAY_URL=https://adapter.example.com
"@ | Set-Content -Path $envFile -Encoding UTF8

Push-Location $dist
try {
    .\adapter.exe --version
    .\adapter.exe --help | Out-Null
    foreach ($platform in @("boss", "douyin", "rednote")) {
        .\adapter.exe doctor --platform $platform --skip-platform
        if ($LASTEXITCODE -ne 0) { throw "doctor failed for $platform" }
    }
    $process = Start-Process -FilePath ".\adapter.exe" -ArgumentList "serve --no-open-browser --no-restart --dotenv .env" -PassThru
    try {
        $ready = $false
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 250
            try {
                $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8765/health/live" -TimeoutSec 2
                if ($response.StatusCode -eq 200) { $ready = $true; break }
            } catch {}
        }
        if (-not $ready) { throw "adapter.exe health smoke did not become ready" }
        $session = Invoke-RestMethod -UseBasicParsing "http://127.0.0.1:8765/api/session" -TimeoutSec 2
        $headers = @{ "X-Adapter-Control" = $session.control_token }
        Invoke-RestMethod -UseBasicParsing -Method Post -Uri "http://127.0.0.1:8765/api/shutdown" -Headers $headers -ContentType "application/json" -Body "{}" -TimeoutSec 2 | Out-Null
        if (-not $process.WaitForExit(10000)) {
            throw "adapter.exe did not shut down cleanly"
        }
    } finally {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        $process.WaitForExit()
    }
} finally {
    Pop-Location
    Remove-Item $envFile -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $dist "adapter_data") -Recurse -Force -ErrorAction SilentlyContinue
}
