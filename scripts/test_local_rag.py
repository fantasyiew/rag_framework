"""Manual local smoke test: python scripts/test_local_rag.py --query '你的问题'."""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(argv=None):
    parser = argparse.ArgumentParser(description='测试本地 POST /v1/rag（会执行检索和生成）')
    parser.add_argument('--url', default='http://127.0.0.1:8000/v1/rag', help='完整端点地址')
    parser.add_argument('--query', default='东京有哪些适合赏樱的景点？', help='用户问题')
    parser.add_argument('--knowledge-base-id', default='default', help='知识库 ID，不是名称')
    parser.add_argument('--conversation-id', help='可选 Trace 归组标识')
    parser.add_argument('--history', action='append', default=[], help='历史文本，可重复传入；不会自动加载会话')
    parser.add_argument('--include-trace', action='store_true', help='返回完整 Trace')
    parser.add_argument('--timeout', type=float, default=120, help='客户端超时秒数，默认 120')
    parser.add_argument('--json', action='store_true', dest='print_json', help='打印完整 JSON 响应')
    args = parser.parse_args(argv)
    if not args.query.strip() or args.timeout <= 0:
        parser.error('query 不能空白，timeout 必须大于 0')
    payload = {'query': args.query, 'knowledge_base_id': args.knowledge_base_id,
               'history': args.history, 'include_trace': args.include_trace}
    if args.conversation_id:
        payload['conversation_id'] = args.conversation_id
    request = Request(args.url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                      method='POST')
    try:
        with urlopen(request, timeout=args.timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        try:
            detail = json.loads(body).get('detail', '未提供错误详情')
        except (ValueError, AttributeError):
            detail = '响应不是 JSON，请检查端点地址和服务日志'
        print(f'HTTP {exc.code}：{json.dumps(detail, ensure_ascii=False)}', file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError) as exc:
        print(f'连接失败或超时：{exc}。请确认服务已启动且地址正确。', file=sys.stderr)
        return 1
    except ValueError:
        print('响应不是有效 JSON，请检查是否连接到了正确的服务。', file=sys.stderr)
        return 1
    if not isinstance(result, dict) or not isinstance(result.get('answer'), str) or not isinstance(result.get('generation'), dict):
        print('响应缺少 answer / generation，可能是服务版本或端点错误。', file=sys.stderr)
        return 1
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        generation = result['generation']
        print('最终回答：\n' + result['answer'])
        print(f"\n状态：{generation.get('status')} · 模型：{generation.get('model')} · 降级：{generation.get('fallback_used')}")
        print(f"上下文：{len(result.get('contexts', []))} · 引用：{len(result.get('citations', []))}")
        print(f"Trace ID：{result.get('trace_id')}")
        print(f"配置版本：{result.get('config_version')} · 耗时：{result.get('duration_ms')} ms")
        for index, context in enumerate(result.get('contexts', []), 1):
            chunk = context.get('chunk', {})
            print(f"\n[{index}] chunk_id={chunk.get('id')} · score={context.get('score')}")
            print(chunk.get('content', ''))
        if args.include_trace:
            print('\n完整 Trace：\n' + json.dumps(result.get('trace'), ensure_ascii=False, indent=2))
    if result['generation'].get('status') == 'empty_answer':
        print('警告：服务执行结束但回答为空，请按 Trace ID 排查。', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())

# .venv\Scripts\python.exe scripts\test_local_rag.py --query "日本第一座国立美术馆是哪个" --json