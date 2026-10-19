"""Completed-case counts and cancellation-safe SSE evaluation transport."""
import asyncio
import json


class EvaluationProgress:
    def __init__(self, total, callback=None):
        self.total, self.callback = total, callback
        self.completed = self.successful = self.failed = 0

    def record(self, result):
        self.completed += 1
        if result.error:
            self.failed += 1
        else:
            self.successful += 1
        if self.callback:
            self.callback({'total': self.total, 'completed': self.completed,
                           'successful': self.successful, 'failed': self.failed,
                           'case_id': result.case_id})


async def evaluation_events(evaluator, request):
    queue = asyncio.Queue()
    def progress(value):
        queue.put_nowait(('progress', value))

    async def run():
        try:
            report = await evaluator.evaluate(request, on_progress=progress)
            await queue.put(('complete', report.model_dump(mode='json')))
        except Exception as exc:  # noqa: BLE001 - Never stream provider bodies or credentials.
            await queue.put(('error', {'message': '评估执行或报告保存失败，请检查服务日志。', 'error': type(exc).__name__}))

    def encode(event, payload):
        return f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'

    task = asyncio.create_task(run())
    try:
        yield encode('start', {'total': len(request.cases), 'completed': 0, 'successful': 0, 'failed': 0})
        while True:
            try:
                event, payload = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield ': heartbeat\n\n'
                continue
            yield encode(event, payload)
            if event in {'complete', 'error'}:
                return
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
