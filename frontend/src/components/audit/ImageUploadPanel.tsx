import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'

import {
  listPlanograms,
  listStreamCameras,
  listStreamModels,
  setActivePlanogram,
  type StreamCamera,
  type StreamModel,
} from '@/api'
import type { Language, UI_TEXT } from '@/lib/i18n'
import type { AuditPanelState, AuditPipelineStep } from '@/types'
import type { Planogram } from '@/types/planogram'

import styles from './ImageUploadPanel.module.css'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const STEP_ORDER: AuditPipelineStep[] = ['vision', 'planogram', 'agent', 'tickets', 'done']

interface ImageUploadPanelProps {
  text: (typeof UI_TEXT)[Language]['audit']
  state: AuditPanelState
  isMonitoring: boolean
  onSelectImage: (file: File) => void
  onStartInference: (model: string) => Promise<void>
  onAnalyzeCameraCapture: (camera: string, model: string) => Promise<void>
  onStartMonitoring: (camera: string, model: string, intervalMs: number) => void
  onStopMonitoring: () => void
  onClear: () => void
}

function isAcceptedImage(file: File): boolean {
  return ACCEPTED_TYPES.includes(file.type) || /\.(jpe?g|png|webp|gif)$/i.test(file.name)
}

function stepLabel(text: ImageUploadPanelProps['text'], step: AuditPipelineStep): string {
  return text.stepLabels[step]
}

function stepStatusLabel(text: ImageUploadPanelProps['text'], status: string): string {
  if (status === 'running') return text.stepRunning
  if (status === 'done') return text.stepDone
  if (status === 'skipped') return text.stepSkipped
  if (status === 'error') return text.stepError
  return text.stepPending
}

export function ImageUploadPanel({
  text,
  state,
  isMonitoring,
  onSelectImage,
  onStartInference,
  onAnalyzeCameraCapture,
  onStartMonitoring,
  onStopMonitoring,
  onClear,
}: ImageUploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [cameras, setCameras] = useState<StreamCamera[]>([])
  const [models, setModels] = useState<StreamModel[]>([])
  const [planograms, setPlanograms] = useState<Planogram[]>([])
  const [selectedCamera, setSelectedCamera] = useState('0')
  const [selectedModel, setSelectedModel] = useState('')
  const [selectedPlanogramId, setSelectedPlanogramId] = useState('')
  const [intervalMs, setIntervalMs] = useState(60_000)
  const [planogramLoading, setPlanogramLoading] = useState(true)

  const isBusy = state.status === 'analyzing' || state.status === 'uploading'
  const suggestedAction = state.result?.suggestedAction ?? ''
  const explanation = state.result?.explanation ?? ''
  const planogramMatch = state.result?.planogramResponse ?? null
  const ticketIds = state.result?.ticketIds ?? []
  const closedLoopNarrative = state.result?.closedLoopNarrative ?? ''
  const steps = state.steps?.length
    ? state.steps
    : STEP_ORDER.map((id) => ({ id, status: 'pending' as const }))
  const completedCount = steps.filter((step) => step.status === 'done' || step.status === 'skipped').length
  const progressPercent = Math.max(8, Math.round((completedCount / steps.length) * 100))
  const activeStepLabel = state.activeStep
    ? stepLabel(text, state.activeStep)
    : isBusy
      ? text.progressCopy
      : text.progressTitle

  useEffect(() => {
    let cancelled = false

    async function loadControls(): Promise<void> {
      try {
        const [cameraResponse, modelResponse, planogramResponse] = await Promise.all([
          listStreamCameras(),
          listStreamModels(),
          listPlanograms(),
        ])
        if (cancelled) {
          return
        }

        setCameras(cameraResponse.cameras)
        setSelectedCamera(cameraResponse.defaultCamera || cameraResponse.cameras[0]?.id || '0')
        setModels(modelResponse.models)
        setSelectedModel(modelResponse.defaultModel || modelResponse.models[0]?.id || '')
        setPlanograms(planogramResponse.planograms)
        setSelectedPlanogramId(planogramResponse.activePlanogramId || planogramResponse.planograms[0]?.id || '')
      } catch (error) {
        if (!cancelled) {
          setLocalError(error instanceof Error ? error.message : text.controlsError)
        }
      } finally {
        if (!cancelled) {
          setPlanogramLoading(false)
        }
      }
    }

    void loadControls()

    return () => {
      cancelled = true
    }
  }, [text.controlsError])

  async function onPlanogramChange(planogramId: string): Promise<void> {
    setSelectedPlanogramId(planogramId)
    if (!planogramId) {
      return
    }
    try {
      await setActivePlanogram(planogramId)
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : text.controlsError)
    }
  }

  function handleFile(file: File | undefined): void {
    if (!file) {
      return
    }

    if (!isAcceptedImage(file)) {
      setLocalError(text.invalidImage)
      return
    }

    setLocalError(null)
    onSelectImage(file)
  }

  function onInputChange(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0]
    handleFile(file)
    event.target.value = ''
  }

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files?.[0]
    handleFile(file)
  }

  return (
    <section className={styles.panel} aria-labelledby="audit-panel-title">
      <header className={styles.header}>
        <h2 id="audit-panel-title" className={styles.title}>
          {text.title}
        </h2>
        <p className={styles.subtitle}>{text.subtitle}</p>
      </header>

      <section className={styles.controlPanel} aria-label={text.controlPanelLabel}>
        <label className={styles.field}>
          <span>{text.camera}</span>
          <select
            className={styles.select}
            value={selectedCamera}
            disabled={isBusy || isMonitoring}
            onChange={(event) => setSelectedCamera(event.target.value)}
          >
            {cameras.length > 0 ? (
              cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.label}
                </option>
              ))
            ) : (
              <option value={selectedCamera}>{`${text.cameraFallback} ${selectedCamera}`}</option>
            )}
          </select>
        </label>

        <label className={styles.field}>
          <span>{text.model}</span>
          <select
            className={styles.select}
            value={selectedModel}
            disabled={isBusy || isMonitoring}
            onChange={(event) => setSelectedModel(event.target.value)}
          >
            {models.length > 0 ? (
              models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                </option>
              ))
            ) : (
              <option value={selectedModel}>{selectedModel || text.defaultModel}</option>
            )}
          </select>
        </label>

        <label className={styles.field}>
          <span>{text.planogram}</span>
          <select
            className={styles.select}
            value={selectedPlanogramId}
            disabled={isBusy || isMonitoring || planogramLoading}
            onChange={(event) => void onPlanogramChange(event.target.value)}
          >
            {planogramLoading ? <option value="">{text.planogramLoading}</option> : null}
            {!planogramLoading && planograms.length === 0 ? <option value="">{text.planogramNone}</option> : null}
            {planograms.map((planogram) => (
              <option key={planogram.id} value={planogram.id}>
                {planogram.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>{text.interval}</span>
          <select
            className={styles.select}
            value={intervalMs}
            disabled={isBusy || isMonitoring}
            onChange={(event) => setIntervalMs(Number(event.target.value))}
          >
            {text.intervalOptions.map((label, index) => (
              <option key={label} value={[60_000, 120_000, 300_000, 600_000][index]}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <div className={styles.monitorActions}>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={isBusy || isMonitoring || !selectedModel}
            onClick={() => onStartMonitoring(selectedCamera, selectedModel, intervalMs)}
          >
            {text.startMonitoring}
          </button>
          <button
            type="button"
            className={styles.ghostButton}
            disabled={isBusy || !selectedModel}
            onClick={() => void onAnalyzeCameraCapture(selectedCamera, selectedModel)}
          >
            {text.analyzeNow}
          </button>
          <button type="button" className={styles.ghostButton} disabled={!isMonitoring} onClick={onStopMonitoring}>
            {text.stopMonitor}
          </button>
        </div>
      </section>

      <div
        className={`${styles.dropzone} ${isDragging ? styles.dropzoneActive : ''}`}
        onDragEnter={(event) => {
          event.preventDefault()
          setIsDragging(true)
        }}
        onDragOver={(event) => {
          event.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={(event) => {
          event.preventDefault()
          setIsDragging(false)
        }}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          className={styles.fileInput}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          aria-label={text.uploadImageLabel}
          disabled={isBusy}
          onChange={onInputChange}
        />
        <div>
          <p className={styles.dropTitle}>{text.dropTitle}</p>
          <p className={styles.dropHint}>{text.dropHint}</p>
        </div>
      </div>

      {state.previewUrl ? (
        <div className={styles.previewWrap}>
          <img className={styles.preview} src={state.previewUrl} alt={text.previewAlt} />
          <div className={styles.metaRow}>
            <p className={styles.fileName}>{state.fileName}</p>
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={isBusy || !selectedModel}
                onClick={() => void onStartInference(selectedModel)}
              >
                {isBusy ? text.running : text.startInference}
              </button>
              <button
                type="button"
                className={styles.ghostButton}
                disabled={isBusy}
                onClick={() => inputRef.current?.click()}
              >
                {text.replace}
              </button>
              <button type="button" className={styles.ghostButton} disabled={isBusy} onClick={onClear}>
                {text.clear}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {state.status === 'ready' ? (
        <p className={styles.statusLine}>{text.ready}</p>
      ) : null}
      {isMonitoring ? <p className={styles.statusLine}>{text.monitoring}</p> : null}
      {isBusy || state.status === 'success' ? (
        <div className={styles.progressPanel} role="status" aria-live="polite">
          <div className={styles.progressHeader}>
            <span>{text.progressTitle}</span>
            <span>{isBusy ? activeStepLabel : text.progressComplete}</span>
          </div>
          <div className={styles.progressTrack}>
            <span
              className={`${styles.progressBar} ${isBusy ? styles.progressBarAnimated : styles.progressBarSolid}`}
              style={isBusy ? undefined : { width: `${progressPercent}%`, transform: 'none' }}
            />
          </div>
          <ol className={styles.stepList}>
            {steps.map((step) => (
              <li
                key={step.id}
                className={`${styles.stepItem} ${styles[`step_${step.status}`] ?? ''}`}
              >
                <span className={styles.stepName}>{stepLabel(text, step.id)}</span>
                <span className={styles.stepStatus}>{stepStatusLabel(text, step.status)}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {localError ? <p className={styles.errorLine}>{localError}</p> : null}
      {state.errorMessage ? <p className={styles.errorLine}>{state.errorMessage}</p> : null}

      <div className={styles.results}>
        <article className={`${styles.box} ${styles.actionBox}`} aria-live="polite">
          <h3 className={styles.boxLabel}>{text.action}</h3>
          <p className={`${styles.boxBody} ${suggestedAction ? '' : styles.boxEmpty}`}>
            {suggestedAction || text.waiting}
          </p>
        </article>

        <article className={`${styles.box} ${styles.explanationBox}`} aria-live="polite">
          <h3 className={styles.boxLabel}>{text.explanation}</h3>
          <p className={`${styles.boxBody} ${explanation ? '' : styles.boxEmpty}`}>
            {explanation || text.waiting}
          </p>
        </article>

        <article className={`${styles.box} ${styles.planogramBox}`} aria-live="polite">
          <h3 className={styles.boxLabel}>{text.planogramMatch}</h3>
          {planogramMatch ? (
            <div className={styles.boxBody}>
              <p>{planogramMatch.summary}</p>
              {planogramMatch.missingItems.length > 0 ? (
                <>
                  <p className={styles.missingTitle}>{text.missingItems}</p>
                  <ul className={styles.missingList}>
                    {planogramMatch.missingItems.map((item) => (
                      <li key={`${item.slotId}-${item.sku || item.itemName}`}>
                        {`${item.itemName || item.sku || item.slotId}`}
                        {item.itemStock != null ? ` · stock ${item.itemStock}` : ''}
                        {item.itemPrice != null ? ` · $${item.itemPrice}` : ''}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          ) : (
            <p className={`${styles.boxBody} ${styles.boxEmpty}`}>{text.noMatchYet}</p>
          )}
        </article>

        <article className={`${styles.box} ${styles.explanationBox}`} aria-live="polite">
          <h3 className={styles.boxLabel}>{text.ticketsOpened}</h3>
          {ticketIds.length > 0 || closedLoopNarrative ? (
            <div className={styles.boxBody}>
              {closedLoopNarrative ? <p>{closedLoopNarrative}</p> : null}
              {ticketIds.length > 0 ? (
                <ul className={styles.missingList}>
                  {ticketIds.map((ticketId) => (
                    <li key={ticketId}>{ticketId}</li>
                  ))}
                </ul>
              ) : (
                <p>{text.noTickets}</p>
              )}
            </div>
          ) : (
            <p className={`${styles.boxBody} ${styles.boxEmpty}`}>{text.noTickets}</p>
          )}
        </article>
      </div>
    </section>
  )
}
