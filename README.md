# Tools
A collection of custom tools I regularly use across both Windows and Linux.

## Windows
  
`Windows/Hyprland.ahk`
  - [AutoHotkey](https://www.autohotkey.com/)
  - [Windows Terminal](https://github.com/microsoft/terminal) 
##### Description
```
Windows + Holding left click    Moves the window around just like the title bar
Windows + Holding right click   Resizes the window based on mouse movement and based on which corner is closest to the mouse
Windows + Q                     Closes the program the mouse is highlighting. The program doesn't have to be focused
Windows + W                     Opens the default browser
Windows + F                     Toggles restore/maximize button
Windows + Enter                 Opens Windows Terminal
```
`Windows/Microsoft.PowerShell_profile.ps1`
  - [fastfetch](https://github.com/fastfetch-cli/fastfetch)
  - [fzf](https://github.com/junegunn/fzf)
  - [PowerShell 7](https://github.com/PowerShell/PowerShell)
##### Description
```
wingetf                         Fuzzy find searches every winget installation and allows you to install the searched up application by pressing enter
ebrc/rbrc                       Edit .bashrc / Reload .bashrc (Is from my Linux .bashrc) which opens/reloads the powershell profile in notepad
claer                           Custom function for clear (incase you do a spelling error(Happens a lot))
grep                            Custom function for findstr
cff                             Custom function for clear && fastfetch
```

## Linux
`Linux/.bashrc`
##### Description
```
My custom made bashrc with multiple functions and shortcuts. Some functions only work on Arch Linux.  Dont know the requirements
```
`Linux/Scripts/*`
##### Description
```
The folder name should be self explanatory. Dont know the requirements. 
```

## Linux programs
Each one has its own README with requirements and usage.

| Folder | What it is |
|---|---|
| `Linux/Programs/diskmap` | Disk usage analyzer in the spirit of WinDirStat, as a terminal program and a window (Rust) |
| `Linux/Programs/controller_tester` | Local web app that tests Xbox, PlayStation and Nintendo controllers: buttons, sticks, triggers, gyro, rumble |
| `Linux/Programs/jc-py-color-picker` | Linux port of the Joy-Con color picker |
| `Linux/Programs/fh6-dash` | Live dashboard for Forza Horizon 6 "Data Out" telemetry (FastAPI) |
| `Linux/Programs/gt7` | Live telemetry dashboard for Gran Turismo 7, and the notes on its protocol |
| `Linux/Programs/rust-liquid-glass-replica` | A floating pane of iOS 26-style liquid glass for Hyprland (Rust) |
| `Linux/Programs/pydownloader4downloads.khinsider` | Downloads whole albums from downloads.khinsider.com (Python, runs on Windows too) |

## Browser
`Browser/forgejo-semantic-commits`
##### Description
```
Firefox / Zen extension (Refined Forgejo) that makes Forgejo and Gitea nicer to use, in the spirit of Refined GitHub
```
