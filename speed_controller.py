class BehaviorMode:
    SPEED = "speed"
    SAFE = "safe"
    AUTO = "auto"

class SpeedController:
    def __init__(self, mode=BehaviorMode.AUTO):
        self.mode = mode
        self.safe_count = 0  # 連續遇到CF challenge次數
        self.speed_count = 0 # 連續沒遇到 challenge 次數
        self.current = BehaviorMode.SPEED
        self.CF_THRESHOLD = 2   # 幾次遇到 challenge 自動進入 safe
        self.SPEED_RECOVER = 8  # 幾件都沒遇到 challenge 自動回 speed

    def update(self, cf_challenge_detected: bool):
        if self.mode == BehaviorMode.AUTO:
            if cf_challenge_detected:
                self.safe_count += 1
                self.speed_count = 0
                if self.safe_count >= self.CF_THRESHOLD:
                    self.current = BehaviorMode.SAFE
            else:
                self.safe_count = 0
                self.speed_count += 1
                if self.speed_count >= self.SPEED_RECOVER:
                    self.current = BehaviorMode.SPEED

    def get_params(self):
        if self.mode == BehaviorMode.SAFE or self.current == BehaviorMode.SAFE:
            return dict(delay=(0.3, 1.1), mouse_steps=6, scroll_times=1)
        else:
            return dict(delay=(0.03, 0.08), mouse_steps=1, scroll_times=0)