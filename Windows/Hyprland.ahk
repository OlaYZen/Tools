; KDE-style Easy Window Dragging with Windows Key
SetWinDelay(-1)
CoordMode "Mouse"

#LButton::
{
    MouseGetPos &startX, &startY, &id
    if WinGetMinMax(id)
        return

    WinActivate(id)
    WinGetPos &winX, &winY, &winW, &winH, id

    ; Calculate relative position (0 to 1)
    relX := (startX - winX) / winW
    relY := (startY - winY) / winH

    ; Zone threshold: 35% for edges
    threshold := 0.35

    ; Determine zone: -1 = near start, 0 = middle, 1 = near end
    zoneX := (relX < threshold) ? -1 : (relX > 1 - threshold) ? 1 : 0
    zoneY := (relY < threshold) ? -1 : (relY > 1 - threshold) ? 1 : 0

    ; Only constrain on pure edges (not corners, not center)
    pureHorizontalEdge := (zoneX != 0 && zoneY == 0)
    pureVerticalEdge := (zoneX == 0 && zoneY != 0)

    moveX := !pureVerticalEdge
    moveY := !pureHorizontalEdge

    lastX := startX
    lastY := startY

    pos := Buffer(8)

    Loop {
        if !GetKeyState("LButton", "P")
            break

        DllCall("GetCursorPos", "Ptr", pos)
        curX := NumGet(pos, 0, "Int")
        curY := NumGet(pos, 4, "Int")

        if (curX != lastX || curY != lastY) {
            dx := curX - startX
            dy := curY - startY

            newX := moveX ? winX + dx : winX
            newY := moveY ? winY + dy : winY

            WinMove newX, newY, winW, winH, id

            lastX := curX
            lastY := curY
        }

        Sleep 0
    }
}


#RButton::
{
    MouseGetPos &startX, &startY, &winId
    if WinGetMinMax(winId)
        return

    WinGetPos &winX, &winY, &winW, &winH, winId

    ; Calculate relative position (0 to 1)
    relX := (startX - winX) / winW
    relY := (startY - winY) / winH

    ; Zone threshold: 35% for corners, 30% middle (10% tolerance built in)
    threshold := 0.35

    ; Determine zone: -1 = near start, 0 = middle, 1 = near end
    zoneX := (relX < threshold) ? -1 : (relX > 1 - threshold) ? 1 : 0
    zoneY := (relY < threshold) ? -1 : (relY > 1 - threshold) ? 1 : 0

    ; Center zone - do nothing
    if (zoneX == 0 && zoneY == 0)
        return

    ; Determine resize behavior
    ; Corners: resize both | Edges: resize single dimension
    isCorner := (zoneX != 0 && zoneY != 0)

    resizeW := (zoneX != 0) || isCorner
    resizeH := (zoneY != 0) || isCorner

    ; For edges, constrain to single axis
    if (!isCorner) {
        resizeW := (zoneX != 0)
        resizeH := (zoneY != 0)
    }

    ; Anchor opposite edge (left zone = anchor right, etc.)
    anchorRight := (zoneX == -1)
    anchorBottom := (zoneY == -1)

    prevX := startX
    prevY := startY

    Loop {
        if !GetKeyState("RButton", "P")
            break

        MouseGetPos &currX, &currY
        WinGetPos &winX, &winY, &winW, &winH, winId

        dX := currX - prevX
        dY := currY - prevY

        newX := winX
        newY := winY
        newW := winW
        newH := winH

        if (resizeW) {
            if (anchorRight) {
                newX += dX
                newW -= dX
            } else {
                newW += dX
            }
        }

        if (resizeH) {
            if (anchorBottom) {
                newY += dY
                newH -= dY
            } else {
                newH += dY
            }
        }

        WinMove newX, newY, newW, newH, winId

        prevX := currX
        prevY := currY
    }
}
#f::
{
    MouseGetPos ,, &KDE_id
    if WinGetMinMax(KDE_id)
        WinRestore KDE_id
    else
        WinMaximize KDE_id
}

#w::
{
    Run "explorer.exe https:"
}

#Enter::
{
    Run "wt.exe"
}

#q::
{
    MouseGetPos ,, &winID
    WinActivate winID

    class := WinGetClass(winID)
    if (class = "CabinetWClass" or class = "ExploreWClass") {
        ; This is a File Explorer window — safe to close
        WinClose winID
    } else {
        ; For other apps, also close normally
        WinClose winID
    }
}
