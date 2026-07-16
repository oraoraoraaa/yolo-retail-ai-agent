import { useEffect, useMemo, useState } from 'react'

import { getStreamVideoUrl, listStreamCameras, startStream, stopStream, type StreamCamera } from '@/api'
import type { Language, UI_TEXT } from '@/lib/i18n'

import styles from './StreamPanel.module.css'

type StreamUiStatus = 'idle' | 'loading-cameras' | 'starting' | 'live' | 'error'

interface StreamPanelProps {
  text: (typeof UI_TEXT)[Language]['stream']
}

export function StreamPanel({ text }: StreamPanelProps) {
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
        setErrorMessage(text.errors.reachService)
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
        setErrorMessage(response.error ?? text.errors.startCamera)
        return
      }

      setReloadKey((value) => value + 1)
    } catch (error) {
      setStatus('error')
      setErrorMessage(text.errors.start)
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
      ? text.statuses.live
      : status === 'starting'
        ? text.statuses.starting
        : status === 'loading-cameras'
          ? text.statuses.loading
          : status === 'error'
            ? text.statuses.error
            : text.statuses.ready

  return (
    <section className={styles.panel} aria-labelledby="stream-panel-title">
      <header className={styles.header}>
        <div>
          <h2 id="stream-panel-title" className={styles.title}>
            {text.title}
          </h2>
          <p className={styles.subtitle}>{text.subtitle}</p>
        </div>
        <div className={`${styles.statusBadge} ${isLive ? styles.statusLive : ''}`}>
          <span className={styles.statusDot} />
          {statusLabel}
        </div>
      </header>

      <div className={styles.toolbar}>
        <label className={styles.cameraLabel}>
          <span>{text.camera}</span>
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
              <option value={selectedCamera || '0'}>
                {selectedCamera ? `${text.cameraFallback} ${selectedCamera}` : `${text.cameraFallback} 0`}
              </option>
            )}
          </select>
        </label>
        <div className={styles.actions}>
          <button className={styles.primaryButton} type="button" disabled={isBusy || isLive} onClick={connect}>
            {text.start}
          </button>
          <button className={styles.ghostButton} type="button" disabled={isBusy || isLive} onClick={() => void loadCameras()}>
            {text.refresh}
          </button>
          <button className={styles.ghostButton} type="button" disabled={status === 'idle'} onClick={disconnect}>
            {text.stop}
          </button>
        </div>
      </div>

      <div className={styles.viewer}>
        {cacheBustedUrl ? (
          <img
            key={reloadKey}
            className={styles.streamImage}
            src={cacheBustedUrl}
            alt={text.title}
            onLoad={() => setStatus('live')}
            onError={() => setStatus('error')}
          />
        ) : (
          <div className={styles.placeholder}>
            <p className={styles.placeholderTitle}>{text.disconnected}</p>
            <p className={styles.placeholderCopy}>{text.startService}</p>
            {errorMessage ? <p className={styles.errorCopy}>{errorMessage}</p> : null}
          </div>
        )}

        {isBusy ? (
          <div className={styles.overlay} role="status" aria-live="polite">
            <div className={styles.spinner} />
            <span>{status === 'loading-cameras' ? text.scanning : text.opening}</span>
          </div>
        ) : null}
      </div>

      <div className={styles.infoGrid}>
        <article className={styles.infoBox}>
          <h3>{text.service}</h3>
          <p>{text.serviceCopy}</p>
        </article>
        <article className={styles.infoBox}>
          <h3>{text.overlay}</h3>
          <p>{text.overlayCopy}</p>
        </article>
      </div>
    </section>
  )
}
