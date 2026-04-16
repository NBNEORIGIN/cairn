from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.eval.suite import load_prompt_suite, score_answer


DEFAULT_SUITE = ROOT / 'projects' / 'deek' / 'eval_prompt_suite.json'
DEFAULT_CACHE = ROOT / 'data' / 'eval_cache.json'


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the DEEK live answer evaluator.')
    parser.add_argument('--api-url', default='http://localhost:8765')
    parser.add_argument('--api-key', default='deek-dev-key-change-in-production')
    parser.add_argument('--project', default='deek')
    parser.add_argument('--model', default='sonnet')
    parser.add_argument('--suite', default=str(DEFAULT_SUITE))
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--timeout', type=float, default=90.0)
    args = parser.parse_args()

    suite = load_prompt_suite(args.suite)[: args.limit]
    headers = {'X-API-Key': args.api_key, 'Content-Type': 'application/json'}
    results = []

    with httpx.Client(timeout=args.timeout) as client:
        for prompt in suite:
            session_id = f'eval-{prompt.prompt_id}-{uuid.uuid4().hex[:8]}'
            response = client.post(
                f'{args.api_url}/chat',
                headers=headers,
                json={
                    'project_id': args.project,
                    'session_id': session_id,
                    'content': prompt.prompt,
                    'model_override': args.model,
                },
            )
            response.raise_for_status()
            payload = response.json()
            answer = str(payload.get('content') or '')
            scored = score_answer(prompt, answer)
            results.append({
                'id': prompt.prompt_id,
                'passed': scored.passed,
                'score': scored.score,
                'missing_required': scored.missing_required,
                'forbidden_hits': scored.forbidden_hits,
                'model_used': payload.get('model_used'),
                'cost_usd': payload.get('cost_usd'),
            })

    passed = sum(1 for item in results if item['passed'])
    failed = len(results) - passed
    cache_payload = {
        'suite': Path(args.suite).name,
        'project': args.project,
        'model': args.model,
        'passed': passed,
        'failed': failed,
        'results': results,
        'last_run': datetime.utcnow().isoformat(),
    }
    DEFAULT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CACHE.write_text(json.dumps(cache_payload, indent=2), encoding='utf-8')
    print(json.dumps(cache_payload, indent=2))
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
