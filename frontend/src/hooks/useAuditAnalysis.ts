import { useCallback, useEffect, useRef, useState } from 'react'

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

function createInitialState(): AuditPanelState {
  return {
    status: 'idle',
    previewUrl: null,
    fileName: null,
    result: null,
    errorMessage: null,
    steps: createInitialAuditSteps(),
    activeStep: null,
  }
}

/** Cap how far the monitor interval stretches after consecutive failures. */
const MAX_BACKOFF_MULTIPLIER = 8

/** Mutable per-camera monitoring bookkeeping kept outside of React state. */
interface CameraRuntime {
  previewUrl: string | null
  file: File | null
  monitorTimer: number | null
  monitorRunning: boolean
  monitorParams: {
    model: string
    language: Language
    baseIntervalMs: number
    planogramId: string | null
  } | null
  failureStreak: number
}

/** Snapshot of a camera's saved background-monitoring config for the UI. */
export interface MonitorSettings {
  model: string
  intervalMs: number
  planogramId: string | null
}

function updateSteps(
  steps: AuditStepState[],
  step: AuditPipelineStep,
  status: AuditStepState['status'],
): AuditStepState[] {
  return steps.map((item) => (item.id === step ? { ...item, status } : item))
}

/**
 * Multi-camera shelf audit controller.
 *
 * Every camera keeps an independent audit state slot plus its own monitoring
 * timer, so cameras keep auditing in the background when the operator switches
 * the active (viewed) camera. The audit controls in the UI always target the
 * camera id passed to each action, never a single global camera.
 */
export function useAuditAnalysis() {
  const [states, setStates] = useState<Record<string, AuditPanelState>>({})
  const [monitoring, setMonitoring] = useState<Record<string, boolean>>({})
  const runtimeRef = useRef<Map<string, CameraRuntime>>(new Map())

  function getRuntime(camera: string): CameraRuntime {
    let runtime = runtimeRef.current.get(camera)
    if (!runtime) {
      runtime = {
        previewUrl: null,
        file: null,
        monitorTimer: null,
        monitorRunning: false,
        monitorParams: null,
        failureStreak: 0,
      }
      runtimeRef.current.set(camera, runtime)
    }
    return runtime
  }

  function patchState(camera: string, updater: (previous: AuditPanelState) => AuditPanelState): void {
    setStates((current) => {
      const previous = current[camera] ?? createInitialState()
      return { ...current, [camera]: updater(previous) }
    })
  }

  const getState = useCallback(
    (camera: string): AuditPanelState => states[camera] ?? createInitialState(),
    [states],
  )

  const isMonitoring = useCallback((camera: string): boolean => monitoring[camera] ?? false, [monitoring])

  function applyProgress(camera: string, event: AuditProgressEvent): void {
    patchState(camera, (previous) => {
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
        const runtime = getRuntime(camera)
        if (runtime.previewUrl && runtime.previewUrl.startsWith('blob:')) {
          URL.revokeObjectURL(runtime.previewUrl)
          runtime.previewUrl = null
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

  function selectImage(camera: string, file: File): void {
    const runtime = getRuntime(camera)
    if (runtime.previewUrl) {
      URL.revokeObjectURL(runtime.previewUrl)
    }

    const previewUrl = URL.createObjectURL(file)
    runtime.previewUrl = previewUrl
    runtime.file = file

    patchState(camera, () => ({
      status: 'ready',
      previewUrl,
      fileName: file.name,
      result: null,
      errorMessage: null,
      steps: createInitialAuditSteps(),
      activeStep: null,
    }))
  }

  async function submitImage(
    camera: string,
    model: string,
    language: Language,
    planogramId?: string | null,
  ): Promise<void> {
    const runtime = getRuntime(camera)
    const file = runtime.file
    if (!file) {
      patchState(camera, (previous) => ({
        ...previous,
        status: 'error',
        errorMessage:
          language === 'zh' ? '开始推理前请先选择图片。' : 'Please choose an image before starting inference.',
      }))
      return
    }

    patchState(camera, (previous) => ({
      ...previous,
      status: 'analyzing',
      result: null,
      errorMessage: null,
      steps: createInitialAuditSteps(),
      activeStep: 'vision',
    }))

    try {
      const result = await analyzeShelfImage(
        file,
        model,
        language,
        (event) => applyProgress(camera, event),
        planogramId,
      )
      if (result.annotatedImage && runtime.previewUrl && runtime.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(runtime.previewUrl)
        runtime.previewUrl = null
      }
      patchState(camera, (previous) => ({
        ...previous,
        status: 'success',
        previewUrl: result.annotatedImage ?? previous.previewUrl,
        result,
        errorMessage: null,
        activeStep: null,
        steps: previous.steps.map((step) => (step.status === 'pending' ? { ...step, status: 'done' } : step)),
      }))
    } catch {
      const message = language === 'zh' ? '图片分析失败。' : 'Image analysis failed.'
      patchState(camera, (previous) => ({
        ...previous,
        status: 'error',
        errorMessage: message,
        activeStep: null,
      }))
    }
  }

  async function submitCameraCapture(
    camera: string,
    model: string,
    language: Language,
    planogramId?: string | null,
  ): Promise<void> {
    const runtime = getRuntime(camera)
    if (runtime.monitorRunning) {
      return
    }

    runtime.monitorRunning = true
    patchState(camera, (previous) => ({
      ...previous,
      status: 'analyzing',
      fileName: language === 'zh' ? `摄像头 ${camera} 抓拍` : `Camera ${camera} capture`,
      result: null,
      errorMessage: null,
      steps: createInitialAuditSteps(),
      activeStep: 'vision',
    }))

    try {
      const result = await analyzeShelfCameraCapture(
        camera,
        model,
        language,
        (event) => applyProgress(camera, event),
        planogramId,
      )
      patchState(camera, (previous) => ({
        ...previous,
        status: 'success',
        previewUrl: result.annotatedImage ?? previous.previewUrl,
        fileName: language === 'zh' ? `摄像头 ${camera} 抓拍` : `Camera ${camera} capture`,
        result,
        errorMessage: null,
        activeStep: null,
        steps: previous.steps.map((step) => (step.status === 'pending' ? { ...step, status: 'done' } : step)),
      }))
      runtime.failureStreak = 0
    } catch {
      runtime.failureStreak += 1
      const message = language === 'zh' ? '摄像头抓拍分析失败。' : 'Camera capture analysis failed.'
      patchState(camera, (previous) => ({
        ...previous,
        status: 'error',
        errorMessage: message,
        activeStep: null,
      }))
    } finally {
      runtime.monitorRunning = false
    }
  }

  function clearMonitorTimer(camera: string): void {
    const runtime = getRuntime(camera)
    if (runtime.monitorTimer !== null) {
      window.clearTimeout(runtime.monitorTimer)
      runtime.monitorTimer = null
    }
  }

  function scheduleNextMonitorTick(camera: string): void {
    const runtime = getRuntime(camera)
    const params = runtime.monitorParams
    if (!params) {
      return
    }

    const multiplier = Math.min(MAX_BACKOFF_MULTIPLIER, 2 ** Math.max(0, runtime.failureStreak))
    const delay = Math.max(1_000, params.baseIntervalMs * multiplier)

    clearMonitorTimer(camera)
    runtime.monitorTimer = window.setTimeout(() => {
      void runMonitorTick(camera)
    }, delay)
  }

  async function runMonitorTick(camera: string): Promise<void> {
    const runtime = getRuntime(camera)
    const params = runtime.monitorParams
    if (!params) {
      return
    }

    if (runtime.monitorRunning) {
      scheduleNextMonitorTick(camera)
      return
    }

    await submitCameraCapture(camera, params.model, params.language, params.planogramId)

    if (runtime.monitorParams) {
      scheduleNextMonitorTick(camera)
    }
  }

  function startMonitoring(
    camera: string,
    model: string,
    intervalMs: number,
    language: Language,
    planogramId?: string | null,
  ): void {
    stopMonitoring(camera)
    const runtime = getRuntime(camera)
    runtime.monitorParams = {
      model,
      language,
      baseIntervalMs: Math.max(1_000, intervalMs),
      planogramId: planogramId ?? null,
    }
    runtime.failureStreak = 0
    setMonitoring((current) => ({ ...current, [camera]: true }))
    void runMonitorTick(camera)
  }

  /** Read a camera's saved background-monitoring settings, if any. */
  const getMonitorSettings = useCallback((camera: string): MonitorSettings | null => {
    const runtime = runtimeRef.current.get(camera)
    if (!runtime?.monitorParams) {
      return null
    }
    return {
      model: runtime.monitorParams.model,
      intervalMs: runtime.monitorParams.baseIntervalMs,
      planogramId: runtime.monitorParams.planogramId,
    }
  }, [])

  function stopMonitoring(camera: string): void {
    clearMonitorTimer(camera)
    const runtime = getRuntime(camera)
    runtime.monitorParams = null
    runtime.failureStreak = 0
    setMonitoring((current) => {
      if (!current[camera]) {
        return current
      }
      return { ...current, [camera]: false }
    })
  }

  function stopAllMonitoring(): void {
    for (const camera of runtimeRef.current.keys()) {
      stopMonitoring(camera)
    }
  }

  function clearAudit(camera: string): void {
    const runtime = getRuntime(camera)
    if (runtime.previewUrl) {
      URL.revokeObjectURL(runtime.previewUrl)
      runtime.previewUrl = null
    }
    runtime.file = null
    patchState(camera, () => createInitialState())
  }

  useEffect(() => {
    const runtimes = runtimeRef.current
    return () => {
      for (const runtime of runtimes.values()) {
        if (runtime.previewUrl) {
          URL.revokeObjectURL(runtime.previewUrl)
        }
        if (runtime.monitorTimer !== null) {
          window.clearTimeout(runtime.monitorTimer)
        }
        runtime.monitorParams = null
      }
    }
  }, [])

  return {
    getState,
    isMonitoring,
    getMonitorSettings,
    selectImage,
    submitImage,
    submitCameraCapture,
    startMonitoring,
    stopMonitoring,
    stopAllMonitoring,
    clearAudit,
  }
}
