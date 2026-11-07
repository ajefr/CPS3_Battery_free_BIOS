-- coverage log while playing: CARTED=<this folder> COVP=<log prefix>
local d=os.getenv("CARTED")
dofile(d.."/coverage.lua")
dofile(d.."/play.lua")
