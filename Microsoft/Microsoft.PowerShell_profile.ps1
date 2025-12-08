# Custom yayf implmementation via winget
function wingetf {
    winget search --query "" | fzf --preview 'winget show {2}' --preview-window=down:75% --with-nth=1,2 --bind "enter:execute(winget install {2})"
}

# Aliases
Set-Alias grep findstr
 
Set-Alias claer clear

# $Profile functions
function ebrc { notepad $PROFILE }
function rbrc { . $PROFILE }
function cff { clear && fastfetch }

# Runs Fastfetch
cff
