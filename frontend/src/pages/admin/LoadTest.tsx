import { useEffect, useState } from 'react'
import { Activity, ExternalLink, SlidersHorizontal, Terminal } from 'lucide-react'
import { Badge } from '../../components/ui/Badge'
import { Card } from '../../components/ui/Card'
import { EmptyState, PageHeader } from '../../components/ui/Misc'
import { useTheme } from '../../lib/theme'

/**
 * Live view of the Locust load tests in `attendance-load-testing/`.
 *
 * The tests run in their own processes against their own API instance and database; this page only *displays* the
 * harness's dashboard (served by Locust's web server, default http://localhost:8089/facegate) inside the admin console.
 * It never calls the FaceGate API and nothing here can start load against this installation's data.
 */
const BASE = (import.meta.env.VITE_LOADTEST_URL as string | undefined) ?? 'http://localhost:8089'

type Live = { state: string; finished: boolean; users: number; meta: { stage?: string; scenario?: string } }

export default function LoadTest() {
  const { resolved } = useTheme()
  const [live, setLive] = useState<Live | null>(null)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    let stop = false
    let timer = 0
    const tick = async () => {
      try {
        const r = await fetch(`${BASE}/facegate/data`, { cache: 'no-store' })
        const d = (await r.json()) as Live
        if (!stop) setLive(d)
      } catch {
        if (!stop) setLive(null)
      }
      if (!stop) { setChecked(true); timer = window.setTimeout(tick, 3000) }
    }
    void tick()
    return () => { stop = true; window.clearTimeout(timer) }
  }, [])

  const running = live?.state === 'running' || live?.state === 'spawning'
  const status = !live ? <Badge tone="neutral" dot>Harness offline</Badge>
    : running ? <Badge tone="success" dot>Running · {live.users} users</Badge>
    : live.finished ? <Badge tone="info" dot>Last run finished</Badge>
    : <Badge tone="neutral" dot>Idle</Badge>

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="Testing"
        title="Locust load test"
        description={<>Live results from the isolated load-test environment: simulated employees checking in by face against a separate test instance and database. {live?.meta.stage ? <span className="text-ink">Current: {live.meta.stage}.</span> : null}</>}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {status}
            <a href={`${BASE}/facegate?theme=${resolved}`} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-md border border-line-2 bg-surface px-4 text-sm font-medium text-ink hover:bg-surface-3"><ExternalLink className="size-4" aria-hidden /> Open full screen</a>
            <a href={BASE} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-md bg-brand-700 px-4 text-sm font-medium text-white shadow-sm hover:bg-brand-600"><SlidersHorizontal className="size-4" aria-hidden /> Locust controls</a>
          </div>
        }
      />

      {live ? (
        <Card className="overflow-hidden p-0">
          <iframe title="Locust load test dashboard" src={`${BASE}/facegate?theme=${resolved}`} className="block h-[calc(100dvh-13rem)] min-h-[640px] w-full border-0" />
        </Card>
      ) : checked ? (
        <Card>
          <EmptyState
            icon={<Activity className="size-6" aria-hidden />}
            title="The load-test harness is not running"
            description={<>This tab shows live results as soon as Locust is started on this machine. It checks again every few seconds.</>}
            action={
              <div className="mx-auto max-w-xl space-y-2 text-left text-sm">
                <p className="flex items-center gap-2 font-medium text-ink"><Terminal className="size-4" aria-hidden /> Start it from the repository folder</p>
                <pre className="scrollbar-thin overflow-x-auto rounded-md bg-surface-3 p-3 font-mono text-xs text-ink">cd attendance-load-testing{'\n'}./start.ps1{'\n'}.venv\Scripts\python tools\run_suite.py   # runs every stage</pre>
                <p className="text-xs text-ink-3">Looking for the dashboard at <code>{BASE}/facegate</code>. Set <code>VITE_LOADTEST_URL</code> to use another address. The tests never touch this installation&rsquo;s employees or attendance records.</p>
              </div>
            }
          />
        </Card>
      ) : (
        <Card className="grid h-64 place-items-center text-sm text-ink-3">Looking for the load-test harness…</Card>
      )}
    </div>
  )
}
