import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from 'react'

import {
  captureCameraSnapshot,
  listPlanograms,
  listStreamCameras,
  listStreamModels,
  type StreamCamera,
  type StreamModel,
} from '@/api'
import { useCameraStreams } from '@/hooks/useCameraStreams'
import type { MonitorSettings } from '@/hooks/useAuditAnalysis'
import { GlassSelect } from '@/components/ui/GlassSelect'
import type { Language, UI_TEXT } from '@/lib/i18n'
import type { AuditPanelState, AuditPipelineStep } from '@/types'
import type { Planogram } from '@/types/planogram'

import styles from './ImageUploadPanel.module.css'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const STEP_ORDER: AuditPipelineStep[] = ['vision', 'planogram', 'agent', 'tickets', 'done']
const INTERVAL_VALUES = [60_000, 120_000, 300_000, 600_000]

/** Per-camera UI config the operator can tune independently. */
interface CameraConfig {
  model: string
  intervalMs: number
  planogramId: string
}

interface AuditController {
  getState: (camera: string) => AuditPanelState
  isMonitoring: (camera: string) => boolean
  getMonitorSettings: (camera: string) => MonitorSettings | null
  selectImage: (camera: string, file: File) => void
  submitImage: (camera: string, model: string, language: Language, planogramId?: string | null) => Promise<void>
  submitCameraCapture: (
    camera: string,
    model: string,
    language: Language,
    planogramId?: string | null,
  ) => Promise<void>
  startMonitoring: (
    camera: string,
    model: string,
    intervalMs: number,
    language: Language,
    planogramId?: string | null,
  ) => void
  stopMonitoring: (camera: string) => void
  clearAudit: (camera: string) => void
}

interface ImageUploadPanelProps {
  text: (typeof UI_TEXT)[Language]['audit']
  language: Language
  audit: AuditController
  /** When false the current user is read-only (staff): can view cameras/streams
   *  but cannot run audits or start monitoring. */
  canWrite?: boolean
  /**
   * Capture a clean-plate still from the live camera and hand it to the
   * planogram editor as the shelf reference photo.
   */
  onCreatePlanogramFromCapture?: (payload: {
    imageBase64: string
    imageWidth: number
    imageHeight: number
    camera: string
  }) => void
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
  language,
  audit,
  canWrite = true,
  onCreatePlanogramFromCapture,
}: ImageUploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [cameras, setCameras] = useState<StreamCamera[]>([])
  const [models, setModels] = useState<StreamModel[]>([])
  const [planograms, setPlanograms] = useState<Planogram[]>([])
  // '' = camera grid view; a camera id = streaming detail view for that camera.
  const [openedCamera, setOpenedCamera] = useState('')
  // Detail-view viewer mode: 'stream' shows the live MJPEG feed; 'capture'
  // shows the latest analyzed still (upload preview or manual "Analyze now"
  // result). Defaults to 'stream' when opening a camera so an already-audited
  // camera still opens its live stream instead of freezing on its last capture.
  const [viewMode, setViewMode] = useState<'stream' | 'capture'>('stream')
  const [configs, setConfigs] = useState<Record<string, CameraConfig>>({})
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [defaultModel, setDefaultModel] = useState('')
  const [snapshotBusy, setSnapshotBusy] = useState(false)
  const [snapshotPreview, setSnapshotPreview] = useState<string | null>(null)

  const streams = useCameraStreams()
  // Track which camera is currently streaming so switching cameras (or leaving
  // the panel) tears down only that live stream — never the background audits.
  const streamingCameraRef = useRef('')

  function configFor(camera: string): CameraConfig {
    return configs[camera] ?? { model: defaultModel, intervalMs: 60_000, planogramId: '' }
  }

  const loadControls = useCallback(
    async (signal?: { cancelled: boolean }): Promise<void> => {
      const [cameraResponse, modelResponse, planogramResponse] = await Promise.all([
        listStreamCameras(),
        listStreamModels(),
        listPlanograms(),
      ])
      if (signal?.cancelled) {
        return
      }

      const model = modelResponse.defaultModel || modelResponse.models[0]?.id || ''
      const activePlanogram = planogramResponse.activePlanogramId || planogramResponse.planograms[0]?.id || ''
      setCameras(cameraResponse.cameras)
      setModels(modelResponse.models)
      setDefaultModel(model)
      setPlanograms(planogramResponse.planograms)

      setConfigs((current) => {
        const next = { ...current }
        for (const camera of cameraResponse.cameras) {
          if (!next[camera.id]) {
            next[camera.id] = { model, intervalMs: 60_000, planogramId: activePlanogram }
          }
        }
        return next
      })
    },
    [],
  )

  useEffect(() => {
    const signal = { cancelled: false }
    void loadControls(signal)
      .catch((error) => {
        if (!signal.cancelled) {
          setLocalError(error instanceof Error ? error.message : text.controlsError)
        }
      })
      .finally(() => {
        if (!signal.cancelled) {
          setLoading(false)
        }
      })
    return () => {
      signal.cancelled = true
    }
  }, [loadControls, text.controlsError])

  async function refreshCameras(): Promise<void> {
    setRefreshing(true)
    setLocalError(null)
    try {
      await loadControls()
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : text.controlsError)
    } finally {
      setRefreshing(false)
    }
  }

  const cameraList = useMemo(() => cameras, [cameras])

  // When the panel unmounts (operator leaves the audit page), stop the live
  // stream of the currently viewed camera. Background monitoring lives in the
  // App-level audit hook, so saved cameras keep auditing after we leave.
  useEffect(() => {
    return () => {
      const streaming = streamingCameraRef.current
      if (streaming) {
        void streams.stopCameraStream(streaming)
        streamingCameraRef.current = ''
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openCamera(cameraId: string): void {
    setOpenedCamera(cameraId)
    // Always open on the live stream, even if this camera already has a stored
    // capture from background auditing.
    setViewMode('stream')
    setSnapshotPreview(null)
    setLocalError(null)
    streamingCameraRef.current = cameraId
    const model = configFor(cameraId).model || defaultModel || undefined
    void streams.startCameraStream(cameraId, model)
  }

  async function takePhotoForPlanogram(camera: string): Promise<void> {
    if (!canWrite || !onCreatePlanogramFromCapture || snapshotBusy) {
      return
    }
    setSnapshotBusy(true)
    setLocalError(null)
    try {
      const snapshot = await captureCameraSnapshot(camera)
      if (!snapshot.imageBase64) {
        throw new Error(text.snapshotFailed)
      }
      setSnapshotPreview(snapshot.imageBase64)
      setViewMode('capture')
      onCreatePlanogramFromCapture({
        imageBase64: snapshot.imageBase64,
        imageWidth: snapshot.image.width,
        imageHeight: snapshot.image.height,
        camera,
      })
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : text.snapshotFailed)
    } finally {
      setSnapshotBusy(false)
    }
  }

  function closeCamera(): void {
    const streaming = streamingCameraRef.current
    if (streaming) {
      void streams.stopCameraStream(streaming)
      streamingCameraRef.current = ''
    }
    setOpenedCamera('')
  }

  function updateConfig(camera: string, patch: Partial<CameraConfig>): void {
    setConfigs((current) => {
      const base = current[camera] ?? { model: defaultModel, intervalMs: 60_000, planogramId: '' }
      return { ...current, [camera]: { ...base, ...patch } }
    })

    // If we change the model of the camera we're viewing live, restart its
    // stream so the overlay reflects the new weights immediately.
    if (patch.model && streamingCameraRef.current === camera) {
      void streams.stopCameraStream(camera).then(() => {
        streamingCameraRef.current = camera
        void streams.startCameraStream(camera, patch.model)
      })
    }

    // If the camera is already auditing in the background, re-save so the new
    // planogram / interval / model take effect on the next tick.
    if (audit.isMonitoring(camera)) {
      const nextConfig = { ...configFor(camera), ...patch }
      audit.startMonitoring(
        camera,
        nextConfig.model,
        nextConfig.intervalMs,
        language,
        nextConfig.planogramId || null,
      )
    }
  }

  function toggleAuditing(camera: string): void {
    if (audit.isMonitoring(camera)) {
      audit.stopMonitoring(camera)
      return
    }
    const config = configFor(camera)
    if (!config.model) {
      return
    }
    audit.startMonitoring(camera, config.model, config.intervalMs, language, config.planogramId || null)
  }

  function handleFile(file: File | undefined): void {
    if (!file || !openedCamera) {
      return
    }
    if (!isAcceptedImage(file)) {
      setLocalError(text.invalidImage)
      return
    }
    setLocalError(null)
    // Uploading a still switches the viewer to show that image.
    setViewMode('capture')
    audit.selectImage(openedCamera, file)
  }

  function onInputChange(event: ChangeEvent<HTMLInputElement>): void {
    handleFile(event.target.files?.[0])
    event.target.value = ''
  }

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    setIsDragging(false)
    handleFile(event.dataTransfer.files?.[0])
  }

  function streamStatusLabel(camera: string): string {
    const status = streams.getStreamState(camera).status
    if (status === 'live') return text.streamLive
    if (status === 'starting') return text.streamStarting
    if (status === 'error') return text.streamError
    return text.streamIdle
  }

  function cameraLabel(cameraId: string): string {
    const camera = cameraList.find((item) => item.id === cameraId)
    return camera?.label ?? (cameraId ? `${text.cameraFallback} ${cameraId}` : '')
  }

  function planogramName(planogramId: string): string {
    return planograms.find((item) => item.id === planogramId)?.name ?? text.planogramNone
  }

  // ----- Camera grid (default view) ---------------------------------------
  if (!openedCamera) {
    return (
      <section className={styles.panel} aria-labelledby="audit-panel-title">
        <header className={styles.headerRow}>
          <div className={styles.header}>
            <h2 id="audit-panel-title" className={styles.title}>
              {text.title}
            </h2>
            <p className={styles.subtitle}>{text.multiSubtitle}</p>
          </div>
          <button
            type="button"
            className={`${styles.ghostButton} glass-lens`}
            onClick={() => void refreshCameras()}
            disabled={refreshing || loading}
          >
            {refreshing ? text.refreshing : text.refreshCameras}
          </button>
        </header>

        {localError ? <p className={styles.errorLine}>{localError}</p> : null}

        {loading ? (
          <p className={styles.statusLine}>{text.controlsLoading}</p>
        ) : cameraList.length === 0 ? (
          <section className={styles.selectPrompt}>
            <p className={styles.selectPromptTitle}>{text.noCameras}</p>
            <p className={styles.selectPromptCopy}>{text.noCamerasCopy}</p>
          </section>
        ) : (
          <div className={styles.blockGrid}>
            {cameraList.map((camera) => {
              const cameraState = audit.getState(camera.id)
              const monitoring = audit.isMonitoring(camera.id)
              const config = configFor(camera.id)
              const cover = cameraState.previewUrl
              return (
                <article key={camera.id} className={styles.cameraBlock}>
                  <button
                    type="button"
                    className={styles.blockCover}
                    onClick={() => openCamera(camera.id)}
                    aria-label={`${text.openStream}: ${camera.label}`}
                  >
                    {cover ? (
                      <img className={styles.blockCoverImage} src={cover} alt={camera.label} />
                    ) : (
                      <div className={styles.blockCoverEmpty}>
                        <span>{text.noCapture}</span>
                      </div>
                    )}
                    <span
                      className={`${styles.blockStatus} ${monitoring ? styles.blockStatusActive : ''}`}
                    >
                      <span className={styles.streamDot} />
                      {monitoring ? text.statusAuditing : text.statusIdle}
                    </span>
                  </button>

                  <div className={styles.blockBody}>
                    <div className={styles.blockNameRow}>
                      <span className={styles.blockName}>{camera.name ?? camera.label}</span>
                      <span className={styles.blockId}>{`${text.cameraFallback} ${camera.id}`}</span>
                    </div>

                    <GlassSelect
                      label={text.planogram}
                      size="compact"
                      value={config.planogramId}
                      options={[
                        { value: '', label: text.planogramNone },
                        ...planograms.map((planogram) => ({
                          value: planogram.id,
                          label: planogram.name,
                        })),
                      ]}
                      onChange={(next) => updateConfig(camera.id, { planogramId: next })}
                    />

                    <GlassSelect
                      label={text.interval}
                      size="compact"
                      value={String(config.intervalMs)}
                      options={text.intervalOptions.map((label, index) => ({
                        value: String(INTERVAL_VALUES[index]),
                        label,
                      }))}
                      onChange={(next) => updateConfig(camera.id, { intervalMs: Number(next) })}
                    />

                    <div className={styles.blockActions}>
                      {canWrite ? (
                        <button
                          type="button"
                          className={monitoring ? styles.ghostButton : styles.primaryButton}
                          onClick={() => toggleAuditing(camera.id)}
                          disabled={!config.model}
                        >
                          {monitoring ? text.stopMonitor : text.startMonitoring}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className={`${styles.ghostButton} glass-lens`}
                        onClick={() => openCamera(camera.id)}
                      >
                        {text.openStream}
                      </button>
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>
    )
  }

  // ----- Streaming detail view (a camera is opened) -----------------------
  const camera = openedCamera
  const state = audit.getState(camera)
  const isBusy = state.status === 'analyzing' || state.status === 'uploading'
  const monitoringActive = audit.isMonitoring(camera)
  const streamState = streams.getStreamState(camera)
  const activeConfig = configFor(camera)
  // Only show the stored still when the operator is explicitly in capture mode
  // and there is a capture to show. Otherwise the live stream is displayed —
  // this is what lets an already-audited camera open its live feed.
  const showCapture =
    viewMode === 'capture' && Boolean(snapshotPreview || state.previewUrl)
  const captureImageSrc = snapshotPreview ?? state.previewUrl

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

  return (
    <section className={styles.panel} aria-labelledby="audit-panel-title">
      <header className={styles.headerRow}>
        <div className={styles.header}>
          <button type="button" className={`${styles.backButton} glass-lens`} onClick={closeCamera}>
            {text.backToCameras}
          </button>
          <h2 id="audit-panel-title" className={styles.title}>
            {cameraLabel(camera)}
          </h2>
          <p className={styles.subtitle}>{text.activeCameraHint}</p>
        </div>
        <div className={styles.headerControls}>
          {state.previewUrl || snapshotPreview ? (
            <div className={styles.viewToggle} role="group" aria-label={text.viewToggleLabel}>
              <button
                type="button"
                className={`${styles.viewToggleButton} ${showCapture ? '' : styles.viewToggleActive} glass-lens`}
                onClick={() => setViewMode('stream')}
                aria-pressed={!showCapture}
              >
                {text.viewLive}
              </button>
              <button
                type="button"
                className={`${styles.viewToggleButton} ${showCapture ? styles.viewToggleActive : ''} glass-lens`}
                onClick={() => setViewMode('capture')}
                aria-pressed={showCapture}
              >
                {text.viewCapture}
              </button>
            </div>
          ) : null}
          <div className={`${styles.streamBadge} ${streamState.status === 'live' ? styles.streamBadgeLive : ''}`}>
            <span className={styles.streamDot} />
            {showCapture ? text.viewingCapture : streamStatusLabel(camera)}
          </div>
        </div>
      </header>

      <section className={styles.activeCamera} aria-label={text.activeCameraLabel}>
        <div className={styles.activeViewer}>
          {showCapture && captureImageSrc ? (
            <img className={styles.activeImage} src={captureImageSrc} alt={text.previewAlt} />
          ) : streamState.status === 'live' || streamState.status === 'starting' ? (
            <img
              key={`active-${camera}-${streamState.reloadKey}`}
              className={styles.activeImage}
              src={streams.videoUrl(camera)}
              alt={cameraLabel(camera)}
              onLoad={() => streams.markLive(camera)}
              onError={() => streams.markError(camera, text.streamErrorDetail)}
            />
          ) : (
            <div className={styles.activePlaceholder}>
              <p className={styles.activePlaceholderTitle}>{text.streamOffline}</p>
              <p className={styles.activePlaceholderCopy}>{text.streamOfflineCopy}</p>
            </div>
          )}
          {!showCapture && streamState.status === 'starting' ? (
            <div className={styles.viewerOverlay} role="status" aria-live="polite">
              <div className={styles.spinner} />
              <span>{text.streamStarting}</span>
            </div>
          ) : null}
        </div>

        {streamState.status === 'error' && streamState.error ? (
          <p className={styles.errorLine}>{streamState.error}</p>
        ) : null}
      </section>

      <section className={styles.controlPanel} aria-label={text.controlPanelLabel}>
        {/* Row 1: model + planogram (equal tracks, minmax(0) so long EN/ZH labels ellipsize). */}
        <div className={styles.controlFieldsPrimary}>
          <GlassSelect
            className={styles.controlField}
            label={text.model}
            size="compact"
            value={activeConfig.model}
            disabled={isBusy}
            options={
              models.length > 0
                ? models.map((model) => ({ value: model.id, label: model.label }))
                : [{ value: activeConfig.model, label: activeConfig.model || text.defaultModel }]
            }
            onChange={(next) => updateConfig(camera, { model: next })}
          />

          <GlassSelect
            className={styles.controlField}
            label={text.planogram}
            size="compact"
            value={activeConfig.planogramId}
            disabled={isBusy}
            options={[
              { value: '', label: text.planogramNone },
              ...planograms.map((planogram) => ({
                value: planogram.id,
                label: planogram.name,
              })),
            ]}
            onChange={(next) => updateConfig(camera, { planogramId: next })}
          />
        </div>

        {/* Row 2: interval + action buttons. */}
        <div className={styles.controlFieldsSecondary}>
          <GlassSelect
            className={styles.controlFieldInterval}
            label={text.interval}
            size="compact"
            value={String(activeConfig.intervalMs)}
            disabled={isBusy}
            options={text.intervalOptions.map((label, index) => ({
              value: String(INTERVAL_VALUES[index]),
              label,
            }))}
            onChange={(next) => updateConfig(camera, { intervalMs: Number(next) })}
          />

          {canWrite ? (
            <div className={styles.monitorActions}>
              <button
                type="button"
                className={`${styles.primaryButton} glass-lens`}
                disabled={isBusy || !activeConfig.model}
                onClick={() =>
                  audit.startMonitoring(
                    camera,
                    activeConfig.model,
                    activeConfig.intervalMs,
                    language,
                    activeConfig.planogramId || null,
                  )
                }
              >
                {monitoringActive ? text.saveUpdate : text.save}
              </button>
              <button
                type="button"
                className={`${styles.ghostButton} glass-lens`}
                disabled={isBusy || !activeConfig.model}
                onClick={() => {
                  // Show the annotated result of this manual analysis.
                  setSnapshotPreview(null)
                  setViewMode('capture')
                  void audit.submitCameraCapture(camera, activeConfig.model, language, activeConfig.planogramId || null)
                }}
              >
                {text.analyzeNow}
              </button>
              {onCreatePlanogramFromCapture ? (
                <button
                  type="button"
                  className={`${styles.primaryButton} glass-lens`}
                  disabled={isBusy || snapshotBusy}
                  onClick={() => void takePhotoForPlanogram(camera)}
                >
                  {snapshotBusy ? text.takingPhoto : text.takePhotoForPlanogram}
                </button>
              ) : null}
              <button
                type="button"
                className={`${styles.ghostButton} glass-lens`}
                disabled={!monitoringActive}
                onClick={() => audit.stopMonitoring(camera)}
              >
                {text.stopMonitor}
              </button>
            </div>
          ) : null}
        </div>
      </section>

      {monitoringActive ? (
        <p className={styles.statusLine}>
          {text.savedHint}
          {activeConfig.planogramId ? ` · ${planogramName(activeConfig.planogramId)}` : ''}
        </p>
      ) : null}

      {canWrite ? (
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
      ) : null}

      {canWrite && state.previewUrl && state.fileName ? (
        <div className={styles.previewMeta}>
          <p className={styles.fileName}>{state.fileName}</p>
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.primaryButton} glass-lens`}
              disabled={isBusy || !activeConfig.model}
              onClick={() => {
                setViewMode('capture')
                void audit.submitImage(camera, activeConfig.model, language, activeConfig.planogramId || null)
              }}
            >
              {isBusy ? text.running : text.startInference}
            </button>
            <button type="button" className={`${styles.ghostButton} glass-lens`} disabled={isBusy} onClick={() => inputRef.current?.click()}>
              {text.replace}
            </button>
            <button
              type="button"
              className={`${styles.ghostButton} glass-lens`}
              disabled={isBusy}
              onClick={() => {
                audit.clearAudit(camera)
                setViewMode('stream')
              }}
            >
              {text.clear}
            </button>
          </div>
        </div>
      ) : null}

      {state.status === 'ready' ? <p className={styles.statusLine}>{text.ready}</p> : null}
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
              <li key={step.id} className={`${styles.stepItem} ${styles[`step_${step.status}`] ?? ''}`}>
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
          <p className={`${styles.boxBody} ${explanation ? '' : styles.boxEmpty}`}>{explanation || text.waiting}</p>
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
