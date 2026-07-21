import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'

import {
  clearTickets,
  getTicket,
  getWebhookSettings,
  listTickets,
  redispatchTicket,
  saveWebhookSettings,
  testWebhook,
  updateTicketStatus,
  verifyTicket,
} from '@/api/tickets'
import { captureCameraDetection, listStreamCameras, listStreamModels } from '@/api/stream'
import { getActivePlanogramId, matchPlanogramDetections } from '@/api/planogram'
import { GlassSelect } from '@/components/ui/GlassSelect'
import type { Language, UI_TEXT } from '@/lib/i18n'
import type {
  AssigneeRole,
  IssueType,
  StaffRole,
  Ticket,
  TicketPriority,
  TicketStatus,
  WebhookChannel,
  WebhookEndpoint,
  WebhookProviderConfig,
  WebhookSettings,
} from '@/types/tickets'
import { FIXED_ISSUE_TYPES } from '@/types/tickets'

import styles from './TicketBoardPanel.module.css'

type BoardText = (typeof UI_TEXT)[Language]['tickets']

const BOARD_COLUMNS: TicketStatus[] = [
  'open',
  'dispatched',
  'in_progress',
  'done',
  'verified',
  'escalated',
]

const STATUS_OPTIONS: Array<TicketStatus | 'all'> = [
  'all',
  'open',
  'dispatched',
  'in_progress',
  'done',
  'verified',
  'escalated',
  'cancelled',
]

const PRIORITY_OPTIONS: Array<TicketPriority | 'all'> = ['all', 'critical', 'high', 'medium', 'low']
const ISSUE_OPTIONS = [
  'all',
  'out_of_stock',
  'shelf_empty',
  'low_stock',
  'camera_issue',
  'misplaced',
] as const
const CHANNELS: WebhookChannel[] = ['slack', 'wecom', 'generic']
const DEFAULT_ROLES: StaffRole[] = [
  { id: 'floor_staff', label: 'Floor staff' },
  { id: 'backroom', label: 'Backroom' },
  { id: 'manager', label: 'Manager' },
]
const DEFAULT_ISSUE_ROLE_MAP: Record<string, string[]> = {
  low_stock: ['backroom'],
  low_stock_warning: ['backroom'],
  out_of_stock: ['backroom'],
  shelf_empty: ['floor_staff'],
  camera_issue: ['floor_staff', 'manager'],
  misplaced: ['floor_staff'],
}

interface TicketBoardPanelProps {
  text: BoardText
  language: Language
  isAdmin: boolean
  /** When false the current user is read-only (staff): hide all ticket actions. */
  canWrite?: boolean
  readOnlyNotice?: string
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function priorityClass(priority: TicketPriority): string {
  if (priority === 'critical') return styles.priorityCritical
  if (priority === 'high') return styles.priorityHigh
  if (priority === 'medium') return styles.priorityMedium
  return styles.priorityLow
}

function emptyProvider(name: string): WebhookProviderConfig {
  return {
    enabled: false,
    endpoints: [
      {
        id: `ep-${name}-default`,
        name: 'Default',
        url: '',
        enabled: true,
      },
    ],
  }
}

function emptyWebhookSettings(): WebhookSettings {
  return {
    activeChannel: 'slack',
    slack: emptyProvider('slack'),
    wecom: emptyProvider('wecom'),
    generic: emptyProvider('generic'),
    defaultEndpointId: null,
    roles: DEFAULT_ROLES.map((role) => ({ ...role })),
    issueRoleMap: { ...DEFAULT_ISSUE_ROLE_MAP },
    roleRoutes: {},
  }
}

function normalizeProvider(raw: unknown, fallbackName: string): WebhookProviderConfig {
  const base = emptyProvider(fallbackName)
  if (!raw || typeof raw !== 'object') return base
  const data = raw as Record<string, unknown>
  // Legacy single-url shape
  if (Array.isArray(data.endpoints)) {
    return {
      enabled: Boolean(data.enabled),
      endpoints: (data.endpoints as WebhookEndpoint[]).map((ep, index) => ({
        id: ep.id || `ep-${fallbackName}-${index}`,
        name: ep.name || `Endpoint ${index + 1}`,
        url: ep.url || '',
        enabled: ep.enabled !== false,
      })),
    }
  }
  const url = String(data.url || '')
  const label = String(data.label || 'Default')
  return {
    enabled: Boolean(data.enabled),
    endpoints: url
      ? [
          {
            id: `ep-legacy-${fallbackName}`,
            name: label,
            url,
            enabled: Boolean(data.enabled),
          },
        ]
      : base.endpoints,
  }
}

function normalizeWebhookSettings(raw: WebhookSettings | Record<string, unknown>): WebhookSettings {
  const data = raw as Record<string, unknown>
  const defaults = emptyWebhookSettings()
  const roleRoutes =
    (data.roleRoutes as WebhookSettings['roleRoutes']) ||
    (data.roleChannels as WebhookSettings['roleRoutes']) ||
    {}
  const rolesRaw = Array.isArray(data.roles) ? (data.roles as StaffRole[]) : defaults.roles
  const roles = rolesRaw
    .map((role) => ({
      id: String(role.id || '')
        .trim()
        .toLowerCase()
        .replace(/\s+/g, '_'),
      label: String(role.label || role.id || '').trim() || 'Role',
    }))
    .filter((role, index, arr) => role.id && arr.findIndex((item) => item.id === role.id) === index)
  const issueRoleMapRaw =
    (data.issueRoleMap as WebhookSettings['issueRoleMap']) ||
    (data.issue_role_map as WebhookSettings['issueRoleMap']) ||
    {}
  const issueRoleMap: WebhookSettings['issueRoleMap'] = {}
  for (const issue of [...FIXED_ISSUE_TYPES, 'misplaced'] as IssueType[]) {
    const values = issueRoleMapRaw[issue] || DEFAULT_ISSUE_ROLE_MAP[issue] || ['floor_staff']
    issueRoleMap[issue] = Array.isArray(values)
      ? values.map((value) => String(value)).filter(Boolean)
      : [String(values)]
  }
  return {
    activeChannel: (data.activeChannel as WebhookChannel) || defaults.activeChannel,
    slack: normalizeProvider(data.slack, 'slack'),
    wecom: normalizeProvider(data.wecom, 'wecom'),
    generic: normalizeProvider(data.generic, 'generic'),
    defaultEndpointId: (data.defaultEndpointId as string | null | undefined) ?? null,
    roles: roles.length ? roles : defaults.roles,
    issueRoleMap,
    roleRoutes: roleRoutes || {},
  }
}

function roleLabel(settings: WebhookSettings, roleId: string, text: BoardText): string {
  const found = settings.roles.find((role) => role.id === roleId)
  if (found?.label) return found.label
  const builtin = text.assigneeLabels[roleId as keyof typeof text.assigneeLabels]
  return builtin || roleId
}

function ticketRoles(ticket: Ticket): string[] {
  const roles: string[] = []
  for (const role of ticket.assigneeRoles || []) {
    if (role && !roles.includes(role)) roles.push(role)
  }
  if (ticket.assigneeRole && !roles.includes(ticket.assigneeRole)) {
    roles.unshift(ticket.assigneeRole)
  }
  return roles
}

function allEndpointOptions(settings: WebhookSettings): Array<{ value: string; label: string }> {
  const options: Array<{ value: string; label: string }> = []
  for (const channel of CHANNELS) {
    const provider = settings[channel]
    for (const ep of provider.endpoints) {
      options.push({
        value: `${channel}:${ep.id}`,
        label: `${channel} · ${ep.name}`,
      })
    }
  }
  return options
}

function newEndpointId(channel: WebhookChannel): string {
  return `ep-${channel}-${Math.random().toString(36).slice(2, 8)}`
}

export function TicketBoardPanel({
  text,
  language,
  isAdmin,
  canWrite = true,
  readOnlyNotice,
}: TicketBoardPanelProps) {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [statusLine, setStatusLine] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<TicketStatus | 'all'>('all')
  const [priorityFilter, setPriorityFilter] = useState<TicketPriority | 'all'>('all')
  const [issueFilter, setIssueFilter] = useState<(typeof ISSUE_OPTIONS)[number]>('all')
  const [assigneeFilter, setAssigneeFilter] = useState<AssigneeRole | 'all'>('all')
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [busyTicketId, setBusyTicketId] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [webhookSettings, setWebhookSettings] = useState<WebhookSettings>(emptyWebhookSettings)
  const [settingsBusy, setSettingsBusy] = useState(false)
  const [verifyCamera, setVerifyCamera] = useState('0')
  const [verifyModel, setVerifyModel] = useState('')
  const [cameras, setCameras] = useState<Array<{ id: string; label: string }>>([])
  const [models, setModels] = useState<Array<{ id: string; label: string }>>([])

  const loadTickets = useCallback(async () => {
    setStatus('loading')
    setErrorMessage(null)
    try {
      const result = await listTickets({
        status: statusFilter,
        priority: priorityFilter,
        issueType: issueFilter,
        assigneeRole: assigneeFilter,
        keyword: keyword.trim() || undefined,
        limit: 200,
      })
      setTickets(result.tickets)
      setTotal(result.total)
      setStatus('idle')
    } catch {
      setErrorMessage(text.errors.loadFailed)
      setStatus('error')
    }
  }, [assigneeFilter, issueFilter, keyword, priorityFilter, statusFilter, text.errors.loadFailed])

  const loadControls = useCallback(async () => {
    try {
      const [cameraResponse, modelResponse] = await Promise.all([
        listStreamCameras(),
        listStreamModels(),
      ])
      setCameras(
        cameraResponse.cameras.map((camera) => ({
          id: camera.id,
          label: camera.label || camera.id,
        })),
      )
      setVerifyCamera(cameraResponse.defaultCamera || cameraResponse.cameras[0]?.id || '0')
      setModels(
        modelResponse.models.map((model) => ({
          id: model.id,
          label: model.label || model.id,
        })),
      )
      setVerifyModel(modelResponse.defaultModel || modelResponse.models[0]?.id || '')
    } catch {
      // Verify controls remain optional when model-local is offline.
    }
  }, [])

  const loadWebhookSettings = useCallback(async () => {
    if (!isAdmin) return
    try {
      const settings = await getWebhookSettings()
      setWebhookSettings(normalizeWebhookSettings(settings))
    } catch {
      setErrorMessage(text.errors.webhookLoadFailed)
    }
  }, [isAdmin, text.errors.webhookLoadFailed])

  useEffect(() => {
    void loadTickets()
    void loadControls()
  }, [loadControls, loadTickets])

  useEffect(() => {
    if (showSettings) {
      void loadWebhookSettings()
    }
  }, [loadWebhookSettings, showSettings])

  const columns = useMemo(() => {
    const map = new Map<TicketStatus, Ticket[]>()
    for (const column of BOARD_COLUMNS) {
      map.set(column, [])
    }
    for (const ticket of tickets) {
      const list = map.get(ticket.status)
      if (list) {
        list.push(ticket)
      } else if (ticket.status === 'cancelled') {
        // Keep cancelled tickets out of the main board columns unless filtered.
        continue
      }
    }
    return map
  }, [tickets])

  async function openTicket(ticket: Ticket): Promise<void> {
    try {
      const detail = await getTicket(ticket.id)
      setSelected(detail)
    } catch {
      setSelected(ticket)
    }
  }

  async function changeStatus(ticketId: string, nextStatus: TicketStatus, note?: string): Promise<void> {
    setBusyTicketId(ticketId)
    setStatusLine(null)
    setErrorMessage(null)
    try {
      const updated = await updateTicketStatus(ticketId, nextStatus, note)
      setTickets((previous) => previous.map((item) => (item.id === ticketId ? updated : item)))
      setSelected((previous) => (previous?.id === ticketId ? updated : previous))
      setStatusLine(text.statusUpdated)
    } catch {
      setErrorMessage(text.errors.updateFailed)
    } finally {
      setBusyTicketId(null)
    }
  }

  async function onRedispatch(ticketId: string): Promise<void> {
    setBusyTicketId(ticketId)
    setStatusLine(null)
    setErrorMessage(null)
    try {
      const result = await redispatchTicket(ticketId, language)
      if (result.ok) {
        setStatusLine(text.redispatched)
      } else {
        setErrorMessage(String(result.error || text.errors.dispatchFailed))
      }
      await loadTickets()
      if (selected?.id === ticketId) {
        const detail = await getTicket(ticketId)
        setSelected(detail)
      }
    } catch {
      setErrorMessage(text.errors.dispatchFailed)
    } finally {
      setBusyTicketId(null)
    }
  }

  async function onVerify(ticketId: string): Promise<void> {
    setBusyTicketId(ticketId)
    setStatusLine(null)
    setErrorMessage(null)
    try {
      const vision = await captureCameraDetection(verifyCamera, verifyModel)
      let planogramResponse: Record<string, unknown> | null = null
      const activeId = await getActivePlanogramId()
      if (activeId) {
        planogramResponse = (await matchPlanogramDetections(activeId, vision)) as unknown as Record<
          string,
          unknown
        >
      }
      const result = await verifyTicket(ticketId, {
        visionModelResponse: vision as unknown as Record<string, unknown>,
        planogramResponse,
        language,
        sourceLabel: `camera:${verifyCamera}`,
      })
      setSelected(result.ticket)
      setStatusLine(result.verified ? text.verifyClosed : text.verifyEscalated)
      await loadTickets()
    } catch {
      setErrorMessage(text.errors.verifyFailed)
    } finally {
      setBusyTicketId(null)
    }
  }

  async function onClearAllTickets(): Promise<void> {
    if (!window.confirm(text.confirmClearAll)) {
      return
    }
    setStatus('loading')
    setErrorMessage(null)
    setStatusLine(null)
    try {
      const result = await clearTickets()
      setTickets([])
      setTotal(0)
      setSelected(null)
      setStatusLine(text.clearedAll.replace('{count}', String(result.deleted ?? 0)))
      setStatus('idle')
    } catch {
      setErrorMessage(text.errors.clearFailed)
      setStatus('error')
    }
  }

  function onSubmitFilters(event: FormEvent): void {
    event.preventDefault()
    void loadTickets()
  }

  async function onSaveWebhooks(): Promise<void> {
    setSettingsBusy(true)
    setErrorMessage(null)
    setStatusLine(null)
    try {
      const saved = await saveWebhookSettings(webhookSettings)
      setWebhookSettings(normalizeWebhookSettings(saved))
      setStatusLine(text.webhooksSaved)
    } catch {
      setErrorMessage(text.errors.webhookSaveFailed)
    } finally {
      setSettingsBusy(false)
    }
  }

  async function onTestWebhook(channel: WebhookChannel, endpointId?: string): Promise<void> {
    setSettingsBusy(true)
    setErrorMessage(null)
    setStatusLine(null)
    try {
      const result = await testWebhook(
        channel,
        text.webhookTestMessage,
        webhookSettings,
        endpointId,
        language,
      )
      if (result.ok) {
        const endpointName = result.endpointName ? ` / ${String(result.endpointName)}` : ''
        setStatusLine(`${text.webhookTestOk} (${channel}${endpointName})`)
      } else {
        setErrorMessage(String(result.error || text.errors.webhookTestFailed))
      }
    } catch {
      setErrorMessage(text.errors.webhookTestFailed)
    } finally {
      setSettingsBusy(false)
    }
  }

  function updateProvider(
    channel: WebhookChannel,
    patch: Partial<WebhookProviderConfig>,
  ): void {
    setWebhookSettings((previous) => ({
      ...previous,
      [channel]: {
        ...previous[channel],
        ...patch,
      },
    }))
  }

  function updateEndpoint(
    channel: WebhookChannel,
    endpointId: string,
    patch: Partial<WebhookEndpoint>,
  ): void {
    setWebhookSettings((previous) => ({
      ...previous,
      [channel]: {
        ...previous[channel],
        endpoints: previous[channel].endpoints.map((ep) =>
          ep.id === endpointId ? { ...ep, ...patch } : ep,
        ),
      },
    }))
  }

  function addEndpoint(channel: WebhookChannel): void {
    const endpoint: WebhookEndpoint = {
      id: newEndpointId(channel),
      name: `${text.channelLabels[channel]} bot`,
      url: '',
      enabled: true,
    }
    setWebhookSettings((previous) => ({
      ...previous,
      [channel]: {
        ...previous[channel],
        enabled: true,
        endpoints: [...previous[channel].endpoints, endpoint],
      },
    }))
  }

  function removeEndpoint(channel: WebhookChannel, endpointId: string): void {
    setWebhookSettings((previous) => ({
      ...previous,
      [channel]: {
        ...previous[channel],
        endpoints: previous[channel].endpoints.filter((ep) => ep.id !== endpointId),
      },
    }))
  }

  const isLoading = status === 'loading'
  const selectedBusy = selected ? busyTicketId === selected.id : false
  const endpointOptions = allEndpointOptions(webhookSettings)

  return (
    <section className={styles.panel} aria-labelledby="ticket-board-title">
      <header className={styles.header}>
        <div>
          <h2 id="ticket-board-title" className={styles.title}>
            {text.title}
          </h2>
          <p className={styles.subtitle}>{text.subtitle}</p>
        </div>
        <div className={styles.headerActions}>
          {isAdmin ? (
            <button
              className={`${styles.ghostButton} glass-lens`}
              type="button"
              onClick={() => setShowSettings((value) => !value)}
            >
              {showSettings ? text.hideWebhooks : text.configureWebhooks}
            </button>
          ) : null}
          {canWrite ? (
            <button
              className={`${styles.dangerButton} glass-lens`}
              type="button"
              disabled={isLoading || total === 0}
              onClick={() => void onClearAllTickets()}
            >
              {text.clearAll}
            </button>
          ) : null}
          <button
            className={`${styles.button} glass-lens`}
            type="button"
            disabled={isLoading}
            onClick={() => void loadTickets()}
          >
            {isLoading ? text.loading : text.refresh}
          </button>
        </div>
      </header>

      <form className={styles.toolbar} onSubmit={onSubmitFilters}>
        <label className={styles.field}>
          <span>{text.search}</span>
          <input
            className={styles.input}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder={text.searchPlaceholder}
          />
        </label>
        <GlassSelect
          label={text.status}
          size="compact"
          value={statusFilter}
          options={STATUS_OPTIONS.map((value) => ({
            value,
            label: text.statusLabels[value],
          }))}
          onChange={(next) => setStatusFilter(next as TicketStatus | 'all')}
        />
        <GlassSelect
          label={text.priority}
          size="compact"
          value={priorityFilter}
          options={PRIORITY_OPTIONS.map((value) => ({
            value,
            label: text.priorityLabels[value],
          }))}
          onChange={(next) => setPriorityFilter(next as TicketPriority | 'all')}
        />
        <GlassSelect
          label={text.issueType}
          size="compact"
          value={issueFilter}
          options={ISSUE_OPTIONS.map((value) => ({
            value,
            label: text.issueLabels[value as keyof typeof text.issueLabels] || value,
          }))}
          onChange={(next) => setIssueFilter(next as (typeof ISSUE_OPTIONS)[number])}
        />
        <GlassSelect
          label={text.assignee}
          size="compact"
          value={assigneeFilter}
          options={[
            { value: 'all', label: text.assigneeLabels.all },
            ...webhookSettings.roles.map((role) => ({
              value: role.id,
              label: roleLabel(webhookSettings, role.id, text),
            })),
          ]}
          onChange={(next) => setAssigneeFilter(next as AssigneeRole | 'all')}
        />
        <button className={`${styles.primaryButton} glass-lens`} type="submit" disabled={isLoading}>
          {text.query}
        </button>
      </form>

      {errorMessage ? <p className={styles.errorLine}>{errorMessage}</p> : null}
      {statusLine ? <p className={styles.statusLine}>{statusLine}</p> : null}
      <p className={styles.statusLine}>
        {text.totalLabel.replace('{count}', String(total))}
      </p>

      {showSettings && isAdmin ? (
        <section className={styles.settingsCard} aria-label={text.webhookTitle}>
          <div className={styles.header}>
            <div>
              <h3 className={styles.title}>{text.webhookTitle}</h3>
              <p className={styles.subtitle}>{text.webhookSubtitle}</p>
            </div>
          </div>

          <GlassSelect
            label={text.activeChannel}
            size="compact"
            value={webhookSettings.activeChannel}
            options={CHANNELS.map((channel) => ({
              value: channel,
              label: text.channelLabels[channel],
            }))}
            onChange={(next) =>
              setWebhookSettings((previous) => ({
                ...previous,
                activeChannel: next as WebhookChannel,
              }))
            }
          />

          <div className={styles.settingsGrid}>
            {CHANNELS.map((channel) => {
              const config = webhookSettings[channel]
              return (
                <article key={channel} className={styles.channelCard}>
                  <div className={styles.channelHeader}>
                    <h4 className={styles.channelTitle}>{text.channelLabels[channel]}</h4>
                    <label className={styles.checkboxRow}>
                      <input
                        type="checkbox"
                        checked={config.enabled}
                        onChange={(event) =>
                          updateProvider(channel, { enabled: event.target.checked })
                        }
                      />
                      <span>{text.enabled}</span>
                    </label>
                  </div>

                  <div className={styles.endpointStack}>
                  {config.endpoints.map((endpoint) => (
                    <div key={endpoint.id} className={styles.endpointCard}>
                      <label className={styles.field}>
                        <span>{text.endpointName}</span>
                        <input
                          className={styles.input}
                          value={endpoint.name}
                          onChange={(event) =>
                            updateEndpoint(channel, endpoint.id, { name: event.target.value })
                          }
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{text.webhookUrl}</span>
                        <input
                          className={styles.input}
                          value={endpoint.url}
                          onChange={(event) =>
                            updateEndpoint(channel, endpoint.id, { url: event.target.value })
                          }
                          placeholder={text.webhookUrlPlaceholder}
                        />
                      </label>
                      <div className={styles.actionRow}>
                        <label className={styles.checkboxRow}>
                          <input
                            type="checkbox"
                            checked={endpoint.enabled}
                            onChange={(event) =>
                              updateEndpoint(channel, endpoint.id, {
                                enabled: event.target.checked,
                              })
                            }
                          />
                          <span>{text.enabled}</span>
                        </label>
                        <button
                          className={`${styles.ghostButton} glass-lens`}
                          type="button"
                          disabled={settingsBusy}
                          onClick={() => void onTestWebhook(channel, endpoint.id)}
                        >
                          {text.testWebhook}
                        </button>
                        <button
                          className={`${styles.dangerButton} glass-lens`}
                          type="button"
                          disabled={settingsBusy || config.endpoints.length <= 1}
                          onClick={() => removeEndpoint(channel, endpoint.id)}
                        >
                          {text.removeEndpoint}
                        </button>
                      </div>
                    </div>
                  ))}
                  </div>

                  <button
                    className={`${styles.ghostButton} glass-lens`}
                    type="button"
                    onClick={() => addEndpoint(channel)}
                  >
                    {text.addEndpoint}
                  </button>
                </article>
              )
            })}
          </div>

          <div className={styles.roleMap}>
            <p className={styles.subtitle}>{text.rolesHint}</p>
            {webhookSettings.roles.map((role, index) => (
              <div key={role.id || index} className={styles.endpointCard}>
                <label className={styles.field}>
                  <span>{text.roleId}</span>
                  <input
                    className={styles.input}
                    value={role.id}
                    onChange={(event) => {
                      const nextId = event.target.value
                        .trim()
                        .toLowerCase()
                        .replace(/\s+/g, '_')
                      setWebhookSettings((previous) => {
                        const roles = previous.roles.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, id: nextId } : item,
                        )
                        const roleRoutes = { ...previous.roleRoutes }
                        if (role.id && role.id in roleRoutes) {
                          roleRoutes[nextId] = roleRoutes[role.id]
                          delete roleRoutes[role.id]
                        }
                        const issueRoleMap = { ...previous.issueRoleMap }
                        for (const issue of Object.keys(issueRoleMap) as IssueType[]) {
                          issueRoleMap[issue] = (issueRoleMap[issue] || []).map((value) =>
                            value === role.id ? nextId : value,
                          )
                        }
                        return { ...previous, roles, roleRoutes, issueRoleMap }
                      })
                    }}
                  />
                </label>
                <label className={styles.field}>
                  <span>{text.roleLabel}</span>
                  <input
                    className={styles.input}
                    value={role.label}
                    onChange={(event) => {
                      const label = event.target.value
                      setWebhookSettings((previous) => ({
                        ...previous,
                        roles: previous.roles.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, label } : item,
                        ),
                      }))
                    }}
                  />
                </label>
                <label className={styles.field}>
                  <span>
                    {text.roleChannel} · {role.label || role.id}
                  </span>
                  <GlassSelect
                    size="compact"
                    value={webhookSettings.roleRoutes[role.id] || ''}
                    options={[
                      { value: '', label: text.useActiveChannel },
                      ...endpointOptions.map((option) => ({
                        value: option.value,
                        label: option.label,
                      })),
                    ]}
                    onChange={(value) => {
                      setWebhookSettings((previous) => {
                        const next = { ...previous.roleRoutes }
                        if (!value) {
                          delete next[role.id]
                        } else {
                          next[role.id] = value
                        }
                        return { ...previous, roleRoutes: next }
                      })
                    }}
                  />
                </label>
                <button
                  className={`${styles.dangerButton} glass-lens`}
                  type="button"
                  disabled={settingsBusy || webhookSettings.roles.length <= 1}
                  onClick={() => {
                    setWebhookSettings((previous) => {
                      const roles = previous.roles.filter((item) => item.id !== role.id)
                      const roleRoutes = { ...previous.roleRoutes }
                      delete roleRoutes[role.id]
                      const issueRoleMap = { ...previous.issueRoleMap }
                      for (const issue of Object.keys(issueRoleMap) as IssueType[]) {
                        const nextRoles = (issueRoleMap[issue] || []).filter((value) => value !== role.id)
                        issueRoleMap[issue] = nextRoles.length
                          ? nextRoles
                          : DEFAULT_ISSUE_ROLE_MAP[issue] || ['floor_staff']
                      }
                      return { ...previous, roles, roleRoutes, issueRoleMap }
                    })
                  }}
                >
                  {text.removeRole}
                </button>
              </div>
            ))}
            <button
              className={`${styles.ghostButton} glass-lens`}
              type="button"
              onClick={() => {
                const id = `role_${Math.random().toString(36).slice(2, 7)}`
                setWebhookSettings((previous) => ({
                  ...previous,
                  roles: [...previous.roles, { id, label: text.newRoleLabel }],
                }))
              }}
            >
              {text.addRole}
            </button>
          </div>

          <div className={styles.roleMap}>
            <p className={styles.subtitle}>{text.issueRoleHint}</p>
            {FIXED_ISSUE_TYPES.map((issue) => {
              const selected = webhookSettings.issueRoleMap[issue] || DEFAULT_ISSUE_ROLE_MAP[issue] || []
              return (
                <div key={issue} className={styles.endpointCard}>
                  <p className={styles.cardTitle}>
                    {text.issueLabels[issue as keyof typeof text.issueLabels] || issue}
                  </p>
                  <div className={styles.badgeRow}>
                    {webhookSettings.roles.map((role) => {
                      const checked = selected.includes(role.id)
                      return (
                        <label key={role.id} className={styles.checkboxRow}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) => {
                              const enabled = event.target.checked
                              setWebhookSettings((previous) => {
                                const current = new Set(previous.issueRoleMap[issue] || [])
                                if (enabled) {
                                  current.add(role.id)
                                } else {
                                  current.delete(role.id)
                                }
                                const nextRoles = Array.from(current)
                                return {
                                  ...previous,
                                  issueRoleMap: {
                                    ...previous.issueRoleMap,
                                    [issue]: nextRoles.length
                                      ? nextRoles
                                      : DEFAULT_ISSUE_ROLE_MAP[issue] || [role.id],
                                  },
                                }
                              })
                            }}
                          />
                          <span>{roleLabel(webhookSettings, role.id, text)}</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>

          <div className={styles.actionRow}>
            <button
              className={`${styles.primaryButton} glass-lens`}
              type="button"
              disabled={settingsBusy}
              onClick={() => void onSaveWebhooks()}
            >
              {settingsBusy ? text.saving : text.saveWebhooks}
            </button>
          </div>
        </section>
      ) : null}

      <div className={styles.board}>
        {BOARD_COLUMNS.map((column) => {
          const items = columns.get(column) ?? []
          return (
            <section key={column} className={styles.column} aria-label={text.statusLabels[column]}>
              <div className={styles.columnHeader}>
                <h3 className={styles.columnTitle}>{text.statusLabels[column]}</h3>
                <span className={styles.columnCount}>{items.length}</span>
              </div>
              <div className={styles.cardList}>
                {items.length > 0 ? (
                  items.map((ticket) => (
                    <button
                      key={ticket.id}
                      type="button"
                      className={`${styles.card} glass-lens`}
                      onClick={() => void openTicket(ticket)}
                    >
                      <p className={styles.cardTitle}>{ticket.title}</p>
                      <div className={styles.badgeRow}>
                        <span className={`${styles.badge} ${priorityClass(ticket.priority)}`}>
                          {text.priorityLabels[ticket.priority]}
                        </span>
                        <span className={styles.badge}>
                          {text.issueLabels[ticket.issueType as keyof typeof text.issueLabels] ||
                            ticket.issueType}
                        </span>
                        <span className={styles.badge}>
                          {ticketRoles(ticket)
                            .map((role) => roleLabel(webhookSettings, role, text))
                            .join(', ')}
                        </span>
                      </div>
                      <p className={styles.cardDesc}>{ticket.description || text.noDescription}</p>
                      <p className={styles.cardMeta}>
                        {ticket.sku || ticket.itemName || ticket.shelfLabel || ticket.id}
                      </p>
                    </button>
                  ))
                ) : (
                  <div className={styles.emptyState}>
                    <p className={styles.emptyTitle}>{text.emptyColumn}</p>
                  </div>
                )}
              </div>
            </section>
          )
        })}
      </div>

      {tickets.length === 0 && !isLoading ? (
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>{text.emptyTitle}</p>
          <p className={styles.emptyCopy}>{text.emptyCopy}</p>
        </div>
      ) : null}

      {selected ? (
        <div className={styles.detailOverlay} role="dialog" aria-modal="true" aria-label={text.detailTitle}>
          <div className={styles.detailCard}>
            <header className={styles.detailHeader}>
              <div>
                <p className={styles.detailEyebrow}>
                  {text.statusLabels[selected.status]} · {text.priorityLabels[selected.priority]}
                </p>
                <h3 className={styles.detailTitle}>{selected.title}</h3>
                <p className={styles.detailMeta}>
                  {selected.id} · {formatDate(selected.updatedAt)}
                </p>
              </div>
              <button className={`${styles.ghostButton} glass-lens`} type="button" onClick={() => setSelected(null)}>
                {text.close}
              </button>
            </header>

            <p className={styles.detailBody}>{selected.description || text.noDescription}</p>
            <p className={styles.detailMeta}>
              {text.issueType}:{' '}
              {text.issueLabels[selected.issueType as keyof typeof text.issueLabels] ||
                selected.issueType}{' '}
              · {text.assignee}:{' '}
              {ticketRoles(selected)
                .map((role) => roleLabel(webhookSettings, role, text))
                .join(', ')}
            </p>
            <p className={styles.detailMeta}>
              SKU: {selected.sku || '—'} · {selected.itemName || '—'} · {selected.shelfLabel || '—'}
            </p>
            <p className={styles.detailMeta}>
              {text.escalations}: {selected.escalateCount} · {text.dispatchedAt}:{' '}
              {formatDate(selected.dispatchedAt)} · {text.doneAt}: {formatDate(selected.doneAt)} ·{' '}
              {text.verifiedAt}: {formatDate(selected.verifiedAt)}
            </p>

            {!canWrite && readOnlyNotice ? (
              <p className={styles.detailMeta}>{readOnlyNotice}</p>
            ) : null}

            {canWrite ? (
              <div className={styles.actionRow}>
                {selected.status === 'open' || selected.status === 'escalated' ? (
                  <button
                    className={`${styles.primaryButton} glass-lens`}
                    type="button"
                    disabled={selectedBusy}
                    onClick={() => void onRedispatch(selected.id)}
                  >
                    {text.dispatch}
                  </button>
                ) : null}
                {selected.status === 'dispatched' || selected.status === 'open' ? (
                  <button
                    className={`${styles.button} glass-lens`}
                    type="button"
                    disabled={selectedBusy}
                    onClick={() => void changeStatus(selected.id, 'in_progress', 'Staff started work')}
                  >
                    {text.markInProgress}
                  </button>
                ) : null}
                {selected.status === 'in_progress' || selected.status === 'dispatched' ? (
                  <button
                    className={`${styles.button} glass-lens`}
                    type="button"
                    disabled={selectedBusy}
                    onClick={() => void changeStatus(selected.id, 'done', 'Marked done by staff')}
                  >
                    {text.markDone}
                  </button>
                ) : null}
                {selected.status !== 'cancelled' && selected.status !== 'verified' ? (
                  <button
                    className={`${styles.dangerButton} glass-lens`}
                    type="button"
                    disabled={selectedBusy}
                    onClick={() => void changeStatus(selected.id, 'cancelled', 'Cancelled')}
                  >
                    {text.cancel}
                  </button>
                ) : null}
              </div>
            ) : null}

            {canWrite && selected.status === 'done' ? (
              <div className={styles.verifyBox}>
                <p className={styles.detailBody}>{text.verifyHint}</p>
                <div className={styles.actionRow}>
                  <label className={styles.field}>
                    <span>{text.camera}</span>
                    <GlassSelect
                      size="compact"
                      value={verifyCamera}
                      options={(cameras.length > 0 ? cameras : [{ id: '0', label: text.cameraFallback }]).map(
                        (camera) => ({
                          value: camera.id,
                          label: camera.label,
                        }),
                      )}
                      onChange={setVerifyCamera}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{text.model}</span>
                    <GlassSelect
                      size="compact"
                      value={verifyModel}
                      options={(models.length > 0 ? models : [{ id: '', label: text.defaultModel }]).map(
                        (model) => ({
                          value: model.id,
                          label: model.label,
                        }),
                      )}
                      onChange={setVerifyModel}
                    />
                  </label>
                  <button
                    className={`${styles.primaryButton} glass-lens`}
                    type="button"
                    disabled={selectedBusy}
                    onClick={() => void onVerify(selected.id)}
                  >
                    {text.verifyRescan}
                  </button>
                </div>
              </div>
            ) : null}

            <section className={styles.jsonBlock}>
              <h4 className={styles.jsonTitle}>{text.history}</h4>
              <ul className={styles.historyList}>
                {(selected.history || []).slice().reverse().map((event, index) => (
                  <li key={`${event.at}-${event.event}-${index}`} className={styles.historyItem}>
                    <p className={styles.historyEvent}>
                      {event.event} · {formatDate(event.at)}
                    </p>
                    {event.note ? <p className={styles.historyNote}>{String(event.note)}</p> : null}
                  </li>
                ))}
              </ul>
            </section>

            {selected.evidence ? (
              <section className={styles.jsonBlock}>
                <h4 className={styles.jsonTitle}>{text.evidence}</h4>
                <pre className={styles.jsonPre}>{JSON.stringify(selected.evidence, null, 2)}</pre>
              </section>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}
