import { NextRequest, NextResponse } from 'next/server';
import { cairnFetch } from '@/lib/api';
import type { ProcessDoc } from '@/lib/types';

// Static process list — returned when no search query is provided.
// Extend this as NBNE's documented processes grow.
const STATIC_PROCESSES: ProcessDoc[] = [
  {
    id: 'proc-001',
    doc_number: 'MFG-001',
    title: 'Print Job Setup',
    summary: 'Checklist and settings for configuring a new print job on the wide-format press.',
    content:
      'Load media, calibrate colour profile, confirm bleed and safe-zone dimensions, run a test strip.',
  },
  {
    id: 'proc-002',
    doc_number: 'MFG-002',
    title: 'Lamination Process',
    summary: 'Steps for applying cold or hot laminate to finished print.',
    content:
      'Allow print to outgas for minimum 30 minutes. Set roller pressure and temperature per media spec. Feed leading edge straight.',
  },
  {
    id: 'proc-003',
    doc_number: 'MFG-003',
    title: 'Sign Installation Site Check',
    summary: 'Pre-installation checklist before attending a sign installation.',
    content:
      'Confirm fixings, wall type, access equipment, scaffold or MEWP permit if required, and site contact details.',
  },
  {
    id: 'proc-004',
    doc_number: 'MFG-004',
    title: 'Vehicle Wrap Preparation',
    summary: 'Surface preparation and panel sequence for full vehicle wrap.',
    content:
      'Clean with isopropyl alcohol, remove badges and trims where required, start at the roof and work down.',
  },
  {
    id: 'proc-005',
    doc_number: 'SHP-001',
    title: 'Artwork Approval Workflow',
    summary: 'How artwork moves from proof to sign-off.',
    content:
      'Send PDF proof to client. Await written approval by email or Phloe portal. Do not proceed to production without approval on file.',
  },
];

interface CairnMemoryResult {
  id?: string;
  chunk?: string;
  text?: string;
  content?: string;
  metadata?: {
    doc_number?: string;
    title?: string;
    summary?: string;
    [key: string]: unknown;
  };
}

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get('q')?.trim();

  if (!q) {
    return NextResponse.json(STATIC_PROCESSES);
  }

  let cairnRes: Response;
  try {
    cairnRes = await cairnFetch(
      `/memory/retrieve?query=${encodeURIComponent(q)}&project=manufacturing&limit=10`,
    );
  } catch {
    // Deek unavailable — fall back to static list filtered by query
    const lower = q.toLowerCase();
    const filtered = STATIC_PROCESSES.filter(
      (p) =>
        p.title.toLowerCase().includes(lower) ||
        p.summary.toLowerCase().includes(lower) ||
        p.content.toLowerCase().includes(lower),
    );
    return NextResponse.json(filtered);
  }

  if (!cairnRes.ok) {
    return NextResponse.json(
      { error: `Deek retrieval failed: ${cairnRes.status}` },
      { status: 502 },
    );
  }

  const raw: CairnMemoryResult[] = await cairnRes.json();

  const docs: ProcessDoc[] = raw.map((item, idx) => ({
    id: item.id ?? `cairn-${idx}`,
    doc_number: item.metadata?.doc_number ?? '',
    title: item.metadata?.title ?? `Result ${idx + 1}`,
    summary: item.metadata?.summary ?? '',
    content: item.chunk ?? item.text ?? item.content ?? '',
  }));

  return NextResponse.json(docs);
}
