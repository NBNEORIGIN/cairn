import { NextResponse } from 'next/server';
import type { ModuleContext } from '@/lib/types';

interface ModuleSpec {
  name: string;
  url: string;
}

const MODULES: ModuleSpec[] = [
  { name: 'manufacture', url: 'http://localhost:8002/api/cairn/context' },
  { name: 'ledger',      url: 'http://localhost:8001/api/cairn/context' },
  { name: 'marketing',   url: 'http://localhost:8004/api/cairn/context' },
];

const TIMEOUT_MS = 2000;

async function fetchModule(spec: ModuleSpec): Promise<ModuleContext> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(spec.url, {
      signal: controller.signal,
      cache: 'no-store',
    });
    clearTimeout(timer);

    if (!res.ok) {
      return {
        module: spec.name,
        generated_at: new Date().toISOString(),
        summary: '',
        data: null,
        status: 'unavailable',
      };
    }

    const data = await res.json();
    return {
      module: spec.name,
      generated_at: data.generated_at ?? new Date().toISOString(),
      summary: data.summary ?? '',
      data: data.data ?? data,
      status: data.status ?? 'live',
    };
  } catch {
    clearTimeout(timer);
    return {
      module: spec.name,
      generated_at: new Date().toISOString(),
      summary: '',
      data: null,
      status: 'unavailable',
    };
  }
}

export async function GET() {
  const results = await Promise.allSettled(MODULES.map(fetchModule));

  const context: Record<string, ModuleContext> = {};

  for (let i = 0; i < MODULES.length; i++) {
    const spec = MODULES[i];
    const result = results[i];

    if (result.status === 'fulfilled') {
      context[spec.name] = result.value;
    } else {
      context[spec.name] = {
        module: spec.name,
        generated_at: new Date().toISOString(),
        summary: '',
        data: null,
        status: 'unavailable',
      };
    }
  }

  return NextResponse.json(context);
}
