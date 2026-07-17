import { useEffect, useRef, useState } from 'react'

import {
  analyzeShelfCameraCapture,
  analyzeShelfImage,
  type AuditProgressEvent,
} from '@/api/audit'
import type { Language } from '@/lib/i18n'
import {
  createInitialAuditSteps,
  type AuditPanelState,
  type AuditPipelineStep,
  type AuditStepState,
} from '@/types/audit'

const INITIAL_STATE: AuditPanelState = {
  status: 'idle',
  previewUrl: null,
  fileName: null,
  result: null,
  errorMessage: null,
  steps: createInitialAuditSteps(),
  activeStep: null,
}

/** Cap how far the monitor interval stretches after consecutive failures. */
const MAX_BACKOFF_MULTIPLIER = 8

function updateSteps(
  steps: AuditStepState[],
  step: AuditPipelineStep,
  status: AuditStepState['status'],
): AuditStepState[] {
  return steps.map((item) => (item.id === step ? { ...item, status } : item))
}

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

  function applyProgress(event: AuditProgressEvent): void {
    setState((previous) => {
      const nextSteps = updateSteps(
        previous.steps.length ? previous.steps : createInitialAuditSteps(),
        event.step,
        event.status === 'running'
          ? 'running'
          : event.status === 'done'
            ? 'done'
            : event.status === 'skipped'
              ? 'skipped'
              : 'error',
      )

      const partial = event.partial ?? {}
      const mergedResult = {
        ...(previous.result ?? {
          suggestedAction: '',
          explanation: '',
        }),
        ...partial,
      }

      let previewUrl = previous.previewUrl
      if (partial.annotatedImage) {
        if (previewUrlRef.current && previewUrlRef.current.startsWith('blob:')) {
          URL.revokeObjectURL(previewUrlRef.current)
          previewUrlRef.current = null
        }
        previewUrl = partial.annotatedImage
      }

      return {
        ...previous,
        status: event.step === 'done' && event.status === 'done' ? 'success' : 'analyzing',
        previewUrl,
        result: mergedResult,
        steps: nextSteps,
        activeStep: event.status === 'running' ? event.step : event.step === 'done' ? null : previous.activeStep,
        errorMessage: null,
      }
    })
  }

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
      steps: createInitialAuditSteps(),
      activeStep: null,
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
      steps: createInitialAuditSteps(),
      activeStep: 'vision',
    }))

    try {
      const result = await analyzeShelfImage(file, model, language, applyProgress)
      if (result.annotatedImage) {
        if (previewUrlRef.current && previewUrlRef.current.startsWith('blob:')) {
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
        activeStep: null,
        steps: previous.steps.map((step) =>
          step.status === 'pending' ? { ...step, status: 'done' } : step,
        ),
      }))
    } catch {
      const message = language === 'zh' ? '图片分析失败。' : 'Image analysis failed.'
      setState((previous) => ({
        ...previous,
        status: 'error',
        errorMessage: message,
        activeStep: null,
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
      steps: createInitialAuditSteps(),
      activeStep: 'vision',
    }))

    try {
      const result = await analyzeShelfCameraCapture(camera, model, language, applyProgress)
      setState((previous) => ({
        ...previous,
        status: 'success',
        previewUrl: result.annotatedImage ?? previous.previewUrl,
        fileName: language === 'zh' ? `摄像头 ${camera} 抓拍` : `Camera ${camera} capture`,
        result,
        errorMessage: null,
        activeStep: null,
        steps: previous.steps.map((step) =>
          step.status === 'pending' ? { ...step, status: 'done' } : step,
        ),
      }))
      failureStreakRef.current = 0
    } catch {
      failureStreakRef.current += 1
      const message = language === 'zh' ? '摄像头抓拍分析失败。' : 'Camera capture analysis failed.'
      setState((previous) => ({
        ...previous,
        status: 'error',
        errorMessage: message,
        activeStep: null,
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

    if (monitorRunningRef.current) {
      scheduleNextMonitorTick()
      return
    }

    await submitCameraCapture(params.camera, params.model, params.language)

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
