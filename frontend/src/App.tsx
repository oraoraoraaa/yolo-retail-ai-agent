import { useEffect, useMemo, useState } from 'react'

import { AccountsPanel } from '@/components/accounts/AccountsPanel'
import { LoginPanel } from '@/components/auth/LoginPanel'
import { ImageUploadPanel } from '@/components/audit/ImageUploadPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { DatabasePanel } from '@/components/database/DatabasePanel'
import { AppShell, type AppPage, type AppPageId } from '@/components/layout/AppShell'
import { PlanogramPanel } from '@/components/planogram/PlanogramPanel'
import { TicketBoardPanel } from '@/components/tickets/TicketBoardPanel'
import { useAgentChat } from '@/hooks/useAgentChat'
import { useAuditAnalysis } from '@/hooks/useAuditAnalysis'
import { useAuth } from '@/hooks/useAuth'
import { UI_TEXT, type Language } from '@/lib/i18n'

function getInitialLanguage(): Language {
  const stored = window.localStorage.getItem('yolo-retail-language')
  return stored === 'zh' ? 'zh' : 'en'
}

function App() {
  const [activePageId, setActivePageId] = useState<AppPageId>('audit')
  const [language, setLanguage] = useState<Language>(getInitialLanguage)
  const auth = useAuth()
  const audit = useAuditAnalysis()
  const chat = useAgentChat()
  const text = UI_TEXT[language]

  // Owner + admin may make changes; staff is read-only. When auth is disabled
  // (local/offline dev) everyone is treated as an owner.
  const canWrite = !auth.authEnabled || auth.canWrite
  const canViewAccounts = !auth.authEnabled || auth.canViewAccounts
  const canManageAccounts = !auth.authEnabled || auth.canManageAccounts

  const pages: AppPage[] = useMemo(() => {
    const base: AppPage[] = [
      { id: 'audit', label: text.pages.audit[0], description: text.pages.audit[1] },
      { id: 'planogram', label: text.pages.planogram[0], description: text.pages.planogram[1] },
      { id: 'tickets', label: text.pages.tickets[0], description: text.pages.tickets[1] },
      { id: 'chat', label: text.pages.chat[0], description: text.pages.chat[1] },
      { id: 'database', label: text.pages.database[0], description: text.pages.database[1] },
    ]
    if (canViewAccounts) {
      base.push({
        id: 'accounts',
        label: text.pages.accounts[0],
        description: text.pages.accounts[1],
      })
    }
    return base
  }, [text, canViewAccounts])

  // If the active page becomes unavailable (e.g. staff can't see accounts),
  // fall back to the audit page.
  useEffect(() => {
    if (!pages.some((page) => page.id === activePageId)) {
      setActivePageId('audit')
    }
  }, [pages, activePageId])

  function updateLanguage(nextLanguage: Language): void {
    setLanguage(nextLanguage)
    window.localStorage.setItem('yolo-retail-language', nextLanguage)
  }

  if (auth.status === 'loading') {
    return (
      <div className="app-loading" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <p style={{ color: 'var(--color-ink-muted)' }}>{text.auth.checking}</p>
      </div>
    )
  }

  if (auth.authEnabled && !auth.authenticated) {
    return (
      <LoginPanel
        text={text.auth}
        language={language}
        languageLabel={text.language}
        onLanguageChange={updateLanguage}
        errorMessage={auth.errorMessage}
        onSubmit={auth.login}
      />
    )
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
      userLabel={auth.username ? `${text.auth.signedInAs} ${auth.username}` : null}
      logoutLabel={auth.authEnabled ? text.auth.signOut : undefined}
      onLogout={auth.authEnabled ? auth.logout : undefined}
    >
      {activePageId === 'audit' ? (
        <ImageUploadPanel text={text.audit} language={language} audit={audit} canWrite={canWrite} />
      ) : null}

      {activePageId === 'planogram' ? (
        <PlanogramPanel text={text.planogram} canWrite={canWrite} readOnlyNotice={text.readOnlyNotice} />
      ) : null}

      {activePageId === 'tickets' ? (
        <TicketBoardPanel
          text={text.tickets}
          language={language}
          isAdmin={canWrite}
          canWrite={canWrite}
          readOnlyNotice={text.readOnlyNotice}
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

      {activePageId === 'database' ? (
        <DatabasePanel text={text.database} canWrite={canWrite} readOnlyNotice={text.readOnlyNotice} />
      ) : null}

      {activePageId === 'accounts' && canViewAccounts ? (
        <AccountsPanel
          text={text.accounts}
          language={language}
          canManage={canManageAccounts}
          currentUserId={auth.userId}
        />
      ) : null}
    </AppShell>
  )
}

export default App
