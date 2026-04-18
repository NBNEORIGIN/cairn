'use client'

/**
 * useMicAmplitude — subscribes to the microphone via Web Audio API and
 * returns a 0..1 amplitude value updated via requestAnimationFrame.
 *
 * Starts only when `enabled` is true. Releases the mic when disabled.
 * Handles permission denial gracefully (returns 0).
 *
 * The underlying AnalyserNode computes RMS over an FFT frame; we apply
 * a simple smoothing lerp so the eye doesn't twitch on every sample.
 */
import { useEffect, useRef, useState } from 'react'

export function useMicAmplitude(enabled: boolean): number {
  const [amp, setAmp] = useState(0)
  const ampRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const ctxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)

  useEffect(() => {
    if (!enabled) {
      return () => {}
    }
    let cancelled = false

    const start = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        })
        if (cancelled) {
          stream.getTracks().forEach(t => t.stop())
          return
        }
        streamRef.current = stream
        const Ctx =
          (window.AudioContext as typeof AudioContext) ||
          ((window as any).webkitAudioContext as typeof AudioContext)
        const ctx = new Ctx()
        ctxRef.current = ctx
        const source = ctx.createMediaStreamSource(stream)
        const analyser = ctx.createAnalyser()
        analyser.fftSize = 512
        analyser.smoothingTimeConstant = 0.8
        source.connect(analyser)
        analyserRef.current = analyser

        const data = new Uint8Array(analyser.frequencyBinCount)
        const loop = () => {
          if (cancelled) return
          analyser.getByteTimeDomainData(data)
          // Compute RMS of the 0-255 samples (128 = silence)
          let sum = 0
          for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128
            sum += v * v
          }
          const rms = Math.sqrt(sum / data.length)
          // Lerp for smoothness
          ampRef.current = ampRef.current * 0.7 + rms * 0.3
          setAmp(ampRef.current)
          rafRef.current = requestAnimationFrame(loop)
        }
        rafRef.current = requestAnimationFrame(loop)
      } catch (err) {
        // Mic denied or no device — leave amp at 0
        console.warn('[useMicAmplitude] could not start mic:', err)
      }
    }

    start()

    return () => {
      cancelled = true
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      analyserRef.current?.disconnect()
      analyserRef.current = null
      try {
        ctxRef.current?.close()
      } catch {}
      ctxRef.current = null
      streamRef.current?.getTracks().forEach(t => t.stop())
      streamRef.current = null
      ampRef.current = 0
      setAmp(0)
    }
  }, [enabled])

  return amp
}
