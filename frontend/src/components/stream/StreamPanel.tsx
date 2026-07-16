import { useMemo, useState, type FormEvent } from 'react'

import { getApiBaseUrl } from '@/api'

import styles from './StreamPanel.module.css'

const DEFAULT_STREAM_PATH = '/api/v1/stream/video'

function getDefaultStreamUrl(): string {
  const configuredUrl = import.meta.env.VITE_STREAM_URL as string | undefined
  if (configuredUrl) {
    return configuredUrl
  }

  const apiBaseUrl = getApiBaseUrl()
  return `${apiBaseUrl}${DEFAULT_STREAM_PATH}`
}

export function StreamPanel() {
  const [streamUrl, setStreamUrl] = useState(getDefaultStreamUrl)
  const [draftUrl, setDraftUrl] = useState(getDefaultStreamUrl)
  const [status, setStatus] = useState<'idle' | 'connecting' | 'live' | 'error'>('idle')
  const [reloadKey, setReloadKey] = useState(0)

  const cacheBustedUrl = useMemo(() => {
    if (status === 'idle') {
      return ''
    }

    const separator = streamUrl.includes('?') ? '&' : '?'
    return `${streamUrl}${separator}t=${reloadKey}`
  }, [reloadKey, status, streamUrl])

  function connect(event?: FormEvent): void {
    event?.preventDefault()
    const nextUrl = draftUrl.trim()
    if (!nextUrl) {
      setStatus('error')
      return
    }

    setStreamUrl(nextUrl)
    setStatus('connecting')
    setReloadKey((value) => value + 1)
  }

  function disconnect(): void {
    setStatus('idle')
  }

  function reconnect(): void {
    setStatus('connecting')
    setReloadKey((value) => value + 1)
  }

  const isLive = status === 'live'
  const isConnecting = status === 'connecting'

  return (
    <section className={styles.panel} aria-labelledby="stream-panel-title">
      <header className={styles.header}>
        <div>
          <h2 id="stream-panel-title" className={styles.title}>
            Camera stream
          </h2>
          <p className={styles.subtitle}>
            View the real-time shelf camera stream and model overlay from the backend.
          </p>
        </div>
        <div className={`${styles.statusBadge} ${isLive ? styles.statusLive : ''}`}>
          <span className={styles.statusDot} />
          {isLive ? 'Live' : isConnecting ? 'Connecting' : status === 'error' ? 'Offline' : 'Ready'}
        </div>
      </header>

      <form className={styles.toolbar} onSubmit={connect}>
        <label className={styles.urlLabel}>
          <span>Stream URL</span>
          <input
            className={styles.urlInput}
            value={draftUrl}
            onChange={(event) => setDraftUrl(event.target.value)}
            placeholder="/api/v1/stream/video"
          />
        </label>
        <div className={styles.actions}>
          <button className={styles.primaryButton} type="submit">
            {status === 'idle' ? 'Connect' : 'Apply URL'}
          </button>
          <button className={styles.ghostButton} type="button" disabled={status === 'idle'} onClick={reconnect}>
            Reconnect
          </button>
          <button className={styles.ghostButton} type="button" disabled={status === 'idle'} onClick={disconnect}>
            Stop
          </button>
        </div>
      </form>

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
              Start the backend stream service, then connect to the MJPEG/video endpoint.
            </p>
          </div>
        )}

        {isConnecting ? (
          <div className={styles.overlay} role="status" aria-live="polite">
            <div className={styles.spinner} />
            <span>Opening camera stream...</span>
          </div>
        ) : null}
      </div>

      <div className={styles.infoGrid}>
        <article className={styles.infoBox}>
          <h3>Backend endpoint</h3>
          <p>
            Default frontend target is <code>{DEFAULT_STREAM_PATH}</code>. Configure <code>VITE_STREAM_URL</code> if the
            stream service uses another URL.
          </p>
        </article>
        <article className={styles.infoBox}>
          <h3>Runtime note</h3>
          <p>
            The current Roboflow script opens an OpenCV window locally. To display here, expose annotated frames as an
            HTTP MJPEG stream from the backend.
          </p>
        </article>
      </div>
    </section>
  )
}
