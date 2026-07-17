import { useEffect, useRef, useState } from 'react'

import { analyzeShelfCameraCapture, analyzeShelfImage } from '@/api'
import type { Language } from '@/lib/i18n'
import type { AuditPanelState } from '@/types'

const INITIAL_STATE: AuditPanelState = {
  status: 'idle',
  previewUrl: null,
  fileName: null,
  result: null,
  errorMessage: null,
}

/** Cap how far the monitor interval stretches after consecutive failures. */
const MAX_BACKOFF_MULTIPLIER = 8

export function useAuditAnalysis() {
  const [state, setState] = useState<AuditPanelState>(INITIAL_STATE)
  const [isMonitoring, setIsMonitoring] = useState(false)
  const previewUrlRef = useRef<string | null>(null)
  const fileRef = useRef<File | null>(null)
  const monitorTimerRef = useRef<number | null>(null)
  const monitorRunningRef = useRef(false)
  const monitorParamsRef = useRef<{
    camera: string
    model: string
    language: Language
    baseIntervalMs: number
  } | null>(null)
  const failureStreakRef = useRef(0)

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current)
      }
      stopMonitoring()
    }
  }, [])

  function selectImage(file: File): void {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current)
    }

    const previewUrl = URL.createObjectURL(file)
    previewUrlRef.current = previewUrl
    fileRef.current = file

    setState({
      status: 'ready',
      previewUrl,
      fileName: file.name,
      result: null,
      errorMessage: null,
    })
  }

  async function submitImage(model: string, language: Language): Promise<void> {
    const file = fileRef.current
    if (!file) {
      setState((previous) => ({
        ...previous,
        status: 'error',
        errorMessage: 'Please choose an image before starting inference.',
      }))
      return
    }

    setState((previous) => ({
      ...previous,
      status: 'analyzing',
      result: null,
      errorMessage: null,
    }))

    try {
      const result = await analyzeShelfImage(file, model, language)
      // Prefer the detector's annotated frame (boxes drawn) over the original upload preview.
      if (result.annotatedImage) {
        if (previewUrlRef.current) {
          URL.revokeObjectURL(previewUrlRef.current)
          previewUrlRef.current = null
        }
      }
      setState((previous) => ({
        ...previous,
        status: 'success',
        previewUrl: result.annotatedImage ?? previous.previewUrl,
        result,
        errorMessage: null,
      }))
    } catch (error) {
      const message = language === 'zh' ? '图片分析失败。' : 'Image analysis failed.'
      setState((previous) => ({
        ...previous,
        status: 'error',
        result: null,
        errorMessage: message,
      }))
    }
  }

  async function submitCameraCapture(camera: string, model: string, language: Language): Promise<void> {
    if (monitorRunningRef.current) {
      return
    }

    monitorRunningRef.current = true
    setState((previous) => ({
      ...previous,
      status: 'analyzing',
      fileName: language === 'zh' ? `摄像头 ${camera} 抓拍` : `Camera ${camera} capture`,
      result: null,
      errorMessage: null,
    }))

    try {
      const result = await analyzeShelfCameraCapture(camera, model, language)
      setState((previous) => ({
        ...previous,
        status: 'success',
        previewUrl: result.annotatedImage ?? previous.previewUrl,
        fileName: language === 'zh' ? `摄像头 ${camera} 抓拍` : `Camera ${camera} capture`,
        result,
        errorMessage: null,
      }))
      failureStreakRef.current = 0
    } catch (error) {
      failureStreakRef.current += 1
      const message = language === 'zh' ? '摄像头抓拍分析失败。' : 'Camera capture analysis failed.'
      setState((previous) => ({
        ...previous,
        status: 'error',
        result: null,
        errorMessage: message,
      }))
    } finally {
      monitorRunningRef.current = false
    }
  }

  function clearMonitorTimer(): void {
    if (monitorTimerRef.current !== null) {
      window.clearTimeout(monitorTimerRef.current)
      monitorTimerRef.current = null
    }
  }

  function scheduleNextMonitorTick(): void {
    const params = monitorParamsRef.current
    if (!params) {
      return
    }

    const multiplier = Math.min(
      MAX_BACKOFF_MULTIPLIER,
      2 ** Math.max(0, failureStreakRef.current),
    )
    const delay = Math.max(1_000, params.baseIntervalMs * multiplier)

    clearMonitorTimer()
    monitorTimerRef.current = window.setTimeout(() => {
      void runMonitorTick()
    }, delay)
  }

  async function runMonitorTick(): Promise<void> {
    const params = monitorParamsRef.current
    if (!params) {
      return
    }

    // Skip scheduling another tick if a previous capture is still in flight;
    // the finally path of submitCameraCapture + scheduleNextMonitorTick keeps
    // the loop alive without stacking overlapping work.
    if (monitorRunningRef.current) {
      scheduleNextMonitorTick()
      return
    }

    await submitCameraCapture(params.camera, params.model, params.language)

    // Only reschedule when monitoring is still active (stop may have been
    // called during the await).
    if (monitorParamsRef.current) {
      scheduleNextMonitorTick()
    }
  }

  function startMonitoring(camera: string, model: string, intervalMs: number, language: Language): void {
    stopMonitoring()
    monitorParamsRef.current = {
      camera,
      model,
      language,
      baseIntervalMs: Math.max(1_000, intervalMs),
    }
    failureStreakRef.current = 0
    setIsMonitoring(true)
    void runMonitorTick()
  }

  function stopMonitoring(): void {
    clearMonitorTimer()
    monitorParamsRef.current = null
    failureStreakRef.current = 0
    setIsMonitoring(false)
  }

  function clearAudit(): void {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current)
      previewUrlRef.current = null
    }
    fileRef.current = null
    setState(INITIAL_STATE)
  }

  return {
    state,
    isMonitoring,
    selectImage,
    submitImage,
    submitCameraCapture,
    startMonitoring,
    stopMonitoring,
    clearAudit,
  }
}
