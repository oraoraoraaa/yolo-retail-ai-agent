import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'

import type { AuditPanelState } from '@/types'

import styles from './ImageUploadPanel.module.css'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']

interface ImageUploadPanelProps {
  state: AuditPanelState
  onSelectImage: (file: File) => void
  onStartInference: () => Promise<void>
  onClear: () => void
}

function isAcceptedImage(file: File): boolean {
  return ACCEPTED_TYPES.includes(file.type) || /\.(jpe?g|png|webp|gif)$/i.test(file.name)
}

export function ImageUploadPanel({ state, onSelectImage, onStartInference, onClear }: ImageUploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const isBusy = state.status === 'analyzing' || state.status === 'uploading'
  const suggestedAction = state.result?.suggestedAction ?? ''
  const explanation = state.result?.explanation ?? ''

  function handleFile(file: File | undefined): void {
    if (!file) {
      return
    }

    if (!isAcceptedImage(file)) {
      setLocalError('Please choose a JPEG, PNG, WebP, or GIF image.')
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
          Shelf image audit
        </h2>
        <p className={styles.subtitle}>
          Upload a local shelf photo. The backend will return a suggested action and an explanation.
        </p>
      </header>

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
          aria-label="Upload shelf image"
          disabled={isBusy}
          onChange={onInputChange}
        />
        <div>
          <p className={styles.dropTitle}>Drop an image here, or click to browse</p>
          <p className={styles.dropHint}>JPEG / PNG / WebP / GIF</p>
        </div>
      </div>

      {state.previewUrl ? (
        <div className={styles.previewWrap}>
          <img className={styles.preview} src={state.previewUrl} alt="Selected shelf preview" />
          <div className={styles.metaRow}>
            <p className={styles.fileName}>{state.fileName}</p>
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={isBusy}
                onClick={() => void onStartInference()}
              >
                {isBusy ? 'Running...' : 'Start inference'}
              </button>
              <button
                type="button"
                className={styles.ghostButton}
                disabled={isBusy}
                onClick={() => inputRef.current?.click()}
              >
                Replace
              </button>
              <button type="button" className={styles.ghostButton} disabled={isBusy} onClick={onClear}>
                Clear
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {state.status === 'ready' ? (
        <p className={styles.statusLine}>Image is ready. Click Start inference to run shelf detection.</p>
      ) : null}
      {isBusy ? (
        <div className={styles.progressPanel} role="status" aria-live="polite">
          <div className={styles.progressHeader}>
            <span>Running shelf detection</span>
            <span>Usually under 10 seconds</span>
          </div>
          <div className={styles.progressTrack}>
            <span className={styles.progressBar} />
          </div>
          <p className={styles.statusLine}>Uploading image, detecting products, and preparing analysis...</p>
        </div>
      ) : null}
      {localError ? <p className={styles.errorLine}>{localError}</p> : null}
      {state.errorMessage ? <p className={styles.errorLine}>{state.errorMessage}</p> : null}

      <div className={styles.results}>
        <article className={`${styles.box} ${styles.actionBox}`} aria-live="polite">
          <h3 className={styles.boxLabel}>Suggested action</h3>
          <p className={`${styles.boxBody} ${suggestedAction ? '' : styles.boxEmpty}`}>
            {suggestedAction || 'Waiting for backend response...'}
          </p>
        </article>

        <article className={`${styles.box} ${styles.explanationBox}`} aria-live="polite">
          <h3 className={styles.boxLabel}>Explanation</h3>
          <p className={`${styles.boxBody} ${explanation ? '' : styles.boxEmpty}`}>
            {explanation || 'Waiting for backend response...'}
          </p>
        </article>
      </div>
    </section>
  )
}
