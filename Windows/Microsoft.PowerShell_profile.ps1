#   ██████████  █████       ██████████ ██████   ██ ██████████  ██████████ ██████████   
#     ███   ████ ████        ███    ███  ███   ████      ████   ███        ████   ████ 
#    ████   ███  ███        ████   ████ █████ ████      ████   ████        ████   ███  
#    ███   ████ ████        ██████████   ███████      ████     ███████    ████   ████  
#   ████   ███  ███        ████   ████    ████       ████     ████        ████   ███   
#  ████   ████ ████        ███    ███     ███       ███       ███        ████   ████   
#    ██████    ██████████ ████   ████    ████     ██████████ ███████████ ████   ███    

# Starts Zoxide
Invoke-Expression (& { (zoxide init powershell | Out-String) })

# Interactive visual menu for Tab completions
Set-PSReadlineKeyHandler -Key Tab -Function MenuComplete

# IDE-style predictive text from terminal history
Set-PSReadLineOption -PredictionSource History
Set-PSReadLineOption -PredictionViewStyle List

# Quick search history using partial keywords + arrows
Set-PSReadlineKeyHandler -Key UpArrow -Function HistorySearchBackward
Set-PSReadlineKeyHandler -Key DownArrow -Function HistorySearchForward


# Custom yayf implmementation via winget
function wingetf {
    winget search --query "" | fzf --preview 'winget show {2}' --preview-window=down:75% --with-nth=1,2 --bind "enter:execute(winget install {2})"
}

# Aliases
Set-Alias grep findstr
 
Set-Alias claer clear
Set-Alias cøear clear
Set-Alias cøaer clear

Set-Alias which gcm

Remove-Item alias:cd
Set-Alias cd z

function bd {
    Set-Location -
}

# Shows hidden items in ls
Remove-Item alias:ls
function ls {
    Get-ChildItem -Force
}

function nepr {
    param(
        [Parameter(Position = 0)]
        [string]$ProjectName
    )

    if ([string]::IsNullOrWhiteSpace($ProjectName)) {
        Write-Host "Usage: nepr <project_name>"
        return
    }

    $projectDir = Join-Path (Join-Path $HOME 'Forgejo') $ProjectName

    if (Test-Path -LiteralPath $projectDir -PathType Container) {
        Write-Host "Project '$ProjectName' already exists. Entering it."
    }
    elseif (Test-Path -LiteralPath $projectDir) {
        Write-Host "A file named '$ProjectName' already exists at $projectDir. Aborting."
        return
    }
    else {
        New-Item -ItemType Directory -Path $projectDir -Force | Out-Null
    }

    Set-Location -LiteralPath $projectDir
    Get-Location
    Get-ChildItem
}

function rmpr {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Position = 0)]
        [string]$ProjectName
    )

    if ([string]::IsNullOrWhiteSpace($ProjectName)) {
        Write-Host "Usage: rmpr <project_name>"
        return
    }

    $projectsRoot = Join-Path $HOME 'Forgejo'
    $projectDir   = Join-Path $projectsRoot $ProjectName

    if (-not (Test-Path -LiteralPath $projectDir -PathType Container)) {
        Write-Host "Project '$ProjectName' does not exist at $projectDir."
        return
    }

    # If you're currently inside the project (or a subfolder), step out first —
    # you can't delete the directory you're standing in.
    $current        = (Get-Location).Path
    $resolvedTarget = (Resolve-Path -LiteralPath $projectDir).Path
    $sep            = [System.IO.Path]::DirectorySeparatorChar
    if ($current.Equals($resolvedTarget, [StringComparison]::OrdinalIgnoreCase) -or
        $current.StartsWith($resolvedTarget + $sep, [StringComparison]::OrdinalIgnoreCase)) {
        Set-Location -LiteralPath $projectsRoot
    }

    if ($PSCmdlet.ShouldProcess($projectDir, 'Remove project directory and all contents')) {
        Remove-Item -LiteralPath $projectDir -Recurse -Force
        Write-Host "Removed project '$ProjectName'."
    }
}

# $Profile functions
function ebrc { code $PROFILE }
function cff { clear && fastfetch }

# ── Linux-style functions ──────────────────────────────────────────────
# Files & listing
function touch {
    param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Path)
    foreach ($p in $Path) {
        if (Test-Path $p) { (Get-Item $p).LastWriteTime = Get-Date }
        else { New-Item -ItemType File -Path $p | Out-Null }
    }
}
function ll { Get-ChildItem -Force @args | Format-Table Mode, LastWriteTime, Length, Name -AutoSize }
function la { Get-ChildItem -Force @args }
function l  { Get-ChildItem @args }
function mkcd { param([Parameter(Mandatory)][string]$Dir) New-Item -ItemType Directory -Force -Path $Dir | Out-Null; Set-Location -LiteralPath $Dir }
function ff {
    param([Parameter(Mandatory)][string]$Pattern, [string]$Path = '.')
    Get-ChildItem -Path $Path -Recurse -Filter "*$Pattern*" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
}

# Text filters (pipeline- or file-aware)
function head { param([int]$n = 10, [string]$Path) if ($Path) { Get-Content -LiteralPath $Path -TotalCount $n } else { $input | Select-Object -First $n } }
function tail {
    param([int]$n = 10, [switch]$f, [string]$Path)
    if ($Path) { if ($f) { Get-Content -LiteralPath $Path -Tail $n -Wait } else { Get-Content -LiteralPath $Path -Tail $n } }
    else { $input | Select-Object -Last $n }
}
function wc {
    param([string]$Path)
    $text  = if ($Path) { Get-Content -LiteralPath $Path -Raw } else { $input | Out-String }
    $lines = ($text -split "`n").Count - 1
    $words = ($text -split '\s+' | Where-Object { $_ -ne '' }).Count
    [pscustomobject]@{ Lines = $lines; Words = $words; Chars = $text.Length }
}
function sed {
    param([string]$Pattern, [string]$Replacement, [string]$Path)
    if ($Path) { (Get-Content -LiteralPath $Path) -replace $Pattern, $Replacement } else { $input -replace $Pattern, $Replacement }
}
function tac { param([string]$Path) $lines = @(if ($Path) { Get-Content -LiteralPath $Path } else { $input }); [array]::Reverse($lines); $lines }

# System & processes
function df {
    Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -or $_.Free } |
        Select-Object Name,
            @{ n = 'Used(GB)'; e = { [math]::Round($_.Used / 1GB, 1) } },
            @{ n = 'Free(GB)'; e = { [math]::Round($_.Free / 1GB, 1) } },
            @{ n = 'Use%';     e = { if ($_.Used + $_.Free) { [math]::Round($_.Used / ($_.Used + $_.Free) * 100) } else { 0 } } } |
        Format-Table -AutoSize
}
function du {
    param([string]$Path = '.')
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    $targets = if ($item -and -not $item.PSIsContainer) { @($item) } else { Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue }
    $targets | ForEach-Object {
        $bytes = if ($_.PSIsContainer) { (Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } else { $_.Length }
        [pscustomobject]@{ Bytes = [long]$bytes; Name = $_.Name }
    } | Sort-Object Bytes -Descending | Format-Table @{ n = 'Size'; e = {
            $b = $_.Bytes
            if     ($b -ge 1GB) { '{0,8:N1} GB' -f ($b / 1GB) }
            elseif ($b -ge 1MB) { '{0,8:N1} MB' -f ($b / 1MB) }
            elseif ($b -ge 1KB) { '{0,8:N1} KB' -f ($b / 1KB) }
            else                { '{0,8} B'    -f $b } } }, Name -AutoSize
}
function uptime {
    $b = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $u = (Get-Date) - $b
    "up {0}d {1}h {2}m (since {3:yyyy-MM-dd HH:mm})" -f $u.Days, $u.Hours, $u.Minutes, $b
}
function env { if ($args) { Get-Item "Env:$($args[0])" -ErrorAction SilentlyContinue } else { Get-ChildItem Env: | Sort-Object Name } }
function export {
    param([Parameter(Mandatory)][string]$Assignment)
    $i = $Assignment.IndexOf('=')
    if ($i -lt 1) { throw "usage: export NAME=VALUE" }
    Set-Item -Path "Env:$($Assignment.Substring(0, $i))" -Value $Assignment.Substring($i + 1)
}
function pkill { param([Parameter(Mandatory)][string]$Name) Stop-Process -Name ($Name -replace '\.exe$') -Force -ErrorAction Stop }

# ───────────────────────────────────────────────────────────────────────

# Runs Fastfetch
cff
#f45873b3-b655-43a6-b217-97c00aa0db58 PowerToys CommandNotFound module

Import-Module -Name Microsoft.WinGet.CommandNotFound
#f45873b3-b655-43a6-b217-97c00aa0db58
