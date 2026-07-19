import { useCallback, useEffect, useRef, useState } from 'react'

import { getStreamStatus, getStreamVideoUrl, startStream, stopStream } from '@/api'

export type CameraStreamStatus = 'idle' | 'starting' | 'live' | 'error'

interface CameraStreamState {
  status: CameraStreamStatus
  error: string | null
  reloadKey: number
}

const STATUS_POLL_MS = 1_500
const STATUS_POLL_MAX_MS = 15_000

function createInitial(): CameraStreamState {
  return { status: 'idle', error: null, reloadKey: 0 }
}

/**
 * Manage several concurrent camera streams from the browser.
 *
 * Each camera has an independent lifecycle so cameras keep streaming (and
 * therefore keep showing live bounding boxes) in the background while the
 * operator views a different one. Backend model-local runs one detection
 * worker per camera, so all started cameras stream at the same time.
 */
export function useCameraStreams() {
  const [states, setStates] = useState<Record<string, CameraStreamState>>({})
  const pollTimersRef = useRef<Map<string, number>>(new Map())
  const pollStartedAtRef = useRef<Map<string, number>>(new Map())
  const statusRef = useRef<Record<string, CameraStreamState>>({})

  useEffect(() => {
    statusRef.current = states
  }, [states])

  const patch = useCallback((camera: string, updater: (previous: CameraStreamState) => CameraStreamState) => {
    setStates((current) => {
      const previous = current[camera] ?? createInitial()
      return { ...current, [camera]: updater(previous) }
    })
  }, [])

  const clearPoll = useCallback((camera: string) => {
    const timer = pollTimersRef.current.get(camera)
    if (timer !== undefined) {
      window.clearTimeout(timer)
      pollTimersRef.current.delete(camera)
    }
    pollStartedAtRef.current.delete(camera)
  }, [])

  const startPoll = useCallback(
    (camera: string) => {
      clearPoll(camera)
      pollStartedAtRef.current.set(camera, Date.now())

      const tick = async (): Promise<void> => {
        if (statusRef.current[camera]?.status !== 'starting') {
          clearPoll(camera)
          return
        }

        try {
          const response = await getStreamStatus(camera)
          if (response.status === 'error') {
            patch(camera, (previous) => ({ ...previous, status: 'error', error: response.error ?? null }))
            clearPoll(camera)
            return
          }
          if (response.status === 'live' && response.hasFrame) {
            patch(camera, (previous) => (previous.status === 'starting' ? { ...previous, status: 'live' } : previous))
            clearPoll(camera)
            return
          }
          if (response.status === 'idle') {
            patch(camera, (previous) => ({ ...previous, status: 'error', error: null }))
            clearPoll(camera)
            return
          }
        } catch {
          // Transient network blips while the camera worker warms up — retry.
        }

        const startedAt = pollStartedAtRef.current.get(camera)
        if (startedAt !== undefined && Date.now() - startedAt > STATUS_POLL_MAX_MS) {
          patch(camera, (previous) => ({ ...previous, status: 'error', error: null }))
          clearPoll(camera)
          return
        }

        const nextTimer = window.setTimeout(() => {
          void tick()
        }, STATUS_POLL_MS)
        pollTimersRef.current.set(camera, nextTimer)
      }

      void tick()
    },
    [clearPoll, patch],
  )

  const startCameraStream = useCallback(
    async (camera: string, model?: string): Promise<void> => {
      // Already live or warming up — nothing to do.
      const current = statusRef.current[camera]?.status
      if (current === 'live' || current === 'starting') {
        return
      }

      patch(camera, (previous) => ({ ...previous, status: 'starting', error: null, reloadKey: previous.reloadKey + 1 }))
      try {
        const response = await startStream(camera, model)
        if (response.status === 'error') {
          patch(camera, (previous) => ({ ...previous, status: 'error', error: response.error ?? null }))
          return
        }
        startPoll(camera)
      } catch (error) {
        patch(camera, (previous) => ({
          ...previous,
          status: 'error',
          error: error instanceof Error ? error.message : null,
        }))
      }
    },
    [patch, startPoll],
  )

  const stopCameraStream = useCallback(
    async (camera: string): Promise<void> => {
      clearPoll(camera)
      patch(camera, (previous) => ({ ...previous, status: 'idle', error: null }))
      try {
        await stopStream(camera)
      } catch {
        // Keep the UI responsive even if the stream service is already closed.
      }
    },
    [clearPoll, patch],
  )

  const markLive = useCallback(
    (camera: string) => {
      clearPoll(camera)
      patch(camera, (previous) => (previous.status === 'live' ? previous : { ...previous, status: 'live' }))
    },
    [clearPoll, patch],
  )

  const markError = useCallback(
    (camera: string, error: string | null) => {
      patch(camera, (previous) => {
        // Ignore image errors while still starting — status poll owns that phase.
        if (previous.status === 'starting') {
          return previous
        }
        return { ...previous, status: 'error', error }
      })
    },
    [patch],
  )

  const getStreamState = useCallback(
    (camera: string): CameraStreamState => states[camera] ?? createInitial(),
    [states],
  )

  const videoUrl = useCallback((camera: string): string => {
    const state = statusRef.current[camera] ?? createInitial()
    return `${getStreamVideoUrl(camera)}&t=${state.reloadKey}`
  }, [])

  useEffect(() => {
    const timers = pollTimersRef.current
    return () => {
      for (const timer of timers.values()) {
        window.clearTimeout(timer)
      }
      timers.clear()
    }
  }, [])

  return {
    getStreamState,
    startCameraStream,
    stopCameraStream,
    markLive,
    markError,
    videoUrl,
  }
}
