--[[
2-bookbench-stories.lua - KOReader user patch from Bookbench
https://github.com/kepfle-git/Bookbench

Stories inside anthologies as entries of a collection. A collection in KOReader can only
hold whole files; with this patch it can also hold "the story X in the anthology Y":

- The collection list shows the story at its place (manual sort order), next to the books.
- Tapping it opens the anthology right at the start of the story (or where you stopped
  reading the story). The story has a reading position of its own: the anthology keeps its
  normal position, as if the story had been read in a separate book.
- At the end of the story a dialog offers the next entry of the collection, going back to
  the collection, or simply reading on in the anthology.
- Long-press on a story: open it, open the anthology normally, mark it read or unread.

Bookbench writes the stories into settings/bookbench_stories.lua (per collection: file,
order, title, table of contents entry). Reading state of the stories is kept in
settings/bookbench_stories_state.lua, which Bookbench reads back.

Install: copy into koreader/patches/ on the e-reader and restart KOReader.
Only for reflowable books (EPUB). Everything is wrapped in pcall: if KOReader changes its
insides, the stories simply do not show up, nothing else breaks.
]]

local DataStorage = require("datastorage")
local Event = require("ui/event")
local LuaSettings = require("luasettings")
local UIManager = require("ui/uimanager")
local ffiUtil = require("ffi/util")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local gettext = require("gettext")
local T = ffiUtil.template

-- KOReader's catalogue does not know these texts; German comes with the patch, other languages stay English
local DE = {
    ["%1\nin %2"] = "%1\nin %2",
    ["Back to the last page"] = "Zurück zur letzten Seite",
    ["Back to “%1”"] = "Zurück zu „%1“",
    ["End of “%1”"] = "Ende von „%1“",
    ["Mark story as read"] = "Geschichte als gelesen markieren",
    ["Mark story as unread"] = "Geschichte als ungelesen markieren",
    ["Next: %1"] = "Weiter: %1",
    ["Open story"] = "Geschichte öffnen",
    ["Open the book normally"] = "Buch normal öffnen",
    ["Read on in this book"] = "In diesem Buch weiterlesen",
    ["Stories need a reflowable book (EPUB)."] = "Geschichten brauchen ein Buch mit fließendem Text (EPUB).",
    ["Story: %1"] = "Geschichte: %1",
    ["in %1"] = "in %1",
    ["story"] = "Geschichte",
    ["“%1” was not found in the table of contents of this book."] =
        "„%1“ steht nicht im Inhaltsverzeichnis dieses Buchs.",
}
local function _(text)
    local lang = G_reader_settings and G_reader_settings:readSetting("language") or ""
    if lang:sub(1, 2) == "de" and DE[text] then return DE[text] end
    return gettext(text)
end

local Stories = { version = 1 }
Stories.DEF = DataStorage:getSettingsDir() .. "/bookbench_stories.lua"
Stories.STATE = DataStorage:getSettingsDir() .. "/bookbench_stories_state.lua"

local function realpath(p)
    return p and (ffiUtil.realpath(p) or p)
end

-- ---------------------------------------------------------------- data
--- {collection name: {story, ...}}; every story gets .collection; re-read when the file changes
function Stories.definitions()
    local mt = lfs.attributes(Stories.DEF, "modification")
    if mt ~= Stories._def_mt then
        Stories._def_mt = mt
        Stories._defs = {}
        if mt then
            local ok, data = pcall(function() return LuaSettings:open(Stories.DEF).data end)
            if ok and type(data) == "table" then
                for name, list in pairs(data) do
                    if type(list) == "table" then
                        local stories = {}
                        for _i, s in ipairs(list) do
                            if type(s) == "table" and s.file and s.toc then
                                s.collection = name
                                s.file = realpath(s.file)
                                table.insert(stories, s)
                            end
                        end
                        Stories._defs[name] = stories
                    end
                end
            else
                logger.warn("bookbench stories: cannot read", Stories.DEF, data)
            end
        end
    end
    return Stories._defs
end

--- Order of a story: as Bookbench wrote it, unless it was moved in KOReader since (arrange dialog)
function Stories.order(s)
    local o = Stories.state():readSetting("order")
    if type(o) == "table" and o.stamp == Stories._def_mt and o[Stories.key(s)] then
        return o[Stories.key(s)]
    end
    return s.order or math.huge
end

function Stories.key(s)
    return string.format("%s|%s|%d", s.file, s.toc, tonumber(s.toc_nr) or 1)
end

function Stories.state()
    if not Stories._state then
        Stories._state = LuaSettings:open(Stories.STATE)
    end
    return Stories._state
end

function Stories.storyState(s)
    local all = Stories.state():readSetting("stories") or {}
    return all[Stories.key(s)] or {}
end

function Stories.saveStoryState(s, values)
    local st = Stories.state()
    local all = st:readSetting("stories") or {}
    local k = Stories.key(s)
    local e = all[k] or {}
    for name, v in pairs(values) do
        if v == false then e[name] = nil else e[name] = v end
    end
    e.title, e.collection, e.last = s.title, s.collection, os.time()
    all[k] = e
    st:saveSetting("stories", all)
    st:flush()
end

function Stories.statusText(s)
    local e = Stories.storyState(s)
    if e.status == "complete" then return "\u{2713}" end
    if e.percent then return string.format("%d %%", math.floor(e.percent * 100 + 0.5)) end
    return ""
end

--- Ordered entries of a collection: real books and stories, by their order
function Stories.ordered(name)
    local ReadCollection = require("readcollection")
    local list = {}
    for _i, item in ipairs(ReadCollection:getOrderedCollection(name) or {}) do
        table.insert(list, { file = item.file, order = item.order })
    end
    for _i, s in ipairs(Stories.definitions()[name] or {}) do
        table.insert(list, { file = s.file, order = Stories.order(s), story = s })
    end
    table.sort(list, function(a, b) return (a.order or math.huge) < (b.order or math.huge) end)
    return list
end

function Stories.nextEntry(s)
    local list = Stories.ordered(s.collection)
    for i, e in ipairs(list) do
        if e.story and Stories.key(e.story) == Stories.key(s) then
            return list[i + 1]
        end
    end
end

-- ---------------------------------------------------------------- opening
--- Open a story from the file manager or from the reader
function Stories.open(ui, s)
    local ReaderUI = require("apps/reader/readerui")
    local reader = ReaderUI.instance
    if reader and reader.document and realpath(reader.document.file) == s.file and reader.bookbench_story then
        reader.bookbench_story:start(s)
        return
    end
    Stories.pending = s
    if reader and reader.document then
        reader:switchDocument(s.file)
    elseif ui and ui.openFile then
        ui:openFile(s.file)
    else
        ReaderUI:showReader(s.file)
    end
end

function Stories.openEntry(ui, e)
    if e.story then
        Stories.open(ui, e.story)
        return
    end
    local ReaderUI = require("apps/reader/readerui")
    local reader = ReaderUI.instance
    if reader and reader.document then
        if realpath(reader.document.file) ~= realpath(e.file) then
            reader:switchDocument(e.file)
        end
    else
        ReaderUI:showReader(e.file)
    end
end

-- ---------------------------------------------------------------- reader module
local EventListener = require("ui/widget/eventlistener")
local StoryModule = EventListener:extend{}

--- Index of a table of contents entry by title and occurrence (1 = first entry with that title)
function StoryModule:tocIndex(title, nr)
    local toc = self.ui.toc
    toc:fillToc()
    local want = tonumber(nr) or 1
    local n = 0
    local norm = function(t) return (t or ""):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "") end
    title = norm(title)
    for i, e in ipairs(toc.toc or {}) do
        if norm(e.title) == title then
            n = n + 1
            if n == want then return i end
        end
    end
end

function StoryModule:start(s)
    if not self.ui.rolling or not self.ui.toc then
        UIManager:show(require("ui/widget/infomessage"):new{ text = _("Stories need a reflowable book (EPUB).") })
        return
    end
    if self.story then                                    -- another story of the same anthology
        self:saveStory()
        self.story = nil
    end
    local i = self:tocIndex(s.toc, s.toc_nr)
    if not i then
        UIManager:show(require("ui/widget/infomessage"):new{
            text = T(_("“%1” was not found in the table of contents of this book."), s.toc) })
        return
    end
    local toc = self.ui.toc.toc
    local j
    if s.toc_end then
        j = self:tocIndex(s.toc_end, s.toc_end_nr)
        j = j and j + 1 or nil                           -- story ends where the entry after toc_end starts
        while j and toc[j] and toc[j].depth > toc[i].depth do j = j + 1 end
    else
        j = i + 1
        while toc[j] and toc[j].depth > toc[i].depth do j = j + 1 end
    end
    self.story = s
    self.start_xp = toc[i].xpointer
    self.end_xp = toc[j] and toc[j].xpointer or nil
    self.asked = false
    -- the anthology's own position, restored when the story is left (kept across restarts)
    local st = Stories.state()
    local anth = st:readSetting("anthology") or {}
    if anth[s.file] == nil then
        anth[s.file] = {
            xpointer = self.ui.doc_settings:readSetting("last_xpointer") or "",
            percent = self.ui.doc_settings:readSetting("percent_finished") or false,
        }
        st:saveSetting("anthology", anth)
        st:flush()
    end
    local e = Stories.storyState(s)
    local xp = self.start_xp
    if e.xpointer and e.status ~= "complete" then
        xp = e.xpointer
    end
    self.ui:handleEvent(Event:new("GotoXPointer", xp, xp))
    Stories.saveStoryState(s, { status = e.status == "complete" and "complete" or "reading" })
    local ok, Notification = pcall(require, "ui/widget/notification")
    if ok then
        Notification:notify(T(_("Story: %1"), s.title or s.toc))
    end
end

function StoryModule:endPage()
    return self.end_xp and self.ui.document:getPageFromXPointer(self.end_xp) or nil
end

function StoryModule:progress()
    local doc = self.ui.document
    local a = doc:getPageFromXPointer(self.start_xp)
    local b = self:endPage() or (doc:getPageCount() + 1)
    local p = doc:getCurrentPage()
    if b <= a then return 0 end
    return math.max(0, math.min(1, (p - a + 1) / (b - a)))
end

function StoryModule:saveStory()
    if not self.story then return end
    Stories.saveStoryState(self.story, { xpointer = self.ui.rolling.xpointer, percent = self:progress() })
end

function StoryModule:check()
    if not self.story or self.asked then return end
    local endp = self:endPage()
    if endp and self.ui.document:getCurrentPage() >= endp then
        self.asked = true
        UIManager:nextTick(function() self:finished() end)
    end
end

function StoryModule:onPageUpdate()
    pcall(self.check, self)
end

function StoryModule:onPosUpdate()
    pcall(self.check, self)
end

function StoryModule:finished()
    local s = self.story
    if not s then return end
    Stories.saveStoryState(s, { status = "complete", percent = 1, xpointer = false })
    local nxt = Stories.nextEntry(s)
    local ButtonDialog = require("ui/widget/buttondialog")
    local dialog
    local buttons = {}
    if nxt then
        local name = nxt.story and (nxt.story.title or nxt.story.toc) or nxt.file:gsub(".*/", "")
        table.insert(buttons, {{ text = T(_("Next: %1"), name), callback = function()
            UIManager:close(dialog)
            self:leave(false)
            Stories.openEntry(self.ui, nxt)
        end }})
    end
    table.insert(buttons, {{ text = T(_("Back to “%1”"), s.collection), callback = function()
        UIManager:close(dialog)
        self:leave(false)
        if self.ui.collections then
            self.ui.collections:onShowColl(s.collection)       -- the collection list, over the book
        end
    end }})
    table.insert(buttons, {{ text = _("Read on in this book"), callback = function()
        UIManager:close(dialog)
        self:leave(true)
    end }})
    table.insert(buttons, {{ text = _("Back to the last page"), callback = function()
        UIManager:close(dialog)
        self.ui:handleEvent(Event:new("GotoViewRel", -1))
        UIManager:scheduleIn(1, function() self.asked = false end)
    end }})
    dialog = ButtonDialog:new{ title = T(_("End of “%1”"), s.title or s.toc), buttons = buttons }
    self.dialog = dialog
    UIManager:show(dialog)
end

--- Leave the story. keep = true: stay where you are, this is now the anthology's position.
function StoryModule:leave(keep)
    if not self.story then return end
    local file = self.story.file
    if self.story then self:saveStory() end
    self.story = nil
    local st = Stories.state()
    local anth = st:readSetting("anthology") or {}
    if keep then
        anth[file] = nil
    else
        self:restore(anth[file])
        anth[file] = nil
    end
    st:saveSetting("anthology", anth)
    st:flush()
    self.left_with = keep and "keep" or "restore"
end

function StoryModule:restore(a)
    if not a then return end
    if a.xpointer and a.xpointer ~= "" then
        self.ui.doc_settings:saveSetting("last_xpointer", a.xpointer)
        self.ui.rolling.xpointer = a.xpointer
    else
        self.ui.doc_settings:delSetting("last_xpointer")
    end
    if a.percent then
        self.ui.doc_settings:saveSetting("percent_finished", a.percent)
    end
end

function StoryModule:onReaderReady()
    local ok, err = pcall(function()
        local p = Stories.pending
        Stories.pending = nil
        if p and p.file == realpath(self.ui.document.file) then
            self:start(p)
        end
    end)
    if not ok then logger.warn("bookbench stories:", err) end
end

--- Runs after ReaderRolling/ReaderFooter (registered later): the anthology keeps its own position
function StoryModule:onSaveSettings()
    if not self.story then return end
    pcall(function()
        self:saveStory()
        local anth = Stories.state():readSetting("anthology") or {}
        local a = anth[self.story.file]
        if a then
            if a.xpointer and a.xpointer ~= "" then
                self.ui.doc_settings:saveSetting("last_xpointer", a.xpointer)
            else
                self.ui.doc_settings:delSetting("last_xpointer")
            end
            if a.percent then
                self.ui.doc_settings:saveSetting("percent_finished", a.percent)
            end
        end
    end)
end

--- Runs after ReaderRolling's (which writes percent_finished there): put the anthology's position back for
--- good. A SaveSettings after this (closing via UIManager) saves rolling.xpointer, which is restored too.
function StoryModule:onCloseDocument()
    if not self.story then return end
    pcall(function()
        local file = self.story.file
        self:saveStory()
        self.story = nil
        local st = Stories.state()
        local anth = st:readSetting("anthology") or {}
        self:restore(anth[file])
        anth[file] = nil
        st:saveSetting("anthology", anth)
        st:flush()
        self.ui.doc_settings:flush()
    end)
end

-- ---------------------------------------------------------------- hooks
local function install()
    local ReaderUI = require("apps/reader/readerui")
    local orig_register = ReaderUI.registerModule
    ReaderUI.registerModule = function(self, name, mod, always)
        orig_register(self, name, mod, always)
        if name == "back" and not self.bookbench_story then          -- last module: after rolling and footer
            local m = StoryModule:new{ ui = self }
            self.bookbench_story = m
            orig_register(self, "bookbench_story", m)
        end
    end

    local FMC = require("apps/filemanager/filemanagercollection")
    local util = require("util")
    local orig_update = FMC.updateItemTable
    FMC.updateItemTable = function(self, item_table, focused_file)
        if item_table == nil and self.booklist_menu and not self.match_table then
            local ok, err = pcall(function()
                local name = self.booklist_menu.path
                local defs = Stories.definitions()[name]
                if not defs or #defs == 0 then return end
                local ReadCollection = require("readcollection")
                local list = {}
                for _f, item in pairs(ReadCollection.coll[name] or {}) do
                    local it = { file = item.file, text = item.text, order = item.order, attr = item.attr,
                                 mandatory = self.mandatory_func and self.mandatory_func(item)
                                             or util.getFriendlySize(item.attr.size or 0) }
                    if self.item_func then self.item_func(it, self.ui) end
                    table.insert(list, it)
                end
                for _i, s in ipairs(defs) do
                    local attr = lfs.attributes(s.file)
                    if attr and attr.mode == "file" then
                        local it = { file = s.file, text = s.title or s.toc, order = Stories.order(s),
                                     attr = attr, bookbench_story = s }
                        if self.item_func then self.item_func(it, self.ui) end
                        it.text = s.title or s.toc
                        local status = Stories.statusText(s)
                        it.mandatory = (s.book and T(_("in %1"), s.book) or _("story")) ..
                                       (status ~= "" and ("  " .. status) or "")
                        table.insert(list, it)
                    end
                end
                if #list > 1 then table.sort(list, self.sorting_func) end
                item_table = list
            end)
            if not ok then
                logger.warn("bookbench stories:", err)
                item_table = nil
            end
        end
        return orig_update(self, item_table, focused_file)
    end

    local orig_select = FMC.onMenuSelect
    FMC.onMenuSelect = function(self, item)
        if item and item.bookbench_story and not (self._manager and self._manager.selected_files) then
            local ui = self.ui
            self.close_callback()
            Stories.open(ui, item.bookbench_story)
            return true
        end
        return orig_select(self, item)
    end

    local orig_hold = FMC.onMenuHold
    FMC.onMenuHold = function(self, item)
        if item and item.bookbench_story and not (self._manager and self._manager.selected_files) then
            local s, ui, menu = item.bookbench_story, self.ui, self
            local ButtonDialog = require("ui/widget/buttondialog")
            local done = Stories.storyState(s).status == "complete"
            local dialog
            dialog = ButtonDialog:new{
                title = s.book and T(_("%1\nin %2"), s.title or s.toc, s.book) or (s.title or s.toc),
                buttons = {
                    {{ text = _("Open story"), callback = function()
                        UIManager:close(dialog)
                        menu.close_callback()
                        Stories.open(ui, s)
                    end }},
                    {{ text = _("Open the book normally"), callback = function()
                        UIManager:close(dialog)
                        menu.close_callback()
                        Stories.openEntry(ui, { file = s.file })
                    end }},
                    {{ text = done and _("Mark story as unread") or _("Mark story as read"), callback = function()
                        UIManager:close(dialog)
                        Stories.saveStoryState(s, done and { status = false, percent = false, xpointer = false }
                                                      or { status = "complete", percent = 1, xpointer = false })
                        menu._manager:updateItemTable(nil, s.file)
                    end }},
                },
            }
            UIManager:show(dialog)
            return true
        end
        return orig_hold(self, item)
    end

    -- Arranging in KOReader: everything gets its position in the full list; for stories it is kept in the
    -- state file (Bookbench reads it back), until Bookbench writes the stories anew.
    local ReadCollection = require("readcollection")
    ReadCollection.updateCollectionOrder = function(self, name, ordered)
        local coll = self.coll[name]
        local st = Stories.state()
        local o = st:readSetting("order")
        if type(o) ~= "table" or o.stamp ~= Stories._def_mt then o = { stamp = Stories._def_mt } end
        local moved = false
        for i, item in ipairs(ordered) do
            if item.bookbench_story then
                o[Stories.key(item.bookbench_story)] = i
                moved = true
            elseif coll[item.file] then
                coll[item.file].order = i
            end
        end
        if moved then
            st:saveSetting("order", o)
            st:flush()
        end
    end
end

local ok, err = pcall(install)
if not ok then
    logger.warn("bookbench stories: not installed:", err)
end

package.loaded["bookbench_stories"] = Stories
return Stories
