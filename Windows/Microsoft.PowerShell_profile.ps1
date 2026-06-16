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

# $Profile functions
function ebrc { code $PROFILE }
function cff { clear && fastfetch }

# Runs Fastfetch
cff
