--[[
2-bookbench-subtitle.lua - KOReader user patch from Bookbench
https://github.com/kepfle-git/Bookbench

Reads the subtitle and calibre's custom columns straight from each EPUB (its OPF),
so they show without calibre's metadata.calibre on the device:

- Bookshelf: new token %subtitle (top panel / hero card, list lines, cover labels,
  [if:subtitle] conditions), listed in Bookshelf's token picker under "bookbench".
- Bookshelf and Bookends: %calibre{name} also finds custom columns stored in the
  EPUB (for example %calibre{subtitle}); a value in the EPUB wins over metadata.calibre.

Subtitle = calibre column #subtitle, otherwise the EPUB 3 subtitle (dc:title with
title-type "subtitle"). Calibre writes custom columns into the OPF when it sends or
converts a book, and so does Bookbench when you edit them.

Install: copy into koreader/patches/ on the e-reader and restart KOReader.
Everything here is wrapped in pcall: if a plugin changes its insides, the tokens
stay empty, nothing breaks.
]]

local userpatch = require("userpatch")
local logger = require("logger")

local Bookbench = { version = 1 }

-- ---------------------------------------------------------------- reading the OPF
local function readOpf(filepath)
    local ok_a, Archiver = pcall(require, "ffi/archiver")
    if not ok_a then return nil end
    local rd = Archiver.Reader:new()
    if not rd:open(filepath) then return nil end
    local ok, opf = pcall(function()
        for _ in rd:iterate() do end -- luacheck: ignore (fills rd.entries)
        local container = rd.entries["META-INF/container.xml"]
                          and rd:extractToMemory("META-INF/container.xml")
        local path = container and container:match('full%-path%s*=%s*"([^"]+)"')
        if path then
            path = path:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end)
        end
        if not (path and rd.entries[path]) then
            path = nil
            for _i, e in ipairs(rd.entries) do
                if type(e) == "table" and type(e.path) == "string" and e.path:lower():match("%.opf$") then
                    path = e.path
                    break
                end
            end
        end
        return path and rd:extractToMemory(path)
    end)
    pcall(function() rd:close() end)
    return ok and opf or nil
end

local ENTITIES = { lt = "<", gt = ">", quot = '"', apos = "'", amp = "&" }

local function unescape(s)
    s = s:gsub("&#[xX](%x+);", function(h)
        local n = tonumber(h, 16)
        return n and n < 128 and string.char(n) or ("&#x" .. h .. ";")
    end)
    s = s:gsub("&#(%d+);", function(d)
        local n = tonumber(d)
        return n and n < 128 and string.char(n) or ("&#" .. d .. ";")
    end)
    return (s:gsub("&(%a+);", function(e) return ENTITIES[e] or ("&" .. e .. ";") end))
end

local function attr(tag, name)
    return tag:match("[%s]" .. name .. '%s*=%s*"([^"]*)"') or tag:match("[%s]" .. name .. "%s*=%s*'([^']*)'")
end

-- every <meta ...> with its text (nil for <meta .../>)
local function metas(opf)
    local list, pos = {}, 1
    while true do
        local s, e, tag = opf:find("(<meta[%s][^>]*>)", pos)
        if not s then break end
        local body
        if not tag:match("/%s*>$") then
            local c = opf:find("</meta%s*>", e + 1)
            local nxt = opf:find("<meta[%s/>]", e + 1)
            if c and (not nxt or c < nxt) then body = opf:sub(e + 1, c - 1) end
        end
        list[#list + 1] = { tag = tag, body = body }
        pos = e + 1
    end
    return list
end

-- small JSON reader (calibre's column JSON is plain); used when rapidjson is missing
local function jsonDecode(s)
    local pos = 1
    local value
    local function ws() pos = s:find("[^ \t\r\n]", pos) or #s + 1 end
    local function err() error("bad json at " .. pos) end
    local function str()
        local out, i = {}, pos + 1
        while true do
            local c = s:sub(i, i)
            if c == "" then err() end
            if c == '"' then pos = i + 1; return table.concat(out) end
            if c == "\\" then
                local e = s:sub(i + 1, i + 1)
                local map = { b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }
                if e == "u" then
                    local n = tonumber(s:sub(i + 2, i + 5), 16) or 63
                    if n >= 0xD800 and n <= 0xDBFF and s:sub(i + 6, i + 7) == "\\u" then
                        local lo = tonumber(s:sub(i + 8, i + 11), 16) or 0xDC00
                        n = 0x10000 + (n - 0xD800) * 0x400 + (lo - 0xDC00)
                        i = i + 6
                    end
                    if n < 0x80 then out[#out + 1] = string.char(n)
                    elseif n < 0x800 then out[#out + 1] = string.char(0xC0 + math.floor(n / 64), 0x80 + n % 64)
                    elseif n < 0x10000 then
                        out[#out + 1] = string.char(0xE0 + math.floor(n / 4096), 0x80 + math.floor(n / 64) % 64, 0x80 + n % 64)
                    else
                        out[#out + 1] = string.char(0xF0 + math.floor(n / 262144), 0x80 + math.floor(n / 4096) % 64,
                                                    0x80 + math.floor(n / 64) % 64, 0x80 + n % 64)
                    end
                    i = i + 6
                else
                    out[#out + 1] = map[e] or e
                    i = i + 2
                end
            else
                local j = s:find('["\\]', i) or #s + 1
                out[#out + 1] = s:sub(i, j - 1)
                i = j
            end
        end
    end
    value = function()
        ws()
        local c = s:sub(pos, pos)
        if c == "{" then
            local t = {}
            pos = pos + 1; ws()
            if s:sub(pos, pos) == "}" then pos = pos + 1; return t end
            while true do
                ws()
                if s:sub(pos, pos) ~= '"' then err() end
                local k = str()
                ws()
                if s:sub(pos, pos) ~= ":" then err() end
                pos = pos + 1
                t[k] = value()
                ws()
                local d = s:sub(pos, pos)
                pos = pos + 1
                if d == "}" then return t end
                if d ~= "," then err() end
            end
        elseif c == "[" then
            local t = {}
            pos = pos + 1; ws()
            if s:sub(pos, pos) == "]" then pos = pos + 1; return t end
            while true do
                t[#t + 1] = value()
                ws()
                local d = s:sub(pos, pos)
                pos = pos + 1
                if d == "]" then return t end
                if d ~= "," then err() end
            end
        elseif c == '"' then
            return str()
        elseif s:sub(pos, pos + 3) == "true" then pos = pos + 4; return true
        elseif s:sub(pos, pos + 4) == "false" then pos = pos + 5; return false
        elseif s:sub(pos, pos + 3) == "null" then pos = pos + 4; return nil
        else
            local num = s:match("^-?%d+%.?%d*[eE]?[-+]?%d*", pos)
            if not num or num == "" then err() end
            pos = pos + #num
            return tonumber(num)
        end
    end
    return value()
end
Bookbench.jsonDecode = jsonDecode

local function decodeJson(s)
    local ok, rj = pcall(require, "rapidjson")
    if ok and type(rj) == "table" and rj.decode then
        local ok2, v = pcall(rj.decode, s)
        if ok2 and type(v) == "table" then return v end
    end
    local ok3, v = pcall(jsonDecode, s)
    return ok3 and v or nil
end

local function plain(v)
    local t = type(v)
    if t == "string" then return v end
    if t == "number" then
        if v == math.floor(v) then return string.format("%d", v) end
        return tostring(v)
    end
    if t == "boolean" then return v and "Yes" or "No" end
    return nil
end

-- calibre's field definition (with "#value#") as display text, like Bookbench shows it
local function display(fm)
    if type(fm) ~= "table" then return nil end
    local v = fm["#value#"]
    local dt = fm.datatype
    if type(v) == "table" then
        if v.__value__ ~= nil then
            local d = plain(v.__value__)
            return d and d:sub(1, 4)
        end
        local im = type(fm.is_multiple2) == "table" and fm.is_multiple2
                   or (type(fm.is_multiple) == "table" and fm.is_multiple) or nil
        local sep = im and im.ui_to_list
        if not sep then
            sep = (type(fm.display) == "table" and fm.display.is_names) and "&" or ","
        end
        sep = (sep:match("^%s*(.-)%s*$") == "&") and " & " or ", "
        local parts = {}
        for _i, x in ipairs(v) do
            local p = plain(x)
            if p and p:match("%S") then parts[#parts + 1] = p end
        end
        return #parts > 0 and table.concat(parts, sep) or nil
    end
    local p = plain(v)
    if not p or p == "" then return nil end
    if dt == "datetime" then return p:sub(1, 4) end        -- the year, as Bookshelf shows dates
    if dt == "comments" then
        p = p:gsub("<[^>]*>", " "):gsub("%s+", " "):match("^%s*(.-)%s*$")
        p = unescape(p)
    end
    return p ~= "" and p or nil
end

local function parseOpf(opf)
    local fields = {}
    local function put(col, fm)
        local key = tostring(col):gsub("^#", ""):lower()
        local text = display(fm)
        if key ~= "" and text then fields[key] = text end
    end
    local list = metas(opf)
    local title_types = {}
    for _i, m in ipairs(list) do
        local name = attr(m.tag, "name")
        local prop = attr(m.tag, "property")
        if name and name:sub(1, 22) == "calibre:user_metadata:" then
            local content = attr(m.tag, "content")
            local fm = content and decodeJson(unescape(content))
            if fm then put(name:sub(23), fm) end
        elseif prop and prop:lower() == "calibre:user_metadata" and m.body then
            local all = decodeJson(unescape(m.body))
            if type(all) == "table" then
                for col, fm in pairs(all) do put(col, fm) end
            end
        elseif prop == "title-type" and m.body and m.body:match("^%s*subtitle%s*$") then
            local ref = attr(m.tag, "refines")
            if ref then title_types[#title_types + 1] = ref:gsub("^#", "") end
        end
    end
    if not fields.subtitle then
        for _i, id in ipairs(title_types) do
            local esc = id:gsub("%W", "%%%0")
            local t = opf:match('<dc:title[^>]-[%s]id%s*=%s*["\']' .. esc .. '["\'][^>]*>(.-)</dc:title>')
            if t and t:match("%S") then
                fields.subtitle = unescape(t:match("^%s*(.-)%s*$"))
                break
            end
        end
    end
    return fields
end
Bookbench.parseOpf = parseOpf

-- ---------------------------------------------------------------- cache per book
local cache = {}

function Bookbench.fieldsFor(filepath)
    if type(filepath) ~= "string" or not filepath:lower():match("%.epub$") then return nil end
    local lfs = require("libs/libkoreader-lfs")
    local mtime = lfs.attributes(filepath, "modification")
    if not mtime then return nil end
    local c = cache[filepath]
    if c and c.mtime == mtime then return c.fields end
    local ok, fields = pcall(function()
        local opf = readOpf(filepath)
        return opf and parseOpf(opf) or {}
    end)
    if not ok then
        logger.warn("bookbench-subtitle: cannot read", filepath, fields)
        fields = {}
    end
    cache[filepath] = { mtime = mtime, fields = fields }
    return fields
end

-- calibre map from the plugin + values from the EPUB (EPUB wins); a new table
local function merged(map, filepath)
    local own = Bookbench.fieldsFor(filepath)
    if not own or next(own) == nil then return map end
    local out = {}
    if type(map) == "table" then
        for k, v in pairs(map) do out[k] = v end
    end
    for k, v in pairs(own) do out[k] = v end
    return out
end

package.loaded["bookbench_subtitle"] = Bookbench

-- A plugin's module as its own code loaded it (already in package.loaded), else require it.
local function module(name)
    local m = package.loaded[name]
    if type(m) == "table" then return m end
    local ok, r = pcall(require, name)
    return ok and type(r) == "table" and r or nil
end

-- KOReader calls these patch functions for every new file manager / reader instance,
-- so each wrap is done once only.
local function wrapOnce(tbl, name, make)
    local orig = tbl[name]
    if type(orig) ~= "function" or tbl["__bookbench_" .. name] then return end
    tbl[name] = make(orig)
    tbl["__bookbench_" .. name] = true
end

-- ---------------------------------------------------------------- Bookshelf
userpatch.registerPatchPluginFunc("bookshelf", function(Bookshelf)
    local ok, err = pcall(function()
        if Bookshelf.registerTokens then
            local done, why = Bookshelf:registerTokens("bookbench", {
                subtitle = {
                    expand = function(book)
                        local f = book and Bookbench.fieldsFor(book.filepath)
                        return f and f.subtitle or ""
                    end,
                    description = "Subtitle from the EPUB (Bookbench patch)",
                },
            })
            if not done then logger.warn("bookbench-subtitle: %subtitle not registered:", why) end
        end
        local Repo = module("lib/bookshelf_book_repository")
        if Repo then
            for _i, name in ipairs({ "buildBookMeta", "buildBook" }) do
                wrapOnce(Repo, name, function(orig)
                    return function(...)
                        local book, a, b, c = orig(...)
                        if type(book) == "table" and type(book.filepath) == "string" then
                            pcall(function() book.calibre = merged(book.calibre, book.filepath) end)
                        end
                        return book, a, b, c
                    end
                end)
            end
        end
    end)
    if not ok then logger.warn("bookbench-subtitle: Bookshelf hook failed:", err) end
end)

-- ---------------------------------------------------------------- Bookends
userpatch.registerPatchPluginFunc("bookends", function()
    local ok, err = pcall(function()
        local CalibreMeta = module("calibre_metadata")
        if not CalibreMeta then return end
        wrapOnce(CalibreMeta, "fieldsFor", function(orig)
            return function(filepath, enabled)
                local map = orig(filepath, enabled)
                local okm, out = pcall(merged, map, filepath)
                return okm and out or map
            end
        end)
    end)
    if not ok then logger.warn("bookbench-subtitle: Bookends hook failed:", err) end
end)
