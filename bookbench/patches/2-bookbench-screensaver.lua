--[[
2-bookbench-screensaver.lua - KOReader user patch from Bookbench
https://github.com/kepfle-git/Bookbench

Sleep screen with a picture (book cover or random image) and a message:
KOReader lays the message over the picture. With this patch the picture
shrinks into the free space next to the message instead, so nothing of the
cover is hidden. Everything else (message, banner/box, position, opacity,
stretching, cropping, background) stays KOReader's own.

Settings (settings.reader.lua; Bookbench's workbench page "Sleep screen" sets them):
  bookbench_screensaver_avoid_message  true (default) = keep the picture clear of the message
  bookbench_screensaver_center         false (default) = use the larger free space (bigger picture);
                                       true = keep the picture in the middle of the screen
                                       (smaller, same gap above and below)

It does not replace Screensaver.show: it only adjusts the one OverlapGroup that
KOReader builds from the picture and the message while the sleep screen is shown.
If KOReader changes that, the patch does nothing and the sleep screen looks as
without it. If the free space is too small (message in the middle with "center",
or a very tall message), the picture stays as KOReader draws it.

Install: copy into koreader/patches/ on the e-reader and restart KOReader.
]]

local ImageWidget = require("ui/widget/imagewidget")
local OverlapGroup = require("ui/widget/overlapgroup")
local Screensaver = require("ui/screensaver")
local Screen = require("device").screen
local logger = require("logger")

local MIN_ANTEIL = 0.3          -- picture area at least 30 % of the screen height, otherwise leave it

local aktiv = false
local orig_new = OverlapGroup.new
local orig_show = Screensaver.show

local function ist_bild(w)
    return type(w) == "table" and w._render == ImageWidget._render and w.width and w.height
end

local function ist_meldung(w)
    return type(w) == "table" and type(w.vertical_position) == "number" and type(w.widget) == "table"
end

-- Bereich (y, h) für das Bild oder nil
local function bereich(H, y, h, mitte)
    local abstand = Screen:scaleBySize(8)
    local oben = y - abstand                      -- frei über der Meldung
    local unten_y = y + h + abstand
    local unten = H - unten_y                     -- frei unter der Meldung
    if mitte then
        -- gleicher Rand oben und unten, so groß wie es neben der Meldung geht
        local rand
        if y + h / 2 >= H / 2 then                -- Meldung in der unteren Hälfte
            rand = H - oben
        else
            rand = unten_y
        end
        local hb = H - 2 * rand
        if hb >= H * MIN_ANTEIL then
            return rand, hb
        end
        -- passt nicht (Meldung zu nah an der Mitte): größeren freien Teil nehmen
    end
    if oben >= unten and oben >= H * MIN_ANTEIL then
        return 0, oben
    elseif unten >= H * MIN_ANTEIL then
        return unten_y, unten
    end
    return nil
end

local function anpassen(o)
    if #o ~= 2 or not o.dimen then return end
    local bild, meldung = o[1], o[2]
    if not (ist_bild(bild) and ist_meldung(meldung)) then return end
    local H = o.dimen.h or Screen:getHeight()
    local h = meldung.widget:getSize().h
    local y = math.floor((H - h) * meldung.vertical_position)
    y = math.max(0, math.min(y, H - h))
    local by, bh = bereich(H, y, h, G_reader_settings:isTrue("bookbench_screensaver_center"))
    if not by then return end
    -- ImageWidget zentriert das Bild selbst in width x height; noch nicht gezeichnet, also nur die Box ändern
    bild.height = bh
    bild.overlap_offset = { 0, by }
end

OverlapGroup.new = function(cls, o)
    if aktiv and cls == OverlapGroup and type(o) == "table" then
        local ok, err = pcall(anpassen, o)
        if not ok then logger.warn("bookbench screensaver patch:", err) end
    end
    return orig_new(cls, o)
end

Screensaver.show = function(self, ...)
    if G_reader_settings:isFalse("bookbench_screensaver_avoid_message") then
        return orig_show(self, ...)
    end
    aktiv = true
    local ok, err = pcall(orig_show, self, ...)
    aktiv = false
    if not ok then error(err, 0) end
end
