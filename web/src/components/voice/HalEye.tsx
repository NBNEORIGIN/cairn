'use client'

/**
 * HAL 9000 eye component.
 *
 * Four visual states driven by props:
 *   idle       — slow breathing pulse (3s cycle, mid brightness)
 *   listening  — scale + brightness driven by mic amplitude (0..1)
 *   thinking   — rotating inner ring + steady brightness
 *   speaking   — pulsing brightness at ~5Hz (Web Speech has no amplitude API)
 *
 * Pure SVG. Transitions between states cross-fade via CSS transitions on
 * the underlying radii/opacity values.
 */
import React, { useEffect, useRef, useState } from 'react'

export type EyeState = 'idle' | 'listening' | 'thinking' | 'speaking'

export function HalEye({
  state,
  amplitude = 0,
  size = 320,
  onClick,
}: {
  state: EyeState
  amplitude?: number
  size?: number
  onClick?: () => void
}) {
  // Internal breathe clock for idle / speaking pulse (no mic amplitude then)
  const [pulse, setPulse] = useState(0)
  const rafRef = useRef<number | null>(null)
  const startRef = useRef<number>(Date.now())

  useEffect(() => {
    const loop = () => {
      const elapsed = (Date.now() - startRef.current) / 1000
      let p = 0
      if (state === 'idle') {
        // 3s breathing cycle, 0.2 amplitude
        p = 0.5 + 0.5 * Math.sin((elapsed * 2 * Math.PI) / 3)
        p = p * 0.3
      } else if (state === 'speaking') {
        // 5Hz faster pulse, 0.5 amplitude
        p = 0.5 + 0.5 * Math.sin(elapsed * 2 * Math.PI * 2.5)
        p = p * 0.5
      } else if (state === 'thinking') {
        p = 0.2
      }
      setPulse(p)
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [state])

  // Listening: use raw mic amplitude (clamped)
  const ampBoosted = Math.min(1, amplitude * 3) // boost since typical RMS is low
  const intensity =
    state === 'listening' ? ampBoosted : pulse

  // Scale factor for the inner glow
  const glowScale = 1 + intensity * 0.15

  // Brightness map for the central red
  const centreAlpha = 0.6 + intensity * 0.4
  const outerGlowAlpha = 0.15 + intensity * 0.35

  // Thinking state: spin the inner ring
  const [spin, setSpin] = useState(0)
  useEffect(() => {
    if (state !== 'thinking') return
    const id = setInterval(() => setSpin(s => (s + 6) % 360), 60)
    return () => clearInterval(id)
  }, [state])

  const cx = size / 2
  const cy = size / 2
  const rOuter = size * 0.48
  const rRing = size * 0.38
  const rPupil = size * 0.18
  const rCore = size * 0.06

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Deek HAL eye"
      className="relative block appearance-none bg-transparent p-0"
      style={{ width: size, height: size }}
    >
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        style={{
          filter: `drop-shadow(0 0 ${20 + intensity * 40}px rgba(239,68,68,${outerGlowAlpha}))`,
          transition: 'filter 200ms ease-out',
        }}
      >
        <defs>
          {/* Radial gradient for the core */}
          <radialGradient id="hal-core-grad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ffe5e5" stopOpacity={0.95} />
            <stop offset="20%" stopColor="#ffb4b4" stopOpacity={centreAlpha} />
            <stop offset="60%" stopColor="#dc2626" stopOpacity={centreAlpha * 0.9} />
            <stop offset="100%" stopColor="#450a0a" stopOpacity={0} />
          </radialGradient>
          <radialGradient id="hal-outer-grad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#1f2937" />
            <stop offset="85%" stopColor="#0f172a" />
            <stop offset="100%" stopColor="#020617" />
          </radialGradient>
        </defs>

        {/* Outer bezel */}
        <circle
          cx={cx}
          cy={cy}
          r={rOuter}
          fill="url(#hal-outer-grad)"
          stroke="#1f2937"
          strokeWidth={2}
        />

        {/* Glowing red iris */}
        <circle
          cx={cx}
          cy={cy}
          r={rRing}
          fill="#0b0b0b"
        />

        {/* Thinking-state rotating ring */}
        {state === 'thinking' && (
          <g transform={`rotate(${spin} ${cx} ${cy})`}>
            <circle
              cx={cx}
              cy={cy}
              r={rRing - 8}
              fill="none"
              stroke="rgba(239,68,68,0.4)"
              strokeWidth={2}
              strokeDasharray="8 16"
            />
          </g>
        )}

        {/* Core glow (scales with intensity) */}
        <g
          style={{
            transformOrigin: `${cx}px ${cy}px`,
            transform: `scale(${glowScale})`,
            transition: 'transform 120ms ease-out',
          }}
        >
          <circle
            cx={cx}
            cy={cy}
            r={rPupil}
            fill="url(#hal-core-grad)"
          />
          {/* Bright centre pinpoint */}
          <circle
            cx={cx}
            cy={cy}
            r={rCore * (1 + intensity * 0.3)}
            fill="#fff5f5"
            opacity={0.9}
          />
        </g>
      </svg>
    </button>
  )
}
