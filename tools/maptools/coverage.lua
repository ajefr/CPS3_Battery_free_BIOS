-- coverage: SIMM 1/2 half-words executed (opcode fetches) and read as data
-- (MAME 0.264+, run with -nodrc; output files $COVP.code / $COVP.data)
local cpu=manager.machine.devices[":maincpu"]
local prog=cpu.spaces["program"] local op=cpu.spaces["decrypted_opcodes"]
local C={} local D={}
local function rec(t,off,mask)
  local a=off&0xfffffffc
  if (mask>>16)&0xffff ~= 0 then t[a]=true end
  if mask&0xffff ~= 0 then t[a+2]=true end
end
cov_taps={
  op:install_read_tap(0x06000000,0x06ffffff,"cov_op",function(o,d,m) rec(C,o,m) end),
  prog:install_read_tap(0x06000000,0x06ffffff,"cov_rd",function(o,d,m) rec(D,o,m) end)}
local function dump()
  for name,t in pairs({code=C,data=D}) do
    local f=io.open(os.getenv("COVP").."."..name,"w") local n=0
    for k in pairs(t) do f:write(string.format("%08x\n",k)) n=n+1 end f:close()
    print(name,n)
  end
end
cov_stop=emu.add_machine_stop_notifier(dump)
local fr=0
cov_fr=emu.register_frame_done(function() fr=fr+1 if fr%18000==0 then dump() end end)
