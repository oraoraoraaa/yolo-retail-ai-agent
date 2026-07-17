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

export function useAuditAnalysis() {
  const [state, setState] = useState<AuditPanelState>(INITIAL_STATE)
  const [isMonitoring, setIsMonitoring] = useState(false)
  const previewUrlRef = useRef<string | null>(null)
  const fileRef = useRef<File | null>(null)
  const monitorTimerRef = useRef<number | null>(null)
  const monitorRunningRef = useRef(false)

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
    } catch (error) {
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

  function startMonitoring(camera: string, model: string, intervalMs: number, language: Language): void {
    stopMonitoring()
    setIsMonitoring(true)
    void submitCameraCapture(camera, model, language)
    monitorTimerRef.current = window.setInterval(() => {
      void submitCameraCapture(camera, model, language)
    }, intervalMs)
  }

  function stopMonitoring(): void {
    if (monitorTimerRef.current !== null) {
      window.clearInterval(monitorTimerRef.current)
      monitorTimerRef.current = null
    }
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
