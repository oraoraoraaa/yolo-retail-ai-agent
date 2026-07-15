import { useEffect, useRef, useState } from 'react'

import { analyzeShelfImage } from '@/api'
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
  const previewUrlRef = useRef<string | null>(null)
  const fileRef = useRef<File | null>(null)

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current)
      }
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

  async function submitImage(): Promise<void> {
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
      const result = await analyzeShelfImage(file)
      setState((previous) => ({
        ...previous,
        status: 'success',
        result,
        errorMessage: null,
      }))
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Image analysis failed.'
      setState((previous) => ({
        ...previous,
        status: 'error',
        result: null,
        errorMessage: message,
      }))
    }
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
    selectImage,
    submitImage,
    clearAudit,
  }
}
