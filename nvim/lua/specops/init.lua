local M = {}
local function run_cmd(cmd)
  local out = vim.fn.system(cmd)
  return out
end

function M.brainstorm()
  local feature = vim.fn.input("Feature: ")
  if feature == "" then return end
  local cmd = "python3 src/cli/specops_cli.py brainstorm " .. feature
  local out = run_cmd(cmd)
  vim.cmd("vnew")
  vim.api.nvim_buf_set_lines(0,0,-1,false, vim.split(out, "\n"))
end

function M.plan()
  local feature = vim.fn.input("Feature: ")
  if feature == "" then return end
  local cmd = "python3 src/cli/specops_cli.py plan " .. feature
  local out = run_cmd(cmd)
  vim.cmd("vnew")
  vim.api.nvim_buf_set_lines(0,0,-1,false, vim.split(out, "\n"))
end

function M.work()
  local feature = vim.fn.input("Feature: ")
  if feature == "" then return end
  local cmd = "python3 src/cli/specops_cli.py work " .. feature
  local out = run_cmd(cmd)
  vim.cmd("vnew")
  vim.api.nvim_buf_set_lines(0,0,-1,false, vim.split(out, "\n"))
end

vim.api.nvim_create_user_command("SpecOpsBrainstorm", M.brainstorm, {})
vim.api.nvim_create_user_command("SpecOpsPlan", M.plan, {})
vim.api.nvim_create_user_command("SpecOpsWork", M.work, {})
return M

