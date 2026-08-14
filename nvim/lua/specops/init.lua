local M = {}

-- Resolve the project root from this file's own location:
-- nvim/lua/specops/init.lua -> project root is three levels up.
local function project_root()
  local src = debug.getinfo(1, "S").source:sub(2)
  local dir = vim.fn.fnamemodify(src, ":p:h")
  return vim.fn.fnamemodify(dir, ":h:h:h")
end

local ROOT = project_root()
local SPECOPS_BIN = ROOT .. "/.venv/bin/specops"

-- Runs specops as an argv list (no shell involved, so feature names can
-- never be interpreted as shell syntax) from the project root.
local function run_specops(args, stdin)
  local cmd = { SPECOPS_BIN }
  for _, a in ipairs(args) do
    table.insert(cmd, a)
  end
  return vim.fn.system(cmd, stdin)
end

local function show_in_buffer(title, text)
  vim.cmd("vnew")
  vim.bo.buftype = "nofile"
  vim.bo.bufhidden = "wipe"
  vim.api.nvim_buf_set_name(0, title)
  vim.api.nvim_buf_set_lines(0, 0, -1, false, vim.split(text, "\n"))
end

local function prompt_feature()
  local feature = vim.fn.input("Feature: ")
  if feature == "" then
    return nil
  end
  -- Mirror the CLI's own validation so a bad name fails fast, in the UI,
  -- instead of silently reaching the shell.
  if not feature:match("^[%w_%-]+$") then
    vim.notify(
      "Invalid feature name: only letters, digits, '-' and '_' are allowed.",
      vim.log.levels.ERROR
    )
    return nil
  end
  return feature
end

function M.brainstorm()
  local feature = prompt_feature()
  if not feature then return end
  local out = run_specops({ "brainstorm", feature })
  show_in_buffer("specops://brainstorm/" .. feature, out)
end

function M.plan()
  local feature = prompt_feature()
  if not feature then return end
  local out = run_specops({ "plan", feature })
  show_in_buffer("specops://plan/" .. feature, out)
end

function M.work()
  local feature = prompt_feature()
  if not feature then return end
  local out = run_specops({ "work", feature })
  show_in_buffer("specops://work/" .. feature, out)
end

function M.review()
  local feature = prompt_feature()
  if not feature then return end
  local out = run_specops({ "review", feature })
  show_in_buffer("specops://review/" .. feature, out)
end

-- Shows the generated patch for human review before touching anything,
-- then asks for an explicit Neovim confirmation, and only if approved
-- feeds the CLI's own 'yes' prompt over stdin.
function M.apply()
  local feature = prompt_feature()
  if not feature then return end

  local patch_path = ROOT .. "/out/" .. feature .. ".patch"
  if vim.fn.filereadable(patch_path) == 0 then
    vim.notify("Patch not found: " .. patch_path, vim.log.levels.ERROR)
    return
  end
  show_in_buffer("specops://apply/" .. feature, table.concat(vim.fn.readfile(patch_path), "\n"))

  local choice = vim.fn.confirm(
    "Apply patch for '" .. feature .. "'? This creates a new branch and commits.",
    "&Yes\n&No",
    2
  )
  if choice ~= 1 then
    vim.notify("Apply aborted.", vim.log.levels.INFO)
    return
  end

  local out = run_specops({ "apply", feature }, "yes\n")
  show_in_buffer("specops://apply-result/" .. feature, out)
end

vim.api.nvim_create_user_command("SpecOpsBrainstorm", M.brainstorm, {})
vim.api.nvim_create_user_command("SpecOpsPlan", M.plan, {})
vim.api.nvim_create_user_command("SpecOpsWork", M.work, {})
vim.api.nvim_create_user_command("SpecOpsReview", M.review, {})
vim.api.nvim_create_user_command("SpecOpsApply", M.apply, {})

return M
