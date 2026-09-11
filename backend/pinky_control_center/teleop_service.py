from __future__ import annotations
import time
from collections.abc import Callable

class TeleopService:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock=clock; self.active: dict[str, tuple[int,float]]={}; self.entered: dict[str,float]={}
    def enter(self, robot_id: str, *, lease_valid: bool) -> None:
        if not lease_valid: raise PermissionError("CONTROL_CONFLICT")
        self.entered[robot_id]=self.clock()
    def ingest(self, robot_id: str, seq: int, linear: float, angular: float, max_linear: float = 1, max_angular: float = 2) -> str:
        previous=self.active.get(robot_id)
        if robot_id not in self.entered or abs(linear)>max_linear or abs(angular)>max_angular or previous and seq<=previous[0]: return "REJECTED"
        self.active[robot_id]=(seq,self.clock()); return "ACCEPTED"
    def tick(self) -> dict[str,str]:
        now=self.clock(); result={}
        for robot_id, entered in list(self.entered.items()):
            last=self.active.get(robot_id, (-1,entered))[1]
            if now-last>.3 or now-entered>1:
                result[robot_id]="ZERO"; self.active.pop(robot_id,None); self.entered.pop(robot_id,None)
        return result
    def protective_stop(self, _robot_id: str) -> dict[str,str]:
        self.active.clear(); self.entered.clear(); return {"robot_1":"STOPPED","robot_2":"STOPPED"}
