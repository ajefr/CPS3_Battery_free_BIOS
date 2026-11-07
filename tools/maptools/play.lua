-- random inputs to cover the game (coins, start, players 1 and 2)
local f={} local names={} local starts={} local coins={}
for tag,port in pairs(manager.machine.ioport.ports) do for name,fl in pairs(port.fields) do
  f[name]=fl
  if name:match("Start") then table.insert(starts,fl)
  elseif name:match("^Coin") then table.insert(coins,fl)
  elseif name:match("^P[12] ") then table.insert(names,fl) end
end end
local seed=tonumber(os.getenv("SEED") or "1"); math.randomseed(seed)
local n=0
play_cb=emu.register_frame_done(function() n=n+1
  local t=n%1800
  if n>3000 then
    if t==0 then for _,c in ipairs(coins) do c:set_value(1) end end
    if t==10 then for _,c in ipairs(coins) do c:set_value(0) end end
    if t==60 or t==300 then for _,s in ipairs(starts) do s:set_value(1) end end
    if t==70 or t==310 then for _,s in ipairs(starts) do s:set_value(0) end end
    if n%4==0 then for _,k in ipairs(names) do k:set_value(math.random()<0.25 and 1 or 0) end end
  end
  if n%3600==0 and os.getenv("SNAP") then manager.machine.video:snapshot() end
end)
