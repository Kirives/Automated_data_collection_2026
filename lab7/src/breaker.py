import time

class CircuitBreaker:
    def __init__(self,threshold=3,cooldown=1.5):
        self.threshold=threshold;self.cooldown=cooldown;self.failures=0
        self.state='closed';self.opened_at=0;self.activations=0
    def allow(self):
        if self.state=='open':
            if time.monotonic()-self.opened_at<self.cooldown:return False
            self.state='half-open'
        return True
    def success(self):self.state='closed';self.failures=0
    def failure(self):
        self.failures+=1
        if self.state=='half-open' or self.failures>=self.threshold:
            self.state='open';self.opened_at=time.monotonic();self.activations+=1
