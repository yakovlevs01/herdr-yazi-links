--- @since 26.8.15
--- @sync entry

local helper = "@HERDR_DRAG_HELPER@"

local selected_paths = ya.sync(function()
	local paths = {}
	for key, file in pairs(cx.active.selected) do
		local url = type(file) == "boolean" and key or file.url
		paths[#paths + 1] = tostring(url)
	end
	if #paths == 0 and cx.active.current.hovered then
		paths[1] = tostring(cx.active.current.hovered.url)
	end
	return paths
end)

local function redraw()
	-- Yazi 26.8 used ya.render; 26.9 exposes ui.render.
	if ui.render then ui.render() else ya.render() end
end

local begin = ya.sync(function(state, id, value)
	state.jobs = state.jobs or {}
	for key, job in pairs(state.jobs) do
		if job.state == "done" or job.state == "error" or job.state == "cancelled" then state.jobs[key] = nil end
	end
	state.sequence = (state.sequence or 0) + 1
	value.sequence = state.sequence
	state.jobs[id] = value
	redraw()
end)

local update = ya.sync(function(state, id, value)
	local old = (state.jobs or {})[id]
	if not old then return end
	value.sequence = old.sequence
	state.jobs[id] = value
	redraw()
end)

local clear_done = ya.sync(function(state, id)
	local job = (state.jobs or {})[id]
	if job and job.state == "done" then
		state.jobs[id] = nil
		redraw()
	end
end)

local function decode(text)
	local ok, value = pcall(ya.json_decode, text)
	return ok and type(value) == "table" and value or nil
end

local function clean(text)
	return tostring(text or ""):gsub("[%c]", " ")
end

local function status_text(state, width)
	local active, chosen = 0, nil
	for _, job in pairs(state.jobs or {}) do
		local running = job.state ~= "done" and job.state ~= "error" and job.state ~= "cancelled"
		if running then active = active + 1 end
		if not chosen or (running and (chosen.state == "done" or chosen.state == "error" or chosen.state == "cancelled"))
			or (running == (chosen.state ~= "done" and chosen.state ~= "error" and chosen.state ~= "cancelled") and job.sequence < chosen.sequence) then
			chosen = job
		end
	end
	if not chosen then return "", "blue" end
	local text, color = "", "blue"
	if chosen.state == "error" then
		text, color = "Drag error: " .. clean(chosen.message), "red"
	elseif chosen.state == "done" then
		text, color = "Drag: ready", "green"
	elseif chosen.state == "cancelled" then
		text, color = "Drag: cancelled", "yellow"
	elseif chosen.state == "queued" then
		text = "Drag: queued"
	else
		local percent = math.max(0, math.min(99, tonumber(chosen.percent) or 0))
		text = string.format("Drag %d/%d %d%%", chosen.file_index or 0, chosen.file_count or 0, percent)
		if width >= 36 then
			local filled = math.floor(percent * 8 / 100)
			text = text .. " [" .. string.rep("█", filled) .. string.rep("░", 8 - filled) .. "]"
		end
		if width >= 62 and chosen.bytes_total then
			text = text .. string.format(" %.1f/%.1f MiB", (chosen.bytes_done or 0) / 1048576, chosen.bytes_total / 1048576)
		end
	end
	if active > 1 then text = text .. " +" .. (active - 1) end
	return text, color
end

return {
	setup = function(state)
		if state.status_child then return end
		state.jobs = state.jobs or {}
		state.status_child = Status:children_add(function(status)
			-- Reserve space for Yazi's permissions and position segments. Otherwise
			-- a long message pushes its own prefix outside a narrow pane.
			local width = math.max(10, math.min(math.floor(status._area.w * 0.65), status._area.w - 40))
			local text, color = status_text(state, width)
			if text == "" then return "" end
			return ui.Line { ui.Span(" " .. ui.truncate(text, { max = width }) .. " "):fg(color) }
		end, 500, Status.RIGHT)
	end,

	run = function(context)
		local scope = rt.scope():child()
		if os.getenv("HERDR_ENV") ~= "1" or not os.getenv("HERDR_SESSION") then
			return ya.emit("shell", { "ripdrag -x -a -n -b %s" })
		end
		local paths = selected_paths()
		if #paths == 0 then
			return begin("submit", { state = "error", message = "No file selected" })
		end
		local output, err = Command("python3"):arg({ helper, "submit", "--watched", "--" }):arg(paths):output()
		if not output or not output.status.success then
			return begin("submit", { state = "error", message = output and output.stderr or tostring(err) })
		end
		local result = decode(output.stdout)
		if not result then
			return begin("submit", { state = "error", message = "Invalid helper response" })
		end
		if not result.id then return end -- Local Herdr launches ripdrag directly.
		local id = result.id
		context.id = id
		begin(id, { state = "queued", file_count = #paths })
		local task = ya.task("custom", { pool = "none", scope = scope, track = true, progress = true })
			:name("Download to local ripdrag"):spawn()
		context.task = task
		if not task:acquire() then return end
		local child, spawn_error = Command("python3"):arg({ helper, "watch", "--heartbeat", id })
			:stdout(Command.PIPED):stderr(Command.PIPED):spawn()
		context.child = child
		if not child then
			task:fail(tostring(spawn_error))
			return update(id, { state = "error", message = tostring(spawn_error) })
		end
		local terminal, cancelled = false, false
		local workload, processed = 0, 0
		task:progress { total = #paths }
		while true do
			if not cancelled and not task:acquire() then
				child:start_kill()
				child:wait()
				-- Observe the receiver's acknowledgement without holding the lease.
				cancelled = true
				child = Command("python3"):arg({ helper, "watch", "--observe", id })
					:stdout(Command.PIPED):stderr(Command.PIPED):spawn()
				context.child = child
				if not child then return update(id, { state = "error", message = "Cannot observe cancellation" }) end
			end
			local line, event = child:read_line()
			if event == 2 then break end
			if event == 0 and line then
				local value = decode(line)
				if value and value.id == id then
					update(id, value)
					local total, done = value.bytes_total or workload, value.bytes_done or processed
					if not cancelled then task:progress { workload = math.max(0, total - workload), processed = math.max(0, done - processed) } end
					workload, processed = total, done
					terminal = value.state == "done" or value.state == "error" or value.state == "cancelled"
					if not cancelled then
						if value.state == "done" then task:succeed()
						elseif terminal then task:fail(value.message or value.state) end
					end
				end
			elseif event == 1 and line then
				update(id, { state = "error", message = clean(line) })
				task:fail(clean(line))
				terminal = true
			end
		end
		child:wait()
		if not terminal then
			task:fail("Progress connection closed")
			update(id, { state = "error", message = "Progress connection closed" })
		end
		ya.sleep(3)
		clear_done(id)
	end,
	entry = function(self)
		ya.async(function()
			local context = {}
			local ok, err = pcall(self.run, context)
			if not ok then
				ya.err(tostring(err))
				if context.child then context.child:start_kill(); context.child:wait() end
				if context.task then context.task:fail(tostring(err)) end
				local value = { state = "error", message = tostring(err) }
				if context.id then update(context.id, value) else begin("plugin", value) end
			end
		end)
	end,
}
