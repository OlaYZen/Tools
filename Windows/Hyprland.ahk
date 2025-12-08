; KDE-style Easy Window Dragging with Windows Key
SetWinDelay 2
CoordMode "Mouse"

SetWinDelay(-1)

#LButton::
{
    MouseGetPos &startX, &startY, &id
    if WinGetMinMax(id)
        return

    WinActivate(id)
    WinGetPos &winX, &winY, &winW, &winH, id

    lastX := startX
    lastY := startY

    pos := Buffer(8)  ; reusable buffer for performance

    Loop
    {
        if !GetKeyState("LButton", "P")
            break

        ; Ultra-fast mouse polling via WinAPI
        DllCall("GetCursorPos", "Ptr", pos)
        curX := NumGet(pos, 0, "Int")
        curY := NumGet(pos, 4, "Int")

        if (curX != lastX || curY != lastY)
        {
            dx := curX - startX
            dy := curY - startY

            WinMove winX + dx, winY + dy, winW, winH, id

            lastX := curX
            lastY := curY
        }

        Sleep 0
    }
}



#RButton::
{
    MouseGetPos &KDE_X1, &KDE_Y1, &KDE_id
    if WinGetMinMax(KDE_id)
        return
    WinGetPos &KDE_WinX1, &KDE_WinY1, &KDE_WinW, &KDE_WinH, KDE_id
    KDE_WinLeft := (KDE_X1 < KDE_WinX1 + KDE_WinW / 2) ? 1 : -1
    KDE_WinUp := (KDE_Y1 < KDE_WinY1 + KDE_WinH / 2) ? 1 : -1
    Loop
    {
        if !GetKeyState("RButton", "P")
            break
        MouseGetPos &KDE_X2, &KDE_Y2
        WinGetPos &KDE_WinX1, &KDE_WinY1, &KDE_WinW, &KDE_WinH, KDE_id
        KDE_X2 -= KDE_X1
        KDE_Y2 -= KDE_Y1
        WinMove KDE_WinX1 + (KDE_WinLeft+1)/2*KDE_X2
              , KDE_WinY1 + (KDE_WinUp+1)/2*KDE_Y2
              , KDE_WinW - KDE_WinLeft*KDE_X2
              , KDE_WinH - KDE_WinUp*KDE_Y2
              , KDE_id
        KDE_X1 += KDE_X2
        KDE_Y1 += KDE_Y2
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
