import { useEffect, useMemo, useState } from 'react'

import { getStreamVideoUrl, listStreamCameras, startStream, stopStream, type StreamCamera } from '@/api'

import styles from './StreamPanel.module.css'

type StreamUiStatus = 'idle' | 'loading-cameras' | 'starting' | 'live' | 'error'

export function StreamPanel() {
  const [cameras, setCameras] = useState<StreamCamera[]>([])
  const [selectedCamera, setSelectedCamera] = useState('')
  const [status, setStatus] = useState<StreamUiStatus>('idle')
  const [errorMessage, setErrorMessage] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  const cacheBustedUrl = useMemo(() => {
    if (status === 'idle' || status === 'loading-cameras' || status === 'error') {
      return ''
    }

    return `${getStreamVideoUrl()}?t=${reloadKey}`
  }, [reloadKey, status])

  async function loadCameras(): Promise<string> {
    setStatus((currentStatus) => (currentStatus === 'live' ? currentStatus : 'loading-cameras'))
    setErrorMessage('')

    const response = await listStreamCameras()
    setCameras(response.cameras)
    const nextCamera = selectedCamera || response.defaultCamera || response.cameras[0]?.id || '0'
    setSelectedCamera(nextCamera)

    setStatus((currentStatus) => (currentStatus === 'loading-cameras' ? 'idle' : currentStatus))
    return nextCamera
  }

  useEffect(() => {
    let cancelled = false

    async function loadInitialCameras(): Promise<void> {
      try {
        const response = await listStreamCameras()
        if (cancelled) {
          return
        }

        setCameras(response.cameras)
        setSelectedCamera(response.defaultCamera || response.cameras[0]?.id || '0')
      } catch (error) {
        if (cancelled) {
          return
        }

        setStatus('error')
        setErrorMessage(error instanceof Error ? error.message : 'Could not reach the local stream service.')
      }
    }

    void loadInitialCameras()

    return () => {
      cancelled = true
    }
  }, [])

  async function connect(): Promise<void> {
    try {
      const camera = selectedCamera || (await loadCameras())
      setStatus('starting')
      setErrorMessage('')
      const response = await startStream(camera)
      if (response.status === 'error') {
        setStatus('error')
        setErrorMessage(response.error ?? 'The local stream service could not start the camera.')
        return
      }

      setReloadKey((value) => value + 1)
    } catch (error) {
      setStatus('error')
      setErrorMessage(error instanceof Error ? error.message : 'The local stream service could not start.')
    }
  }

  async function disconnect(): Promise<void> {
    try {
      await stopStream()
    } catch {
      // Keep the UI responsive even if the stream service is already closed.
    }
    setStatus('idle')
    setErrorMessage('')
  }

  const isLive = status === 'live'
  const isBusy = status === 'starting' || status === 'loading-cameras'
  const statusLabel =
    status === 'live'
      ? 'Live'
      : status === 'starting'
        ? 'Starting'
        : status === 'loading-cameras'
          ? 'Scanning'
          : status === 'error'
            ? 'Offline'
            : 'Ready'

  return (
    <section className={styles.panel} aria-labelledby="stream-panel-title">
      <header className={styles.header}>
        <div>
          <h2 id="stream-panel-title" className={styles.title}>
            Camera stream
          </h2>
          <p className={styles.subtitle}>
            Select a local camera and view YOLO bounding boxes directly in the browser.
          </p>
        </div>
        <div className={`${styles.statusBadge} ${isLive ? styles.statusLive : ''}`}>
          <span className={styles.statusDot} />
          {statusLabel}
        </div>
      </header>

      <div className={styles.toolbar}>
        <label className={styles.cameraLabel}>
          <span>Camera</span>
          <select
            className={styles.cameraSelect}
            value={selectedCamera}
            onChange={(event) => setSelectedCamera(event.target.value)}
            disabled={isBusy || isLive}
          >
            {cameras.length > 0 ? (
              cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.label}
                </option>
              ))
            ) : (
              <option value={selectedCamera || '0'}>{selectedCamera ? `Camera ${selectedCamera}` : 'Camera 0'}</option>
            )}
          </select>
        </label>
        <div className={styles.actions}>
          <button className={styles.primaryButton} type="button" disabled={isBusy || isLive} onClick={connect}>
            Start streaming
          </button>
          <button className={styles.ghostButton} type="button" disabled={isBusy || isLive} onClick={() => void loadCameras()}>
            Refresh cameras
          </button>
          <button className={styles.ghostButton} type="button" disabled={status === 'idle'} onClick={disconnect}>
            Stop
          </button>
        </div>
      </div>

      <div className={styles.viewer}>
        {cacheBustedUrl ? (
          <img
            key={reloadKey}
            className={styles.streamImage}
            src={cacheBustedUrl}
            alt="Real-time shelf detection stream"
            onLoad={() => setStatus('live')}
            onError={() => setStatus('error')}
          />
        ) : (
          <div className={styles.placeholder}>
            <p className={styles.placeholderTitle}>Stream not connected</p>
            <p className={styles.placeholderCopy}>
              Start <code>model-local/stream_server.py</code>, choose a camera, then start streaming.
            </p>
            {errorMessage ? <p className={styles.errorCopy}>{errorMessage}</p> : null}
          </div>
        )}

        {isBusy ? (
          <div className={styles.overlay} role="status" aria-live="polite">
            <div className={styles.spinner} />
            <span>{status === 'loading-cameras' ? 'Scanning cameras...' : 'Opening camera stream...'}</span>
          </div>
        ) : null}
      </div>

      <div className={styles.infoGrid}>
        <article className={styles.infoBox}>
          <h3>Local stream service</h3>
          <p>
            Run <code>uv run stream_server.py</code> in <code>model-local</code>. Configure{' '}
            <code>VITE_STREAM_BASE_URL</code> if it is not on <code>http://localhost:8001</code>.
          </p>
        </article>
        <article className={styles.infoBox}>
          <h3>Model overlay</h3>
          <p>
            Frames are read by OpenCV, annotated with the local ONNX YOLO model, and returned as an MJPEG browser stream.
          </p>
        </article>
      </div>
    </section>
  )
}
