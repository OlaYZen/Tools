#!/bin/bash     

#   ██████████  █████       ██████████ ██████   ██ ██████████  ██████████ ██████████   
#     ███   ████ ████        ███    ███  ███   ████      ████   ███        ████   ████ 
#    ████   ███  ███        ████   ████ █████ ████      ████   ████        ████   ███  
#    ███   ████ ████        ██████████   ███████      ████     ███████    ████   ████  
#   ████   ███  ███        ████   ████    ████       ████     ████        ████   ███   
#  ████   ████ ████        ███    ███     ███       ███       ███        ████   ████   
#    ██████    ██████████ ████   ████    ████     ██████████ ███████████ ████   ███    

iatest=$(expr index "$-" i)

alias cff='clear && fastfetch'

if [ -f /usr/bin/fastfetch ]; then
	cff
fi

# Source global definitions
if [ -f /etc/bashrc ]; then
	. /etc/bashrc
fi

# Enable bash programmable completion features in interactive shells
if [ -f /usr/share/bash-completion/bash_completion ]; then
	. /usr/share/bash-completion/bash_completion
elif [ -f /etc/bash_completion ]; then
	. /etc/bash_completion
fi

# Disable the bell
if [[ $iatest -gt 0 ]]; then bind "set bell-style visible"; fi

# Ignore case on auto-completion
# Note: bind used instead of sticking these in .inputrc
if [[ $iatest -gt 0 ]]; then bind "set completion-ignore-case on"; fi

# Show auto-completion list automatically, without double tab
if [[ $iatest -gt 0 ]]; then bind "set show-all-if-ambiguous On"; fi


alias cd='z'

# cd into the old directory
alias bd='cd "$OLDPWD"'

# To have colors for ls and all grep commands such as grep, egrep and zgrep
export CLICOLOR=1
export LS_COLORS='no=00:fi=00:di=00;34:ln=01;36:pi=40;33:so=01;35:do=01;35:bd=40;33;01:cd=40;33;01:or=40;31;01:ex=01;32:*.tar=01;31:*.tgz=01;31:*.arj=01;31:*.taz=01;31:*.lzh=01;31:*.zip=01;31:*.z=01;31:*.Z=01;31:*.gz=01;31:*.bz2=01;31:*.deb=01;31:*.rpm=01;31:*.jar=01;31:*.jpg=01;35:*.jpeg=01;35:*.gif=01;35:*.bmp=01;35:*.pbm=01;35:*.pgm=01;35:*.ppm=01;35:*.tga=01;35:*.xbm=01;35:*.xpm=01;35:*.tif=01;35:*.tiff=01;35:*.png=01;35:*.mov=01;35:*.mpg=01;35:*.mpeg=01;35:*.avi=01;35:*.fli=01;35:*.gl=01;35:*.dl=01;35:*.xcf=01;35:*.xwd=01;35:*.ogg=01;35:*.mp3=01;35:*.wav=01;35:*.xml=00;31:'
#export GREP_OPTIONS='--color=auto' #deprecated

# Edit aliases
alias ebrc='code ~/.bashrc'
alias ehypr='code ~/.config/hypr'
alias eff='code ~/.config/fastfetch'
alias eal='code ~/.config/alacritty'
alias eki='code ~/.config/kitty'
alias eyz='code ~/.config/YZ-Shell'

# New Project
nepr() {
    if [ -z "$1" ]; then
        echo "Usage: nepr <project_name>"
        return 1
    fi

    project_dir="$HOME/projects/$1"
    mkdir -p "$project_dir"
    cd "$project_dir" || return
}


# Refresh bashrc
alias rbrc='source ~/.bashrc'

# Check trickplay folder size

alias chktrickplay="find /path/to/media -type d -name '*.trickplay' \
  -not -path '*/Immich/*' \
  -not -path '*/Music/*' \
  -not -path '*/Nvidia/*' \
  -not -path '*/Downloads/*' \
  -exec du -sb {} + | awk '{sum += \$1} END {printf \"%.2f GB\n\", sum/1024/1024/1024}'"

# Removes the need for sudo for reboot
alias reboot='shutdown -r'

# Expand the history size
export HISTFILESIZE=100000
export HISTSIZE=5000
export HISTTIMEFORMAT="%F %T " # add timestamp to history
export HISTCONTROL=erasedups:ignoredups:ignorespace
export VCPKG_ROOT=~/vcpkg
export PATH=$VCPKG_ROOT:$PATH

# Check the window size after each command and, if necessary, update the values of LINES and COLUMNS
shopt -s checkwinsize

# Causes bash to append to history instead of overwriting it so if you start a new terminal, you have old session history
shopt -s histappend
PROMPT_COMMAND='history -a'


# set up XDG folders
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
alias ll='ls -alF'
alias grep='grep --color=auto'
alias yayf="yay -Slq | fzf --multi --preview 'yay -Sii {1}' --preview-window=down:50% | xargs -ro yay -S"
alias yayr="yay -Q | fzf --multi --preview 'yay -Sii {1}' --preview-window=down:50% | xargs -ro yay -S"

function historyf() {
    history | tac | fzf \
        --preview 'echo {4..} | fold -s -w $FZF_PREVIEW_COLUMNS' \
        --preview-window=down:15% \
        --bind "enter:execute-silent(echo {4..} | wl-copy; echo {4..} > /dev/tty)+abort"
}

# If vencord breaks. Which is every day...
function vencord() {
    sh -c "$(curl -sS https://raw.githubusercontent.com/Vendicated/VencordInstaller/main/install.sh)"
}

findtext() {
    local path="${1:-/}"  # Use first argument as path, or default to /

    read -p "Enter the pattern to search for: " pattern

    # Expand ~ if used as path
    path=$(eval echo "$path")

    sudo rg --hidden --color=always --heading --line-number \
        --glob '!proc/**' --glob '!sys/**' --glob '!dev/**' \
        "$pattern" "$path" 2>/dev/null
}


alias cp='cp -i'
alias claer='clear'
alias mv='mv -i'
alias mkdir='mkdir -p'
alias py='python3'


alias less='less -R'

alias ping='ping -c 4'
alias ping4='ping -4 -c 4'
alias ping6='ping -6 -c 4'

# Set the default editor
export EDITOR=nvim
export VISUAL=nvim
alias vim='nvim'
alias vi='nvim'
alias nano='nvim'

PS1='[\u@\h \W]\$ '

extract() {
	for archive in "$@"; do
		if [ -f "$archive" ]; then
			case $archive in
			*.tar.bz2) tar xvjf $archive ;;
			*.tar.gz) tar xvzf $archive ;;
			*.bz2) bunzip2 $archive ;;
			*.rar) rar x $archive ;;
			*.gz) gunzip $archive ;;
			*.tar) tar xvf $archive ;;
			*.tbz2) tar xvjf $archive ;;
			*.tgz) tar xvzf $archive ;;
			*.zip) unzip $archive ;;
			*.Z) uncompress $archive ;;
			*.7z) 7z x $archive ;;
			*) echo "don't know how to extract '$archive'..." ;;
			esac
		else
			echo "'$archive' is not a valid file!"
		fi
	done
}

docker2compose() { # Vibe coded and not fully tested :D
    # 1. Join all arguments into a single string
    local CMD="$*"
    
    # 2. Basic validation
    if [[ -z "$CMD" ]]; then
        echo "Usage: docker2compose docker run -d --name=foo -p 80:80 image/name"
        return 1
    fi

    # 3. Extract the image name (it's always the last argument in a standard run command)
    # We use awk to grab the last field ($NF)
    local IMAGE=$(echo "$CMD" | awk '{print $NF}')

    # 4. Extract flags using regex matching
    # --name
    local NAME=$(echo "$CMD" | grep -oP '(?<=--name[=\s])\S+' | head -n 1)
    # --restart
    local RESTART=$(echo "$CMD" | grep -oP '(?<=--restart[=\s])\S+' | head -n 1)
    
    # 5. Start building the YAML content
    local SERVICE_NAME=${NAME:-app} # Default to "app" if no name is found

    echo "version: '3'"
    echo "services:"
    echo "  $SERVICE_NAME:"
    echo "    image: $IMAGE"
    
    if [[ -n "$NAME" ]]; then
        echo "    container_name: $NAME"
    fi
    
    if [[ -n "$RESTART" ]]; then
        echo "    restart: $RESTART"
    fi

    # 6. Handle multiple occurrences of flags (-p, -v, -e)
    
    # Ports (-p)
    if echo "$CMD" | grep -q "\-p"; then
        echo "    ports:"
        # Look for -p followed by space, capture non-space char
        echo "$CMD" | grep -oP '\-p\s+\K\S+' | while read -r port; do
            echo "      - \"$port\""
        done
    fi

    # Volumes (-v)
    if echo "$CMD" | grep -q "\-v"; then
        echo "    volumes:"
        echo "$CMD" | grep -oP '\-v\s+\K\S+' | while read -r vol; do
            echo "      - $vol"
        done
    fi

    # Environment variables (-e)
    if echo "$CMD" | grep -q "\-e"; then
        echo "    environment:"
        echo "$CMD" | grep -oP '\-e\s+\K\S+' | while read -r env; do
            echo "      - $env"
        done
    fi
}

# Copy file with a progress bar
cpp() {
    set -e
    strace -q -ewrite cp -- "${1}" "${2}" 2>&1 |
    awk '{
        count += $NF
        if (count % 10 == 0) {
            percent = count / total_size * 100
            printf "%3d%% [", percent
            for (i=0;i<=percent;i++)
                printf "="
            printf ">"
            for (i=percent;i<100;i++)
                printf " "
            printf "]\r"
        }
    }
    END { print "" }' total_size="$(stat -c '%s' "${1}")" count=0
}

self() {
if [ $# -eq 0 ] || [[ "$1" == "-h" || "$1" == "--help" ]]; then
cat << EOF
Usage: self <command>

Runs the specified command in the background, redirecting both stdout and stderr,
and disowns the process so the terminal is free immediately.

Example:
self kitty

EOF
    
fi
"$@" 2>&1 & disown
}

alias updatetidal="python3.12 -m pip install --upgrade tidal-dl-ng"

updater() {
    read -p "Are you sure you would like to update? [y/N]" -n 1 -r
    echo    # (optional) move to a new line
    if [[ $REPLY =~ ^[Yy]$ ]]
    then
        sudo pacman -Syyu --overwrite "*" --noconfirm --needed

        if which yay >/dev/null 2>&1; then
            yay -Syyu --overwrite "*" --noconfirm --needed --ignore davinci-resolve-studio --ignore qt5-webengine
        fi

        if which flatpak >/dev/null 2>&1; then
            flatpak update -y --noninteractive
        fi
        
        if which snap >/dev/null 2>&1; then
            sudo snap refresh
        fi
    fi
}

alias update=updater

checkip() {
    OPTIND=1; local G='\033[0;32m' Y='\033[1;33m' R='\033[0;31m' N='\033[0m' c=0 o=""
    while getopts "lpch" x; do case $x in
        l|p) o+="$x";; c) c=1;; h|\?)
            echo -e "Usage: checkip [-l] [-p] [-c] [-h]\n\nDisplay local and/or public IP addresses\n"
            echo -e "Options:\n  -l    Show local IP\n  -p    Show public IP\n  -c    Clean (raw IPs only)\n  -h    Help"
            echo -e "\nNo args shows both IPs"; return;;
    esac; done
    [[ -z "$o" ]] && o="lp"
    local pub=$(curl -s -L ifconfig.me) priv=$(ip a | awk '/inet / && !/127.0.0.1/ {print $2}' | cut -d/ -f1)
    [[ -z "$pub" ]] && pub="Unavailable"
    for ((i=0; i<${#o}; i++)); do case "${o:$i:1}" in
        l) ((c)) && echo "$priv" || echo -e "${Y}Local IP:${N} $priv";;
        p) ((c)) && echo "$pub" || { [[ "$pub" != "Unavailable" ]] && echo -e "${G}Public IP:${N} $pub" || echo -e "${R}Public IP: Unable to retrieve.${N}"; };;
    esac; done
}

# Check if the shell is interactive
if [[ $- == *i* ]]; then
    # Bind Ctrl+f to insert 'zi' followed by a newline
    bind '"\C-f":"zi\n"'
fi

export PATH=$PATH:"$HOME/.local/bin:$HOME/.cargo/bin:/var/lib/flatpak/exports/bin:/.local/share/flatpak/exports/bin"

eval "$(starship init bash)"
eval "$(zoxide init bash)"

# Fancy Oh My Posh
# eval "$(oh-my-posh init bash --config ~/.config/ohmyposh/EDM115-newline.omp.json)"
export PATH=$PATH:~/.spicetify
