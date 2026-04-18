'use client'

/**
 * Deek's self-designed "face" — the Constellation Network.
 *
 * Deek chose this when asked to design its own interface (see session
 * "design-my-face-1" in memory). Seven nodes, subtly one per day of the
 * week, connected by thin lines. Nodes drift on independent sinusoidal
 * timers so the whole thing feels alive without being fidgety.
 *
 * Four states mirror the HAL eye:
 *
 *   idle       — slow drift, static lines, low opacity
 *   listening  — faster drift + ring pulse from the centre-nearest node
 *   thinking   — travelling dot hops between random nodes along lines
 *   speaking   — all nodes pulse outward on a rhythm, line opacity
 *                 flickers in cascade
 *
 * Pure SVG + CSS + React state on a single requestAnimationFrame loop.
 * No WebGL, no external libraries.
 */
import { useEffect, useRef, useState } from 'react'
import type { EyeState } from './HalEye'

interface Node {
  baseX: number
  baseY: number
  phaseX: number
  phaseY: number
  x: number
  y: number
}

interface ThinkDot {
  fromIdx: number
  toIdx: number
  progress: number // 0..1
  speed: number
}

const NODE_COUNT = 7

// Seed positions on a gentle circle — jittered so it doesn't look like
// a wheel. Normalised to [-1..1] in each axis; scaled to viewBox at
// render time.
function seedNodes(): Node[] {
  const nodes: Node[] = []
  for (let i = 0; i < NODE_COUNT; i++) {
    const angle = (i / NODE_COUNT) * Math.PI * 2 + (i * 0.13)
    const radius = 0.55 + (i % 3) * 0.12  // 0.55..0.79
    const baseX = Math.cos(angle) * radius
    const baseY = Math.sin(angle) * radius
    nodes.push({
      baseX,
      baseY,
      phaseX: Math.random() * Math.PI * 2,
      phaseY: Math.random() * Math.PI * 2,
      x: baseX,
      y: baseY,
    })
  }
  return nodes
}

export function DeekConstellation({
  state,
  soundIntensity = 0,
  size = 320,
  onClick,
}: {
  state: EyeState
  soundIntensity?: number   // 0..1, passed when listening so nodes react
  size?: number
  onClick?: () => void
}) {
  const [nodes, setNodes] = useState<Node[]>(() => seedNodes())
  const [thinkDots, setThinkDots] = useState<ThinkDot[]>([])
  const [speakPulse, setSpeakPulse] = useState(0)
  const rafRef = useRef<number | null>(null)
  const startRef = useRef<number>(Date.now())

  // ── Animation loop ───────────────────────────────────────────────
  useEffect(() => {
    const loop = () => {
      const t = (Date.now() - startRef.current) / 1000

      // Drift speed scales with state
      const driftSpeed =
        state === 'listening' ? 0.9 + soundIntensity * 1.2
        : state === 'speaking' ? 0.8
        : state === 'thinking' ? 0.5
        : 0.25
      const driftMag =
        state === 'listening' ? 0.06 + soundIntensity * 0.08
        : state === 'speaking' ? 0.05
        : 0.025

      setNodes(prev =>
        prev.map(n => ({
          ...n,
          x: n.baseX + Math.sin(t * driftSpeed + n.phaseX) * driftMag,
          y: n.baseY + Math.cos(t * driftSpeed + n.phaseY) * driftMag,
        })),
      )

      // Speaking pulse — fast sin wave
      if (state === 'speaking') {
        setSpeakPulse(0.5 + 0.5 * Math.sin(t * Math.PI * 2 * 2.2))
      } else {
        setSpeakPulse(0)
      }

      // Thinking: move dots along their paths, spawn new ones when needed
      if (state === 'thinking') {
        setThinkDots(prev => {
          let updated = prev
            .map(d => ({ ...d, progress: d.progress + d.speed }))
            .filter(d => d.progress < 1)
          // Spawn if fewer than 2 active
          while (updated.length < 2) {
            const fromIdx = Math.floor(Math.random() * NODE_COUNT)
            let toIdx = Math.floor(Math.random() * NODE_COUNT)
            if (toIdx === fromIdx) toIdx = (toIdx + 1) % NODE_COUNT
            updated.push({
              fromIdx,
              toIdx,
              progress: 0,
              speed: 0.018 + Math.random() * 0.015,
            })
          }
          return updated
        })
      } else if (thinkDots.length > 0) {
        setThinkDots([])
      }

      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, soundIntensity])

  // ── Render helpers ───────────────────────────────────────────────
  const half = size / 2
  // Map normalised [-1..1] → pixel coords with some margin
  const toPx = (v: number) => half + v * (half * 0.85)

  // Find the node nearest to centre (for the listening ring pulse)
  const centreNearestIdx = nodes.reduce(
    (best, n, i) => {
      const d = Math.hypot(n.x, n.y)
      return d < best.d ? { d, i } : best
    },
    { d: Infinity, i: 0 },
  ).i

  // Colour palette — inspired by NBNE brand (teal + amber accent)
  const NODE_COLOUR = state === 'listening'
    ? '#f59e0b'  // amber
    : state === 'thinking'
    ? '#22d3ee'  // cyan
    : state === 'speaking'
    ? '#34d399'  // emerald
    : '#94a3b8'  // slate
  const LINE_COLOUR = state === 'listening'
    ? 'rgba(245,158,11,0.35)'
    : state === 'thinking'
    ? 'rgba(34,211,238,0.3)'
    : state === 'speaking'
    ? 'rgba(52,211,153,0.35)'
    : 'rgba(148,163,184,0.2)'

  // Which lines to draw — fully-connected is too busy with 7 nodes (21 lines).
  // Draw each node to its 2 nearest neighbours.
  const edges: [number, number][] = []
  const drawnPairs = new Set<string>()
  for (let i = 0; i < nodes.length; i++) {
    const distances = nodes
      .map((n, j) => ({
        j,
        d: i === j ? Infinity : Math.hypot(n.x - nodes[i].x, n.y - nodes[i].y),
      }))
      .sort((a, b) => a.d - b.d)
    for (let k = 0; k < 2; k++) {
      const j = distances[k].j
      const key = i < j ? `${i}-${j}` : `${j}-${i}`
      if (!drawnPairs.has(key)) {
        drawnPairs.add(key)
        edges.push([i, j])
      }
    }
  }

  // Node sizes: pulse with speaking, boost listening-closest node
  const nodeR = (i: number) => {
    const base = 4
    if (state === 'speaking') return base + 3 * speakPulse
    if (state === 'listening') {
      return base + (i === centreNearestIdx ? 2 + soundIntensity * 4 : 0)
    }
    return base
  }

  // Line opacity cascade when speaking
  const lineOpacity = (i: number) => {
    if (state !== 'speaking') return 1
    const t = (Date.now() - startRef.current) / 1000
    const wave = 0.5 + 0.5 * Math.sin(t * 4 - i * 0.6)
    return 0.4 + wave * 0.6
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Deek constellation"
      className="relative block appearance-none bg-transparent p-0"
      style={{ width: size, height: size }}
    >
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        style={{
          filter:
            state === 'listening'
              ? `drop-shadow(0 0 ${20 + soundIntensity * 20}px rgba(245,158,11,0.4))`
              : state === 'speaking'
              ? `drop-shadow(0 0 ${16 + speakPulse * 20}px rgba(52,211,153,0.35))`
              : state === 'thinking'
              ? 'drop-shadow(0 0 18px rgba(34,211,238,0.3))'
              : 'drop-shadow(0 0 10px rgba(148,163,184,0.15))',
          transition: 'filter 200ms ease-out',
        }}
      >
        {/* Soft backdrop */}
        <circle cx={half} cy={half} r={half * 0.95} fill="rgba(15,23,42,0.8)" />

        {/* Connecting lines */}
        {edges.map(([i, j], idx) => (
          <line
            key={`line-${i}-${j}`}
            x1={toPx(nodes[i].x)}
            y1={toPx(nodes[i].y)}
            x2={toPx(nodes[j].x)}
            y2={toPx(nodes[j].y)}
            stroke={LINE_COLOUR}
            strokeWidth={1}
            opacity={lineOpacity(idx)}
          />
        ))}

        {/* Thinking dots travelling along edges */}
        {state === 'thinking' &&
          thinkDots.map((d, i) => {
            const a = nodes[d.fromIdx]
            const b = nodes[d.toIdx]
            const cx = toPx(a.x + (b.x - a.x) * d.progress)
            const cy = toPx(a.y + (b.y - a.y) * d.progress)
            return (
              <circle
                key={`think-${i}`}
                cx={cx}
                cy={cy}
                r={3}
                fill="#22d3ee"
                opacity={0.9}
              >
                <animate
                  attributeName="r"
                  values="2;4;2"
                  dur="1s"
                  repeatCount="indefinite"
                />
              </circle>
            )
          })}

        {/* Listening ring pulse from centre-nearest node */}
        {state === 'listening' && soundIntensity > 0.1 && (
          <circle
            cx={toPx(nodes[centreNearestIdx].x)}
            cy={toPx(nodes[centreNearestIdx].y)}
            r={nodeR(centreNearestIdx) + 10 + soundIntensity * 20}
            fill="none"
            stroke="rgba(245,158,11,0.5)"
            strokeWidth={1.5}
            opacity={0.6}
          />
        )}

        {/* Nodes */}
        {nodes.map((n, i) => (
          <circle
            key={`node-${i}`}
            cx={toPx(n.x)}
            cy={toPx(n.y)}
            r={nodeR(i)}
            fill={NODE_COLOUR}
            opacity={state === 'idle' ? 0.7 : 1}
            style={{ transition: 'r 100ms ease-out, opacity 200ms ease' }}
          />
        ))}

        {/* Central mass (the "self") — subtle */}
        <circle
          cx={half}
          cy={half}
          r={state === 'speaking' ? 3 + speakPulse * 2 : 2.5}
          fill={NODE_COLOUR}
          opacity={0.5}
        />
      </svg>
    </button>
  )
}
