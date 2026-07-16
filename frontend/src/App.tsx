import { useState } from 'react'

import { ImageUploadPanel } from '@/components/audit/ImageUploadPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { DatabasePanel } from '@/components/database/DatabasePanel'
import { AppShell, type AppPage, type AppPageId } from '@/components/layout/AppShell'
import { StreamPanel } from '@/components/stream/StreamPanel'
import { useAgentChat } from '@/hooks/useAgentChat'
import { useAuditAnalysis } from '@/hooks/useAuditAnalysis'
import { UI_TEXT, type Language } from '@/lib/i18n'

function getInitialLanguage(): Language {
  const stored = window.localStorage.getItem('yolo-retail-language')
  return stored === 'zh' ? 'zh' : 'en'
}

function App() {
  const [activePageId, setActivePageId] = useState<AppPageId>('stream')
  const [language, setLanguage] = useState<Language>(getInitialLanguage)
  const audit = useAuditAnalysis()
  const chat = useAgentChat()
  const text = UI_TEXT[language]

  const pages: AppPage[] = [
    {
      id: 'stream',
      label: text.pages.stream[0],
      description: text.pages.stream[1],
    },
    {
      id: 'audit',
      label: text.pages.audit[0],
      description: text.pages.audit[1],
    },
    {
      id: 'chat',
      label: text.pages.chat[0],
      description: text.pages.chat[1],
    },
    {
      id: 'database',
      label: text.pages.database[0],
      description: text.pages.database[1],
    },
  ]

  function updateLanguage(nextLanguage: Language): void {
    setLanguage(nextLanguage)
    window.localStorage.setItem('yolo-retail-language', nextLanguage)
  }

  return (
    <AppShell
      pages={pages}
      activePageId={activePageId}
      onPageChange={setActivePageId}
      language={language}
      languageLabel={text.language}
      navigationLabel={text.shell.navLabel}
      tagline={text.brandTagline}
      onLanguageChange={updateLanguage}
    >
      {activePageId === 'stream' ? <StreamPanel text={text.stream} /> : null}

      {activePageId === 'audit' ? (
        <ImageUploadPanel
          text={text.audit}
          state={audit.state}
          isMonitoring={audit.isMonitoring}
          onSelectImage={audit.selectImage}
          onStartInference={(model) => audit.submitImage(model, language)}
          onAnalyzeCameraCapture={(camera, model) => audit.submitCameraCapture(camera, model, language)}
          onStartMonitoring={(camera, model, intervalMs) => audit.startMonitoring(camera, model, intervalMs, language)}
          onStopMonitoring={audit.stopMonitoring}
          onClear={audit.clearAudit}
        />
      ) : null}

      {activePageId === 'chat' ? (
        <ChatPanel
          text={text.chat}
          messages={chat.state.messages}
          status={chat.state.status}
          errorMessage={chat.state.errorMessage}
          onSendMessage={(content, attachments) => chat.sendMessage(content, attachments, language)}
        />
      ) : null}

      {activePageId === 'database' ? <DatabasePanel text={text.database} /> : null}
    </AppShell>
  )
}

export default App
