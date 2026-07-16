import { useState } from 'react'

import { ImageUploadPanel } from '@/components/audit/ImageUploadPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { DatabasePanel } from '@/components/database/DatabasePanel'
import { AppShell, type AppPage, type AppPageId } from '@/components/layout/AppShell'
import { StreamPanel } from '@/components/stream/StreamPanel'
import { useAgentChat } from '@/hooks/useAgentChat'
import { useAuditAnalysis } from '@/hooks/useAuditAnalysis'

const PAGES: AppPage[] = [
  {
    id: 'stream',
    label: 'Camera Stream',
    description: 'Live shelf detection view',
  },
  {
    id: 'audit',
    label: 'Shelf Audit',
    description: 'Upload image and view analysis',
  },
  {
    id: 'chat',
    label: 'Agent Chat',
    description: 'Ask questions about retail ops',
  },
  {
    id: 'database',
    label: 'Database',
    description: 'Browse and query saved records',
  },
]

function App() {
  const [activePageId, setActivePageId] = useState<AppPageId>('stream')
  const audit = useAuditAnalysis()
  const chat = useAgentChat()

  return (
    <AppShell pages={PAGES} activePageId={activePageId} onPageChange={setActivePageId}>
      {activePageId === 'stream' ? <StreamPanel /> : null}

      {activePageId === 'audit' ? (
        <ImageUploadPanel
          state={audit.state}
          onSelectImage={audit.selectImage}
          onStartInference={audit.submitImage}
          onClear={audit.clearAudit}
        />
      ) : null}

      {activePageId === 'chat' ? (
        <ChatPanel
          messages={chat.state.messages}
          status={chat.state.status}
          errorMessage={chat.state.errorMessage}
          onSendMessage={chat.sendMessage}
        />
      ) : null}

      {activePageId === 'database' ? <DatabasePanel /> : null}
    </AppShell>
  )
}

export default App
