"""导入与问答两条流程共用的阶段上报。

节点用 ``@stage`` 装饰后，开始和结束时都会通过 LangGraph 的自定义事件流推送一条进度事件，
页面据此实时展示流程走到了哪一步::

    {"type": "stage", "node": "rerank", "label": "重排序", "status": "running"}
    {"type": "stage", "node": "rerank", "label": "重排序", "status": "done", "elapsed_ms": 412, "detail": "保留 4 条"}

节点返回的字典里可以带两个保留键（不会写入流程状态）：
``_detail`` —— 给使用者看的一句话结果；``_skipped`` —— 说明本阶段为什么被跳过。
"""
import functools
from time import perf_counter

from app.logging import logger


def stage(node: str, label: str):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state, runtime):
            write = runtime.stream_writer
            event = {"type": "stage", "node": node, "label": label}
            write({**event, "status": "running"})
            started = perf_counter()
            try:
                result = await func(state, runtime)
            except Exception as exc:
                logger.error("{} 失败：{}: {}", label, type(exc).__name__, exc)
                write({**event, "status": "failed"})
                raise
            result = dict(result or {})
            skipped = result.pop("_skipped", None)
            detail = result.pop("_detail", None)
            elapsed_ms = round((perf_counter() - started) * 1000)
            if skipped:
                write({**event, "status": "skipped", "detail": skipped})
            else:
                logger.info("{} 完成，用时 {} ms{}", label, elapsed_ms, f"（{detail}）" if detail else "")
                write({**event, "status": "done", "elapsed_ms": elapsed_ms, **({"detail": detail} if detail else {})})
            return result

        return wrapper

    return decorator
