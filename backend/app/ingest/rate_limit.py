"""滑动窗口限速器：控制调用外部模型接口的频率。"""
import asyncio
import time
from collections import deque
from typing import Awaitable, Callable


class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.max_calls = max(1, max_calls)
        self.window = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """窗口内的调用次数已满时，等到最早的一次调用滑出窗口再放行。"""
        async with self._lock:
            now = self._clock()
            self._drop_expired(now)
            if len(self._calls) >= self.max_calls:
                await self._sleep(self.window - (now - self._calls[0]))
                now = self._clock()
                self._drop_expired(now)
            self._calls.append(now)

    def _drop_expired(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self.window:
            self._calls.popleft()
