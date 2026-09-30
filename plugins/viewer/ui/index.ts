import { Images } from 'lucide-react'
import { registerPluginEventHandlers } from '@/store'
import { ViewerPage } from './ViewerPage'

// Bumps a counter on any index-affecting event so ViewerPage can refresh its lists —
// coalesced server-side into at most one viewer.index_changed per second, so this
// never fires per-file even during a big rescan or capture burst.
registerPluginEventHandlers('viewer', {
  'viewer.index_changed': (_event, cur) => ((cur as number) ?? 0) + 1,
  'viewer.rescan_completed': (_event, cur) => ((cur as number) ?? 0) + 1,
})

export default {
  icon: Images,
  label: 'Viewer',
  Component: ViewerPage,
}
