--- @since 26.5.6

-- The installer replaces this string with the checkout's absolute helper path.
local helper = "@HERDR_DRAG_HELPER@"

local selected_paths = ya.sync(function()
	local paths = {}
	for key, file in pairs(cx.active.selected) do
		-- Recent Yazi exposes index/File; older 26.x exposes Url/boolean.
		local url = type(file) == "boolean" and key or file.url
		paths[#paths + 1] = tostring(url)
	end
	if #paths == 0 and cx.active.current.hovered then
		paths[1] = tostring(cx.active.current.hovered.url)
	end
	return paths
end)

return {
	entry = function()
		if os.getenv("HERDR_ENV") ~= "1" or not os.getenv("HERDR_SESSION") then
			-- Keep Yazi 26's selected-or-hovered expansion for ordinary local use.
			return ya.emit("shell", { "ripdrag -x -a -n -b %s" })
		end

		local paths = selected_paths()
		if #paths == 0 then
			return ya.notify { title = "Herdr drag", content = "No file selected", level = "warn", timeout = 5 }
		end

		-- entry is async; only the selection snapshot above enters sync context.
		-- Command passes each filename as an argument without shell evaluation.
		local output, err = Command("python3"):arg({ helper, "submit", "--" }):arg(paths):output()
		if not output or not output.status.success then
			return ya.notify {
				title = "Herdr drag",
				content = output and output.stderr or tostring(err),
				level = "error",
				timeout = 10,
			}
		end
		local decoded, result = pcall(function() return ya.json_decode(output.stdout) end)
		ya.notify {
			title = "Herdr drag",
			content = decoded and type(result) == "table" and result.message or "Request accepted; see the local receiver log for progress",
			level = "info",
			timeout = 5,
		}
	end,
}
